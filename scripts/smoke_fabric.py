"""Read-only cloud validation; no creates, refreshes, notebook runs, or fallback."""
from __future__ import annotations

import argparse
import base64
import csv
import json
from pathlib import Path
from typing import Any

from construction_iq.config import DATA_ROOT, ROOT, DemoProfile
from construction_iq.fabric_api import (
    FabricApiError, FabricRestClient, KustoClient, OneLakeClient,
    gql_identifier, kql_connection, load_partial_deployment, require_fabric_items, verify_owned_workspace,
)
from construction_iq.fabric_artifacts import (
    FABRIC_EVENTHOUSE_NAME, FABRIC_INGEST_NOTEBOOK_NAME, FABRIC_KQL_DATABASE_NAME,
    FABRIC_LAKEHOUSE_NAME, FABRIC_ONTOLOGY_NAME, INGEST_RECEIPT_PATH,
    dataset_contract, key_path_edges_present, ontology_definition, source_model,
)
from construction_iq.schema_contract import EVENTHOUSE_TABLES


CDP_TO_SUPPLY_QUERY = """
MATCH (`profile`:`UnifiedProfile`)-[:`member_of_audience`]->(`audience`:`Audience`)
      -[:`activated_through`]->(`activation`:`Activation`)-[:`supports_campaign`]->(`campaign`:`Campaign`)
      -[:`generates_demand_signal`]->(`signal`:`DemandSignal`)-[:`requests_product`]->(`product`:`Product`)
      -[:`has_constraint`]->(`constraint`:`SupplyConstraint`)-[:`exposes_commitment`]->(`commitment`:`CustomerCommitment`)
      -[:`has_business_risk`]->(`risk`:`BusinessRisk`)
RETURN `profile`.`profile_id` AS profileId, `audience`.`audience_id` AS audienceId,
       `activation`.`activation_id` AS activationId, `campaign`.`campaign_id` AS campaignId,
       `signal`.`demand_signal_id` AS demandSignalId, `product`.`product_id` AS productId,
       `constraint`.`constraint_id` AS constraintId, `commitment`.`commitment_id` AS commitmentId,
       `risk`.`business_risk_id` AS businessRiskId
LIMIT 1
""".strip()

SUPPRESSION_GOVERNANCE_QUERY = """
MATCH (`event`:`ActivationEvent`)-[:`event_for_profile`]->(`profile`:`UnifiedProfile`),
      (`event`)-[:`event_for_activation`]->(`activation`:`Activation`)-[:`activates_audience`]->(`audience`:`Audience`),
      (`event`)-[:`blocked_by`]->(`rule`:`SuppressionRule`),
      (`audience`)-[:`governed_by`]->(`rule`),
      (`profile`)-[:`member_of_audience`]->(`audience`),
      (`profile`)-[:`has_consent`]->(`consent`:`ConsentRecord`)
RETURN DISTINCT `event`.`activation_event_id` AS activationEventId
""".strip()


def validate_native_traversals(
    fabric: FabricRestClient, workspace_id: str, graph_id: str, expected_suppression_ids: set[str],
) -> dict[str, Any]:
    chain = fabric.query_graph(workspace_id, graph_id, CDP_TO_SUPPLY_QUERY)
    required = {
        "profileId", "audienceId", "activationId", "campaignId", "demandSignalId",
        "productId", "constraintId", "commitmentId", "businessRiskId",
    }
    if not chain or any(not isinstance(row.get(key), str) or not row[key] for row in chain for key in required):
        raise FabricApiError("Native CDP-to-supply traversal did not return a complete linked evidence path.")
    if not expected_suppression_ids:
        raise FabricApiError("Dataset has no suppression events to validate native governance relationships.")
    governance = fabric.query_graph(workspace_id, graph_id, SUPPRESSION_GOVERNANCE_QUERY)
    if any(not isinstance(row.get("activationEventId"), str) or not row["activationEventId"] for row in governance):
        raise FabricApiError("Native suppression traversal returned an invalid event ID.")
    actual_ids = {row["activationEventId"] for row in governance}
    if actual_ids != expected_suppression_ids:
        raise FabricApiError(
            "Native suppression traversal differs from the event facts; every blocked event must reach its "
            "profile, activation, actual rule/audience and consent. "
            f"Missing={sorted(expected_suppression_ids - actual_ids)}, unexpected={sorted(str(value) for value in actual_ids - expected_suppression_ids)}"
        )
    return {"cdpToSupply": chain, "suppressionEventIds": sorted(expected_suppression_ids)}


def smoke() -> dict[str, Any]:
    profile = DemoProfile.load()
    manifest = load_partial_deployment(profile=profile)
    items = require_fabric_items(manifest)
    contract = dataset_contract(DATA_ROOT)
    expected_counts = {table["name"]: table["count"] for table in contract["tables"]}
    fabric = FabricRestClient()
    verify_owned_workspace(fabric, manifest, profile)
    workspace_id = manifest["workspaceId"]
    expected_items = (
        ("lakehouseId", "Lakehouse", FABRIC_LAKEHOUSE_NAME),
        ("eventhouseId", "Eventhouse", FABRIC_EVENTHOUSE_NAME),
        ("kqlDatabaseId", "KQLDatabase", FABRIC_KQL_DATABASE_NAME),
        ("ontologyId", "Ontology", FABRIC_ONTOLOGY_NAME),
        ("notebookId", "Notebook", FABRIC_INGEST_NOTEBOOK_NAME),
        ("graphModelId", "GraphModel", f"{FABRIC_ONTOLOGY_NAME}_graph_{items['ontologyId'].replace('-', '')}"),
    )
    for key, item_type, name in expected_items:
        actual = fabric.request("GET", f"/workspaces/{workspace_id}/items/{items[key]}")
        if (actual.get("id"), actual.get("type"), actual.get("displayName")) != (items[key], item_type, name):
            raise FabricApiError(f"Owned {key} no longer matches its recorded type/name/ID.")
    kql = fabric.request("GET", f"/workspaces/{workspace_id}/kqlDatabases/{items['kqlDatabaseId']}")
    properties = kql.get("properties", {})
    if (*kql_connection(kql), properties.get("parentEventhouseItemId")) != (
        items["kqlQueryUri"], items["kqlDatabaseName"], items["eventhouseId"],
    ):
        raise FabricApiError("Recorded KQL endpoint/database/parent differs from the live owned database.")

    receipt = OneLakeClient().read_json(workspace_id, items["lakehouseId"], INGEST_RECEIPT_PATH)
    if receipt != {"datasetSignature": contract["datasetSignature"], "counts": expected_counts, "schemaValidated": True}:
        raise FabricApiError("Lakehouse ingest validation receipt differs from the local dataset.")
    live = fabric.request("POST", f"/workspaces/{workspace_id}/items/{items['ontologyId']}/getDefinition", {})
    parts = live.get("definition", live).get("parts", [])
    decoded = {part["path"]: json.loads(base64.b64decode(part["payload"])) for part in parts}
    for part in ontology_definition(workspace_id, items["lakehouseId"])["parts"]:
        if part["path"] in {".platform", "definition.json"}:
            continue
        expected = json.loads(base64.b64decode(part["payload"]))
        actual = decoded.get(part["path"])
        if not isinstance(actual, dict) or any(actual.get(key) != value for key, value in expected.items()):
            raise FabricApiError(f"Native ontology definition/binding mismatch: {part['path']}")
    path = key_path_edges_present()
    if not path["complete"]:
        raise FabricApiError(f"Ontology chain is incomplete: {path}")
    entities, _, _ = source_model()
    graph_counts: dict[str, int] = {}
    for label, table in entities.items():
        rows = fabric.query_graph(workspace_id, items["graphModelId"], f"MATCH (n:{gql_identifier(label)}) RETURN count(n) AS rowCount")
        if len(rows) != 1 or rows[0].get("rowCount") != expected_counts[table.name]:
            raise FabricApiError(f"Graph count differs from the dataset for {label}: {rows}")
        graph_counts[table.name] = rows[0]["rowCount"]
    kusto = KustoClient(items["kqlQueryUri"], items["kqlDatabaseName"])
    event_counts = {table.name: kusto.scalar_count(table.name) for table in EVENTHOUSE_TABLES}
    if event_counts != {table.name: expected_counts[table.name] for table in EVENTHOUSE_TABLES}:
        raise FabricApiError("Eventhouse row counts differ from the dataset.")
    activation_events = next(table for table in EVENTHOUSE_TABLES if table.name == "activation_events")
    with (DATA_ROOT / activation_events.folder / "activation_events.csv").open(encoding="utf-8", newline="") as handle:
        suppressed = {row["activation_event_id"] for row in csv.DictReader(handle) if row["suppression_rule_id"]}
    traversals = validate_native_traversals(fabric, workspace_id, items["graphModelId"], suppressed)
    return {
        "complete": True, "scope": "Fabric infrastructure only; not three-lane IQ retrieval acceptance",
        "workspaceId": workspace_id, "ontologyId": items["ontologyId"], "graphModelId": items["graphModelId"],
        "datasetSignature": contract["datasetSignature"], "graphCounts": graph_counts, "eventhouseCounts": event_counts,
        "lakehouseSchemaAndCountReceipt": receipt, "keyOntologyPath": path,
        "nativeTraversalProofs": traversals,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "tests" / "results" / "fabric-smoke.json")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"complete": False, "state": "running"}), encoding="utf-8")
    try:
        result = smoke()
    except (FabricApiError, ValueError, OSError) as error:
        args.output.write_text(json.dumps({"complete": False, "error": str(error)}, indent=2), encoding="utf-8")
        raise
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
