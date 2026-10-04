"""Provision only after separate cloud approval. No import-time cloud calls."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from construction_iq.config import DATA_ROOT, DEPLOYMENT_PATH, DemoProfile
from construction_iq.fabric_api import (
    FabricApiError, FabricRestClient, KustoClient, OneLakeClient,
    kql_connection, load_partial_deployment, merge_deployment, verify_owned_workspace,
)
from construction_iq.fabric_artifacts import (
    FABRIC_EVENTHOUSE_NAME, FABRIC_INGEST_NOTEBOOK_NAME, FABRIC_KQL_DATABASE_NAME,
    FABRIC_LAKEHOUSE_NAME, FABRIC_ONTOLOGY_NAME, INGEST_RECEIPT_PATH, ONTOLOGY_SOURCE,
    REMOTE_DATA_ROOT, build_ingest_notebook_definition, dataset_contract,
    eventhouse_replace_command, key_path_edges_present, ontology_definition,
)
from construction_iq.schema_contract import ALL_TABLES, EVENTHOUSE_TABLES


def ensure_workspace(fabric: FabricRestClient, profile: DemoProfile, path: Path = DEPLOYMENT_PATH) -> dict[str, Any]:
    manifest = load_partial_deployment(path, profile)
    if manifest.get("workspaceId"):
        return verify_owned_workspace(fabric, manifest, profile)
    conflicts = [item for item in fabric.list_all("/workspaces") if item.get("displayName", "").strip().casefold() == profile.workspace_name.strip().casefold()]
    if conflicts:
        raise FabricApiError("An unowned workspace already uses the requested name. Refusing adoption; no resources changed.")
    created = fabric.request("POST", "/workspaces", {
        "displayName": profile.workspace_name, "capacityId": profile.capacity_id,
        "description": "Isolated construction3iq demonstration. Synthetic data; no live Microsoft 365 connection.",
    })
    if not created.get("id"):
        raise FabricApiError("Workspace creation returned no ID. Inspect the operation; never adopt a same-named workspace.", payload=created)
    UUID(created["id"])
    merge_deployment({"workspaceId": created["id"]}, path, profile)
    return verify_owned_workspace(fabric, load_partial_deployment(path, profile), profile)


def ensure_item(
    fabric: FabricRestClient, profile: DemoProfile, workspace_id: str, key: str,
    name: str, item_type: str, *, definition: dict[str, Any] | None = None,
    creation_payload: dict[str, Any] | None = None, collection: str = "items",
    path: Path = DEPLOYMENT_PATH,
) -> dict[str, Any]:
    manifest = load_partial_deployment(path, profile)
    if manifest.get("workspaceId") != workspace_id:
        raise FabricApiError("Item creation workspace does not match the owned manifest.")
    item_id = manifest.get("items", {}).get(key)
    if item_id:
        UUID(item_id)
        item = fabric.request("GET", f"/workspaces/{workspace_id}/items/{item_id}")
        if item.get("id") != item_id or item.get("type") != item_type or item.get("displayName") != name:
            raise FabricApiError(f"Owned {key} no longer matches the expected type/name/ID.")
        if definition is not None:
            fabric.request("POST", f"/workspaces/{workspace_id}/items/{item_id}/updateDefinition", {"definition": definition})
        return item
    pending = manifest.get("pendingItemOperations", {}).get(key)
    if not pending:
        conflicts = [
            item for item in fabric.list_all(f"/workspaces/{workspace_id}/items")
            if item.get("displayName", "").strip().casefold() == name.casefold()
        ]
        if conflicts:
            raise FabricApiError(f"Unowned item named {name!r} exists. Refusing adoption or recreation.")
    body: dict[str, Any] = {"displayName": name, "description": "Synthetic construction3iq demo-owned artifact."}
    if collection == "items":
        body["type"] = item_type
    if creation_payload is not None:
        body["creationPayload"] = creation_payload
    if definition is not None:
        body["definition"] = definition
    if pending:
        created = fabric.wait_operation(pending)
    else:
        created = fabric.request(
            "POST", f"/workspaces/{workspace_id}/{collection}", body,
            on_accepted=lambda location: merge_deployment(
                {"pendingItemOperations": {key: location}}, path, profile
            ),
        )
    if not created.get("id"):
        raise FabricApiError(f"Creation returned no {item_type} ID. Inspect the operation; do not adopt by name.", payload=created)
    UUID(created["id"])
    verified = fabric.request("GET", f"/workspaces/{workspace_id}/items/{created['id']}")
    if verified.get("type") != item_type or verified.get("displayName") != name:
        raise FabricApiError("Created item does not match its submitted workspace, name, and type.")
    merge_deployment({"items": {key: created["id"]}, "pendingItemOperations": {key: None}}, path, profile)
    return verified


def discover_generated_graph(fabric: FabricRestClient, workspace_id: str, ontology_id: str, timeout_seconds: int = 600) -> dict[str, Any]:
    name = f"{FABRIC_ONTOLOGY_NAME}_graph_{ontology_id.replace('-', '')}"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        matches = [item for item in fabric.list_all(f"/workspaces/{workspace_id}/items?type=GraphModel") if item.get("displayName") == name]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise FabricApiError("Multiple ontology-generated graph helpers found; ownership is ambiguous.")
        time.sleep(10)
    raise FabricApiError("Native ontology did not expose its generated GraphModel. No standalone graph fallback is allowed.")


def refresh_graph(fabric: FabricRestClient, workspace_id: str, graph_id: str) -> dict[str, Any]:
    path = f"/workspaces/{workspace_id}/items/{graph_id}/jobs/instances"
    jobs = fabric.list_all(path)
    active = [job for job in jobs if job.get("status") in {"NotStarted", "Running", "InProgress"}]
    if len(active) > 1:
        raise FabricApiError("Multiple graph refresh jobs are active; cannot identify a unique refresh.")
    if active:
        job_id = active[0].get("id")
        if not isinstance(job_id, str):
            raise FabricApiError("Active graph refresh job has no ID.")
        UUID(job_id)
        return fabric.wait_job(workspace_id, graph_id, path + "/" + job_id)
    return fabric.run_job(workspace_id, graph_id, "RefreshGraph", {})


def deploy(profile: DemoProfile, data_root: Path, path: Path = DEPLOYMENT_PATH) -> None:
    contract = dataset_contract(data_root)
    if not key_path_edges_present()["complete"]:
        raise FabricApiError("Required CDP-to-supply ontology path is incomplete.")
    fabric = FabricRestClient()
    capacities = fabric.list_all("/capacities")
    capacity = next((item for item in capacities if item.get("id", "").lower() == profile.capacity_id.lower()), None)
    if not capacity or capacity.get("state") != "Active" or capacity.get("sku") != "F32":
        raise FabricApiError("Configured capacity must be visible, Active, and F32. This script never changes capacity settings.")
    workspace = ensure_workspace(fabric, profile, path)
    workspace_id = workspace["id"]
    lakehouse = ensure_item(fabric, profile, workspace_id, "lakehouseId", FABRIC_LAKEHOUSE_NAME, "Lakehouse", creation_payload={"enableSchemas": True}, path=path)
    eventhouse = ensure_item(fabric, profile, workspace_id, "eventhouseId", FABRIC_EVENTHOUSE_NAME, "Eventhouse", path=path)
    kql = ensure_item(
        fabric, profile, workspace_id, "kqlDatabaseId", FABRIC_KQL_DATABASE_NAME, "KQLDatabase",
        creation_payload={"databaseType": "ReadWrite", "parentEventhouseItemId": eventhouse["id"]},
        collection="kqlDatabases", path=path,
    )
    database = fabric.request("GET", f"/workspaces/{workspace_id}/kqlDatabases/{kql['id']}")
    properties = database.get("properties", {})
    if properties.get("parentEventhouseItemId") != eventhouse["id"]:
        raise FabricApiError("KQL database parent does not match the owned Eventhouse.", payload=database)
    query_uri, database_name = kql_connection(database)
    merge_deployment({"items": {"kqlQueryUri": query_uri, "kqlDatabaseName": database_name}}, path, profile)

    onelake = OneLakeClient()
    for table in ALL_TABLES:
        onelake.upload_file(workspace_id, lakehouse["id"], data_root / table.folder / f"{table.name}.csv", f"{REMOTE_DATA_ROOT}/{table.folder}/{table.name}.csv")
    onelake.upload_file(workspace_id, lakehouse["id"], ONTOLOGY_SOURCE, "Files/ontology/construction-ontology.json")
    notebook = ensure_item(
        fabric, profile, workspace_id, "notebookId", FABRIC_INGEST_NOTEBOOK_NAME, "Notebook",
        definition=build_ingest_notebook_definition(workspace_id, lakehouse["id"], contract), path=path,
    )
    notebook_job = fabric.run_job(workspace_id, notebook["id"], "RunNotebook", {
        "executionData": {"configuration": {"useStarterPool": True, "defaultLakehouse": {
            "id": lakehouse["id"], "name": FABRIC_LAKEHOUSE_NAME, "workspaceId": workspace_id,
        }}},
    })
    expected_counts = {table["name"]: table["count"] for table in contract["tables"]}
    receipt = onelake.read_json(workspace_id, lakehouse["id"], INGEST_RECEIPT_PATH)
    if receipt != {"datasetSignature": contract["datasetSignature"], "counts": expected_counts, "schemaValidated": True}:
        raise FabricApiError("Notebook completed without the exact expected schema/count/digest validation receipt.", payload=receipt)

    kusto = KustoClient(query_uri, database_name)
    for table in EVENTHOUSE_TABLES:
        kusto.execute_mgmt(eventhouse_replace_command(table, data_root))
        if kusto.scalar_count(table.name) != expected_counts[table.name]:
            raise FabricApiError(f"Eventhouse row-count mismatch: {table.name}")

    ontology = ensure_item(
        fabric, profile, workspace_id, "ontologyId", FABRIC_ONTOLOGY_NAME, "Ontology",
        definition=ontology_definition(workspace_id, lakehouse["id"]), collection="ontologies", path=path,
    )
    graph = discover_generated_graph(fabric, workspace_id, ontology["id"])
    merge_deployment({"items": {"graphModelId": graph["id"]}}, path, profile)
    graph_job = refresh_graph(fabric, workspace_id, graph["id"])
    live_count = fabric.query_graph(workspace_id, graph["id"], "MATCH (d:DemandRecord) RETURN count(d) AS rowCount")
    if len(live_count) != 1 or live_count[0].get("rowCount") != expected_counts["demand_records"]:
        raise FabricApiError("Native ontology-generated graph did not return the expected live demand-record count.", payload=live_count)
    inventory = fabric.list_all(f"/workspaces/{workspace_id}/items")
    merge_deployment({
        "fabricValidation": {
            "datasetSignature": contract["datasetSignature"], "lakehouseCounts": expected_counts,
            "notebookJobId": notebook_job.get("id"), "graphJobId": graph_job.get("id"), "liveSmokePassed": False,
            "liveDemandRecordCount": live_count[0]["rowCount"],
        },
        "fabricOwnedItems": [{"id": item["id"], "type": item["type"], "displayName": item["displayName"]} for item in inventory],
    }, path, profile)
    print("Fabric provisioning and ingestion completed. Run scripts/smoke_fabric.py; this is not IQ retrieval acceptance.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy only the isolated construction workspace after separate cloud approval.")
    parser.add_argument("--approve-provisioning", action="store_true", help="Required acknowledgement of separately approved cloud creation.")
    args = parser.parse_args()
    if not args.approve_provisioning:
        parser.error("Cloud provisioning requires separate approval and --approve-provisioning.")
    deploy(DemoProfile.load(), DATA_ROOT)


if __name__ == "__main__":
    main()
