from __future__ import annotations

import base64
import csv
import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from construction_iq.config import ROOT, DemoProfile
from construction_iq.fabric_api import (
    FabricApiError, FabricRestClient, HttpResponse, KustoClient, OneLakeClient,
    get_az_token, load_partial_deployment, manifest_base, merge_deployment, require_fabric_items,
)
from construction_iq.fabric_artifacts import (
    FABRIC_ONTOLOGY_NAME, build_ingest_notebook_definition, dataset_contract,
    eventhouse_replace_command, key_path_edges_present, ontology_definition, source_model,
)
from construction_iq.schema_contract import ALL_TABLES, EVENTHOUSE_TABLES, ColumnSpec, TableSpec

WORKSPACE_ID = "11111111-1111-4111-8111-111111111111"
LAKEHOUSE_ID = "22222222-2222-4222-8222-222222222222"
ONTOLOGY_ID = "33333333-3333-4333-8333-333333333333"
GRAPH_ID = "44444444-4444-4444-8444-444444444444"
JOB_URL = f"https://api.fabric.microsoft.com/v1/workspaces/{WORKSPACE_ID}/items/{LAKEHOUSE_ID}/jobs/instances/{GRAPH_ID}"
OPERATION_URL = f"https://api.fabric.microsoft.com/v1/operations/{GRAPH_ID}"


def script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_csv_fixture(root: Path) -> None:
    for table in ALL_TABLES:
        path = root / table.folder / f"{table.name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow([column.name for column in table.columns])
            writer.writerow([
                column.enum_values[0] if column.enum_values else {
                    "utc_timestamp": "2026-10-01T00:00:00Z", "date": "2026-10-01",
                    "double": "1.5", "decimal": "20.00", "int": "1", "bool": "true",
                }.get(column.column_type, "fixture-1")
                for column in table.columns
            ])


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = DemoProfile.load()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "deployment.json"

    def test_azure_and_fabric_can_merge_in_either_order(self) -> None:
        for updates in (
            [{"azure": {"searchName": "construction3iq-search-test"}}, {"workspaceId": WORKSPACE_ID, "items": {"lakehouseId": LAKEHOUSE_ID}}],
            [{"workspaceId": WORKSPACE_ID, "items": {"lakehouseId": LAKEHOUSE_ID}}, {"azure": {"searchName": "construction3iq-search-test"}}],
        ):
            self.path.unlink(missing_ok=True)
            for update in updates:
                merge_deployment(update, self.path, self.profile)
            merge_deployment({"agents": {"fabricIq": {"name": "specialist", "version": "1"}}}, self.path, self.profile)
            result = merge_deployment({"items": {"ontologyId": ONTOLOGY_ID}}, self.path, self.profile)
            self.assertEqual(result["azure"]["searchName"], "construction3iq-search-test")
            self.assertEqual(result["items"]["lakehouseId"], LAKEHOUSE_ID)
            self.assertEqual(result["workspaceId"], WORKSPACE_ID)
            self.assertEqual(result["agents"]["fabricIq"]["version"], "1")
            self.assertEqual(result["schemaVersion"], 1)
            self.assertEqual(list(self.path.parent.glob(".deployment-*.tmp")), [])
            self.assertFalse(self.path.with_suffix(".json.lock").exists())

    def test_partial_manifest_does_not_require_other_workstream(self) -> None:
        self.assertEqual(load_partial_deployment(self.path, self.profile), manifest_base(self.profile))
        merge_deployment({"workspaceId": WORKSPACE_ID}, self.path, self.profile)
        self.assertNotIn("azure", load_partial_deployment(self.path, self.profile))

    def test_cannot_overwrite_identity_or_owned_ids(self) -> None:
        merge_deployment({"workspaceId": WORKSPACE_ID, "items": {"ontologyId": ONTOLOGY_ID}}, self.path, self.profile)
        original = self.path.read_bytes()
        for update in ({"subscriptionId": WORKSPACE_ID}, {"workspaceId": GRAPH_ID}, {"items": {"ontologyId": GRAPH_ID}}):
            with self.assertRaises(FabricApiError):
                merge_deployment(update, self.path, self.profile)
            self.assertEqual(self.path.read_bytes(), original)

    def test_atomic_replace_failure_preserves_previous_manifest(self) -> None:
        merge_deployment({"workspaceId": WORKSPACE_ID}, self.path, self.profile)
        previous = self.path.read_bytes()
        with patch("construction_iq.fabric_api.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                merge_deployment({"items": {"lakehouseId": LAKEHOUSE_ID}}, self.path, self.profile)
        self.assertEqual(previous, self.path.read_bytes())
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_wrong_profile_fails_before_writing(self) -> None:
        self.path.write_text(json.dumps({**manifest_base(self.profile), "resourceGroup": "unowned-group"}))
        with self.assertRaisesRegex(FabricApiError, "resourceGroup"):
            merge_deployment({}, self.path, self.profile)

    def test_native_ontology_is_required_in_complete_fabric_manifest(self) -> None:
        with self.assertRaisesRegex(FabricApiError, "ontologyId"):
            require_fabric_items({"items": {"lakehouseId": LAKEHOUSE_ID, "eventhouseId": LAKEHOUSE_ID, "kqlDatabaseId": LAKEHOUSE_ID, "graphModelId": GRAPH_ID}})


class FabricClientTests(unittest.TestCase):
    def test_token_uses_subscription_and_verifies_tenant_without_conflicting_cli_options(self) -> None:
        profile = replace(DemoProfile.load(), subscription_id=LAKEHOUSE_ID, tenant_id=ONTOLOGY_ID, capacity_id=GRAPH_ID)
        result = Mock(returncode=0, stdout=json.dumps({"accessToken": "test", "tenant": profile.tenant_id, "subscription": profile.subscription_id}))
        with patch("construction_iq.fabric_api.shutil.which", return_value="az.cmd"), patch("construction_iq.fabric_api.subprocess.run", return_value=result) as run:
            self.assertEqual(get_az_token("https://api.fabric.microsoft.com", profile), "test")
        self.assertIn("--subscription", run.call_args.args[0])
        self.assertNotIn("--tenant", run.call_args.args[0])
        result.stdout = json.dumps({"accessToken": "test", "tenant": WORKSPACE_ID, "subscription": profile.subscription_id})
        with patch("construction_iq.fabric_api.shutil.which", return_value="az.cmd"), patch("construction_iq.fabric_api.subprocess.run", return_value=result):
            with self.assertRaisesRegex(FabricApiError, "token context"):
                get_az_token("https://api.fabric.microsoft.com", profile)

    def test_graph_query_failure_or_missing_rows_is_not_success(self) -> None:
        client = FabricRestClient("test")
        for response in ({"status": {"code": "42", "message": "unavailable"}}, {"status": {"code": "00000"}, "result": {"data": []}}):
            with patch.object(client, "request", return_value=response):
                with self.assertRaises(FabricApiError):
                    client.query_graph(WORKSPACE_ID, GRAPH_ID, "MATCH (d:DemandRecord) RETURN count(d)")

    def test_lro_missing_location_is_failure(self) -> None:
        with self.assertRaisesRegex(FabricApiError, "Location"):
            FabricRestClient("test")._poll_lro(HttpResponse(202, {}, "{}"), 1)

    def test_lro_failure_reports_service_details(self) -> None:
        client = FabricRestClient("test")
        with patch.object(client, "raw_request", return_value=HttpResponse(200, {}, '{"status":"Failed","error":{"message":"Preview unavailable"}}')):
            with patch("construction_iq.fabric_api.time.sleep"):
                with self.assertRaisesRegex(FabricApiError, "Preview unavailable"):
                    client._poll_lro(HttpResponse(202, {"location": OPERATION_URL}, "{}"), 1)

    def test_lro_succeeded_requires_result_and_cannot_silently_swallow_404(self) -> None:
        client = FabricRestClient("test")
        with patch.object(client, "raw_request", side_effect=[
            HttpResponse(200, {}, '{"status":"Succeeded"}'), FabricApiError("result missing", 404),
        ]), patch("construction_iq.fabric_api.time.sleep"):
            with self.assertRaisesRegex(FabricApiError, "result missing"):
                client._poll_lro(HttpResponse(202, {"location": OPERATION_URL}, "{}"), 5)

    def test_lro_timeout_is_bounded(self) -> None:
        client = FabricRestClient("test")
        with patch("construction_iq.fabric_api.time.monotonic", side_effect=[0, 2]):
            with self.assertRaisesRegex(FabricApiError, "Timed out"):
                client._poll_lro(HttpResponse(202, {"location": OPERATION_URL}, "{}"), 1)

    def test_pagination_cannot_loop_or_change_origin(self) -> None:
        client = FabricRestClient("test")
        with patch.object(client, "request", return_value={"value": [], "continuationUri": "/workspaces"}):
            with self.assertRaisesRegex(FabricApiError, "repeated"):
                client.list_all("/workspaces")
        for url in ("https://evil.example/v1/workspaces", "https://api.fabric.microsoft.com.evil.example/v1/workspaces"):
            with self.assertRaises(FabricApiError):
                client._url(url)

    def test_job_waits_for_exact_submitted_job_even_if_already_completed(self) -> None:
        client = FabricRestClient("test")
        with patch.object(client, "raw_request", return_value=HttpResponse(202, {"location": JOB_URL}, "")), patch.object(client, "request", return_value={"id": GRAPH_ID, "status": "Completed"}) as request:
            result = client.run_job(WORKSPACE_ID, LAKEHOUSE_ID, "RunNotebook", {})
        self.assertEqual(result["id"], GRAPH_ID)
        request.assert_called_once_with("GET", JOB_URL, follow_lro=False)

    def test_job_failure_cannot_be_success(self) -> None:
        client = FabricRestClient("test")
        with patch.object(client, "raw_request", return_value=HttpResponse(202, {"location": JOB_URL}, "")), patch.object(client, "request", return_value={"status": "Failed", "failureReason": "schema mismatch"}):
            with self.assertRaisesRegex(FabricApiError, "schema mismatch"):
                client.run_job(WORKSPACE_ID, LAKEHOUSE_ID, "RunNotebook", {})

    def test_unrelated_job_location_fails(self) -> None:
        client = FabricRestClient("test")
        with patch.object(client, "raw_request", return_value=HttpResponse(202, {"location": OPERATION_URL}, "")):
            with self.assertRaisesRegex(FabricApiError, "does not belong"):
                client.run_job(WORKSPACE_ID, LAKEHOUSE_ID, "RunNotebook", {})

    def test_onelake_path_and_kusto_host_guards(self) -> None:
        for remote_path in ("Tables/dbo/account", "Files/../Tables/data", "Files\\evil", "Files//data"):
            with self.assertRaises(FabricApiError):
                OneLakeClient._url(WORKSPACE_ID, LAKEHOUSE_ID, remote_path)
        for host in ("http://abc.kusto.fabric.microsoft.com", "https://evil.example", "https://abc.kusto.fabric.microsoft.com@evil.example"):
            with self.assertRaises(FabricApiError):
                KustoClient(host, "database", "test")

    def test_kusto_embedded_errors_are_not_success(self) -> None:
        client = KustoClient("https://demo.kusto.fabric.microsoft.com", "database", "test")
        with patch.object(client, "_send", return_value=HttpResponse(200, {}, '{"error":{"message":"ingest failed"}}')):
            with self.assertRaisesRegex(FabricApiError, "ingest failed"):
                client.execute_mgmt(".set-or-replace demo <| datatable(x:int)[1]")


class OwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.deploy = script("deploy_fabric")
        self.profile = DemoProfile.load()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "deployment.json"

    def test_existing_same_named_workspace_is_not_adopted(self) -> None:
        fabric = Mock()
        fabric.list_all.return_value = [{"id": WORKSPACE_ID, "displayName": self.profile.workspace_name.upper()}]
        with self.assertRaisesRegex(FabricApiError, "unowned"):
            self.deploy.ensure_workspace(fabric, self.profile, self.path)
        fabric.request.assert_not_called()

    def test_owned_workspace_must_still_match_name_and_capacity(self) -> None:
        merge_deployment({"workspaceId": WORKSPACE_ID}, self.path, self.profile)
        fabric = Mock()
        fabric.request.return_value = {"id": WORKSPACE_ID, "displayName": self.profile.workspace_name, "capacityId": GRAPH_ID}
        with self.assertRaisesRegex(FabricApiError, "capacity"):
            self.deploy.ensure_workspace(fabric, self.profile, self.path)
        self.assertEqual(fabric.request.call_args.args[0], "GET")

    def test_new_workspace_id_is_persisted_without_erasing_azure(self) -> None:
        merge_deployment({"azure": {"searchName": "construction3iq-search-fixture"}}, self.path, self.profile)
        fabric = Mock()
        fabric.list_all.return_value = []
        fabric.request.side_effect = [
            {"id": WORKSPACE_ID},
            {"id": WORKSPACE_ID, "displayName": self.profile.workspace_name, "capacityId": self.profile.capacity_id},
        ]
        self.deploy.ensure_workspace(fabric, self.profile, self.path)
        manifest = load_partial_deployment(self.path, self.profile)
        self.assertEqual(manifest["workspaceId"], WORKSPACE_ID)
        self.assertEqual(manifest["azure"]["searchName"], "construction3iq-search-fixture")

    def test_create_without_id_never_adopts_by_name(self) -> None:
        fabric = Mock()
        fabric.list_all.return_value = []
        fabric.request.return_value = {}
        with self.assertRaisesRegex(FabricApiError, "no ID"):
            self.deploy.ensure_workspace(fabric, self.profile, self.path)
        fabric.list_all.assert_called_once()
        self.assertFalse(self.path.exists())

    def test_unowned_same_named_item_is_not_updated(self) -> None:
        merge_deployment({"workspaceId": WORKSPACE_ID}, self.path, self.profile)
        fabric = Mock()
        fabric.list_all.return_value = [{"id": ONTOLOGY_ID, "displayName": FABRIC_ONTOLOGY_NAME}]
        with self.assertRaisesRegex(FabricApiError, "Unowned item"):
            self.deploy.ensure_item(fabric, self.profile, WORKSPACE_ID, "ontologyId", FABRIC_ONTOLOGY_NAME, "Ontology", definition={}, path=self.path)
        fabric.request.assert_not_called()

    def test_missing_ontology_graph_never_creates_standalone_graph(self) -> None:
        fabric = Mock()
        with self.assertRaisesRegex(FabricApiError, "No standalone"):
            self.deploy.discover_generated_graph(fabric, WORKSPACE_ID, ONTOLOGY_ID, timeout_seconds=0)
        fabric.request.assert_not_called()

    def test_automatic_graph_refresh_is_monitored_without_duplicate_submission(self) -> None:
        fabric = Mock()
        fabric.list_all.return_value = [{"id": ONTOLOGY_ID, "status": "InProgress"}]
        fabric.wait_job.return_value = {"id": ONTOLOGY_ID, "status": "Completed"}
        self.deploy.refresh_graph(fabric, WORKSPACE_ID, GRAPH_ID)
        fabric.run_job.assert_not_called()
        fabric.wait_job.assert_called_once_with(WORKSPACE_ID, GRAPH_ID, f"/workspaces/{WORKSPACE_ID}/items/{GRAPH_ID}/jobs/instances/{ONTOLOGY_ID}")

    def test_graph_refresh_submits_when_no_active_job(self) -> None:
        fabric = Mock()
        fabric.list_all.return_value = [{"id": ONTOLOGY_ID, "status": "Completed"}]
        self.deploy.refresh_graph(fabric, WORKSPACE_ID, GRAPH_ID)
        fabric.run_job.assert_called_once_with(WORKSPACE_ID, GRAPH_ID, "RefreshGraph", {})


class DefinitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_root = Path(self.temporary.name)
        write_csv_fixture(self.data_root)

    def test_direct_binding_prefers_target_entity_table_when_both_have_keys(self) -> None:
        _, _, bindings = source_model()
        by_edge = {(binding.source_label, binding.edge_label, binding.target_label): binding for binding in bindings}
        self.assertEqual(by_edge["UnifiedProfile", "linked_to_contact", "CustomerContact"].table_name, "customer_contacts")
        self.assertEqual(by_edge["DemandRecord", "for_commitment", "CustomerCommitment"].table_name, "customer_commitments")
        self.assertEqual(by_edge["SupplyConstraint", "exposes_commitment", "CustomerCommitment"].table_name, "business_risks")
        self.assertEqual(by_edge["UnifiedProfile", "member_of_audience", "Audience"].table_name, "audience_memberships")

    def test_unrelated_denormalized_table_is_never_inferred_as_a_junction(self) -> None:
        tables = (
            TableSpec("left_entities", "lakehouse", "test", (ColumnSpec("left_id"),)),
            TableSpec("right_entities", "lakehouse", "test", (ColumnSpec("right_id"),)),
            TableSpec("read_model", "lakehouse", "test", (ColumnSpec("record_id"), ColumnSpec("left_id"), ColumnSpec("right_id"))),
        )
        graph_path = self.data_root / "unsupported-relationship.json"
        graph_path.write_text(json.dumps({
            "nodeLabels": [{"label": "Left", "idProperty": "left_id"}, {"label": "Right", "idProperty": "right_id"}, {"label": "ReadModel", "idProperty": "record_id"}],
            "directedEdges": [["Left", "unsupported_link", "Right"]],
        }))
        with patch("construction_iq.fabric_artifacts.ALL_TABLES", tables), patch("construction_iq.fabric_artifacts.TABLE_BY_NAME", {table.name: table for table in tables}):
            with self.assertRaisesRegex(FabricApiError, "No direct entity table or explicit junction"):
                source_model(graph_path)

    def test_node_table_uses_first_id_column_not_leading_time_or_any_foreign_key(self) -> None:
        tables = (
            TableSpec("events", "eventhouse", "events", (ColumnSpec("event_time", "utc_timestamp"), ColumnSpec("description"), ColumnSpec("event_id"), ColumnSpec("owner_id"))),
            TableSpec("owners", "lakehouse", "test", (ColumnSpec("owner_id"),)),
        )
        graph_path = self.data_root / "primary-id.json"
        graph_path.write_text(json.dumps({
            "nodeLabels": [{"label": "Event", "idProperty": "event_id"}, {"label": "Owner", "idProperty": "owner_id"}],
            "directedEdges": [["Event", "for_owner", "Owner"]],
        }))
        with patch("construction_iq.fabric_artifacts.ALL_TABLES", tables), patch("construction_iq.fabric_artifacts.TABLE_BY_NAME", {table.name: table for table in tables}):
            entities, _, bindings = source_model(graph_path)
        self.assertEqual(entities["Event"].name, "events")
        self.assertEqual(entities["Owner"].name, "owners")
        self.assertEqual(bindings[0].table_name, "events")

    def test_all_tables_and_relationships_are_bound_to_only_new_lakehouse(self) -> None:
        entities, _, bindings = source_model()
        self.assertEqual(len(entities), len(ALL_TABLES))
        self.assertTrue(key_path_edges_present()["complete"])
        self.assertIn("DemandRecord", entities)
        definition = ontology_definition(WORKSPACE_ID, LAKEHOUSE_ID)
        decoded = {part["path"]: json.loads(base64.b64decode(part["payload"])) for part in definition["parts"]}
        entity_definitions = [value for path, value in decoded.items() if path.startswith("EntityTypes/") and path.endswith("/definition.json")]
        self.assertEqual(len(entity_definitions), len(ALL_TABLES))
        ids = [entity["id"] for entity in entity_definitions]
        ids += [prop["id"] for entity in entity_definitions for prop in entity["properties"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(0 < int(value) <= 2**53 - 1 for value in ids))
        static = [value["dataBindingConfiguration"] for path, value in decoded.items() if "/DataBindings/" in path]
        self.assertTrue(all(binding["dataBindingType"] == "NonTimeSeries" for binding in static))
        self.assertEqual({binding["sourceTableProperties"]["itemId"] for binding in static}, {LAKEHOUSE_ID})
        self.assertEqual({binding["sourceTableProperties"]["workspaceId"] for binding in static}, {WORKSPACE_ID})
        self.assertEqual(sum("/Contextualizations/" in path for path in decoded), len(bindings))
        self.assertFalse(any(column.name.endswith("_usd") for table in ALL_TABLES for column in table.columns))

    def test_native_contextualizations_bind_the_full_cdp_and_governance_paths(self) -> None:
        decoded = {
            part["path"]: json.loads(base64.b64decode(part["payload"]))
            for part in ontology_definition(WORKSPACE_ID, LAKEHOUSE_ID)["parts"]
        }
        entities = {
            value["name"]: value for path, value in decoded.items()
            if path.startswith("EntityTypes/") and path.endswith("/definition.json")
        }
        required = (
            ("UnifiedProfile", "member_of_audience", "Audience", "audience_memberships", "profile_id", "audience_id"),
            ("Audience", "activated_through", "Activation", "activations", "audience_id", "activation_id"),
            ("Activation", "supports_campaign", "Campaign", "activations", "activation_id", "campaign_id"),
            ("Campaign", "generates_demand_signal", "DemandSignal", "demand_signals", "campaign_id", "demand_signal_id"),
            ("DemandSignal", "requests_product", "Product", "demand_signals", "demand_signal_id", "product_id"),
            ("Product", "has_constraint", "SupplyConstraint", "supply_constraints", "product_id", "constraint_id"),
            ("SupplyConstraint", "exposes_commitment", "CustomerCommitment", "business_risks", "constraint_id", "commitment_id"),
            ("CustomerCommitment", "has_business_risk", "BusinessRisk", "business_risks", "commitment_id", "business_risk_id"),
            ("UnifiedProfile", "has_consent", "ConsentRecord", "consent_records", "profile_id", "consent_id"),
            ("Audience", "governed_by", "SuppressionRule", "suppression_rules", "audience_id", "suppression_rule_id"),
            ("Activation", "activates_audience", "Audience", "activations", "activation_id", "audience_id"),
            ("ActivationEvent", "event_for_profile", "UnifiedProfile", "activation_events", "activation_event_id", "profile_id"),
            ("ActivationEvent", "event_for_activation", "Activation", "activation_events", "activation_event_id", "activation_id"),
            ("ActivationEvent", "blocked_by", "SuppressionRule", "activation_events", "activation_event_id", "suppression_rule_id"),
        )
        for source, edge, target, table, source_key, target_key in required:
            with self.subTest(source=source, edge=edge, target=target):
                matches = [
                    value for path, value in decoded.items()
                    if path.startswith("RelationshipTypes/") and path.endswith("/definition.json")
                    and value["name"] == edge
                    and value["source"]["entityTypeId"] == entities[source]["id"]
                    and value["target"]["entityTypeId"] == entities[target]["id"]
                ]
                self.assertEqual(len(matches), 1)
                prefix = f"RelationshipTypes/{matches[0]['id']}/Contextualizations/"
                contexts = [value for path, value in decoded.items() if path.startswith(prefix)]
                self.assertEqual(len(contexts), 1)
                context = contexts[0]
                self.assertEqual(context["dataBindingTable"], {
                    "workspaceId": WORKSPACE_ID, "itemId": LAKEHOUSE_ID,
                    "sourceTableName": table, "sourceSchema": "dbo", "sourceType": "LakehouseTable",
                })
                self.assertEqual(context["sourceKeyRefBindings"], [{
                    "sourceColumnName": source_key, "targetPropertyId": entities[source]["entityIdParts"][0],
                }])
                self.assertEqual(context["targetKeyRefBindings"], [{
                    "sourceColumnName": target_key, "targetPropertyId": entities[target]["entityIdParts"][0],
                }])

    def test_event_entities_are_native_readable_static_lakehouse_mirrors(self) -> None:
        decoded = {
            part["path"]: json.loads(base64.b64decode(part["payload"]))
            for part in ontology_definition(WORKSPACE_ID, LAKEHOUSE_ID)["parts"]
        }
        entities, _, _ = source_model()
        for label, table in entities.items():
            if table.target != "eventhouse":
                continue
            entity = next(value for path, value in decoded.items() if path.startswith("EntityTypes/") and path.endswith("/definition.json") and value["name"] == label)
            prefix = f"EntityTypes/{entity['id']}/DataBindings/"
            bindings = [value["dataBindingConfiguration"] for path, value in decoded.items() if path.startswith(prefix)]
            self.assertEqual(len(bindings), 1)
            self.assertEqual(bindings[0]["dataBindingType"], "NonTimeSeries")
            self.assertEqual(bindings[0]["sourceTableProperties"], {
                "sourceType": "LakehouseTable", "workspaceId": WORKSPACE_ID,
                "itemId": LAKEHOUSE_ID, "sourceTableName": table.name, "sourceSchema": "dbo",
            })
            property_names = {prop["id"]: prop["name"] for prop in entity["properties"]}
            self.assertEqual(
                {(binding["sourceColumnName"], property_names[binding["targetPropertyId"]]) for binding in bindings[0]["propertyBindings"]},
                {(column.name, column.name) for column in table.columns},
            )

    def test_notebook_has_valid_python_and_strict_count_schema_digest_checks(self) -> None:
        contract = dataset_contract(self.data_root)
        definition = build_ingest_notebook_definition(WORKSPACE_ID, LAKEHOUSE_ID, contract)
        notebook = json.loads(base64.b64decode(definition["parts"][0]["payload"]))
        source = "".join(notebook["cells"][0]["source"])
        compile(source, "<ingest-notebook>", "exec")
        self.assertNotIn("dropDuplicates", source)
        self.assertIn('persisted.schema != typed.schema', source)
        self.assertIn('spec["count"]', source)
        self.assertIn("hashlib.sha256(content)", source)
        self.assertIn('schemaValidated', source)
        self.assertEqual(len(contract["tables"]), len(ALL_TABLES))
        self.assertTrue(all(table["count"] == 1 for table in contract["tables"]))

    def test_csv_wrong_schema_and_duplicate_keys_fail_before_deployment(self) -> None:
        table = ALL_TABLES[0]
        path = self.data_root / table.folder / f"{table.name}.csv"
        original = path.read_text()
        path.write_text(original + original.splitlines()[1] + "\n")
        with self.assertRaisesRegex(FabricApiError, "duplicate"):
            dataset_contract(self.data_root)
        path.write_text("wrong_header\nvalue\n")
        with self.assertRaisesRegex(FabricApiError, "header"):
            dataset_contract(self.data_root)

    def test_eventhouse_reruns_replace_data_without_drop_or_append_duplicates(self) -> None:
        for table in EVENTHOUSE_TABLES:
            command = eventhouse_replace_command(table, self.data_root)
            self.assertTrue(command.startswith(f".set-or-replace {table.name} <| datatable("))
            self.assertNotIn(".drop", command)
            self.assertNotIn(".ingest", command)
            for column in table.columns:
                self.assertIn(column.name + ":", command)

    def test_preflight_contains_no_cloud_mutation_commands(self) -> None:
        source = (ROOT / "scripts" / "preflight.ps1").read_text()
        for forbidden in ("deployment sub create", "group create", "role assignment create", "provider register", "-Method Post", "assignToCapacity", "what-if", "az bicep install"):
            self.assertNotIn(forbidden, source)
        self.assertIn("az bicep build", source)
        self.assertIn("Refusing adoption", source)

    def test_bicep_has_exact_approved_models_tiers_and_keyless_policy(self) -> None:
        main = (ROOT / "infra" / "main.bicep").read_text()
        resources = (ROOT / "infra" / "resources.bicep").read_text()
        self.assertIn("targetScope = 'subscription'", main)
        self.assertEqual(main.count("resource demoGroup "), 1)
        for required in ("'2026-03-05'", "capacity: 50", "capacity: 10", "'GlobalStandard'", "'text-embedding-3-large'", "replicaCount: 1", "partitionCount: 1", "allowSharedKeyAccess: false", "allowBlobPublicAccess: false"):
            self.assertIn(required, resources)
        self.assertEqual(resources.count("disableLocalAuth: true"), 2)
        self.assertNotIn("Microsoft.KeyVault", resources)
        self.assertNotIn("Microsoft.Web", resources)
        self.assertIn("name: 'policies'", resources)
        self.assertIn("properties: { publicAccess: 'None' }", resources)
        self.assertIn("policyContainer: policies.name", resources)
        deploy = (ROOT / "scripts" / "deploy_azure.ps1").read_text()
        self.assertIn("'policyContainer'", deploy)


class NativeTraversalSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.smoke = script("smoke_fabric")
        self.chain = [{
            name: "fixture-" + name for name in (
                "profileId", "audienceId", "activationId", "campaignId", "demandSignalId",
                "productId", "constraintId", "commitmentId", "businessRiskId",
            )
        }]

    def test_live_smoke_requires_complete_chain_and_every_suppression_event(self) -> None:
        fabric = Mock()
        fabric.query_graph.side_effect = [self.chain, [{"activationEventId": "event-1"}, {"activationEventId": "event-2"}]]
        result = self.smoke.validate_native_traversals(fabric, WORKSPACE_ID, GRAPH_ID, {"event-1", "event-2"})
        self.assertEqual(result["cdpToSupply"], self.chain)
        self.assertEqual(result["suppressionEventIds"], ["event-1", "event-2"])
        queries = [call.args[2].replace("`", "") for call in fabric.query_graph.call_args_list]
        self.assertIn("[:requests_product]", queries[0])
        for edge in ("[:event_for_profile]", "[:event_for_activation]", "[:blocked_by]", "[:governed_by]", "[:has_consent]"):
            self.assertIn(edge, queries[1])

    def test_missing_or_extra_suppression_event_fails_even_when_counts_match(self) -> None:
        fabric = Mock()
        fabric.query_graph.side_effect = [self.chain, [{"activationEventId": "wrong-event"}]]
        with self.assertRaisesRegex(FabricApiError, "Missing=.*event-1"):
            self.smoke.validate_native_traversals(fabric, WORKSPACE_ID, GRAPH_ID, {"event-1"})

    def test_counts_alone_do_not_satisfy_live_traversal(self) -> None:
        fabric = Mock()
        fabric.query_graph.return_value = [{"rowCount": 200}]
        with self.assertRaisesRegex(FabricApiError, "complete linked evidence"):
            self.smoke.validate_native_traversals(fabric, WORKSPACE_ID, GRAPH_ID, {"event-1"})


if __name__ == "__main__":
    unittest.main()
