from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from construction_iq.config import ConfigurationError, DemoProfile, ROOT, load_deployment
from construction_iq.orchestrator import action_package, collect_lanes, run
from construction_iq.queue import load_queue, select_context, validate_records
from construction_iq.specialists import INSTRUCTIONS, LANES


def records() -> list[dict]:
    result = []
    for index, (ordered, allocated) in enumerate(((800, 800), (600, 400), (400, 0)), 1):
        result.append({
            "recordId": f"REC-{index}", "commitmentId": f"C-{index}", "businessRiskId": f"R-{index}",
            "accountId": f"A-{index}", "accountName": f"Fictional Contractor {index}",
            "projectName": ("School", "Apartments", "Office")[index - 1],
            "productId": "INS-1", "productName": "Insulation", "productFamilyId": "INS",
            "unit": "m2", "currency": "EUR", "orderedQty": ordered, "availableQty": 1200,
            "allocatedQty": allocated, "shortageQty": ordered - allocated, "unitPrice": 20,
            "orderValue": ordered * 20, "unfilledValue": (ordered - allocated) * 20,
            "priority": index, "committedDate": "2026-10-10", "constraintId": "STOCK-1",
            "clusterId": "POOL-1", "approvalRequired": True, "anchor": True,
        })
    return result


def context() -> dict:
    return select_context({"records": records(), "source": "test"}, "REC-1")


def test_golden_arithmetic_is_not_risk_score_heuristic():
    validated = validate_records(records())
    facts = select_context({"records": validated, "source": "test"}, "REC-1")
    assert facts["totals"] == {
        "orderedQty": 1800, "availableQty": 1200, "allocatedQty": 1200,
        "shortageQty": 600, "orderValue": 36000, "unfilledValue": 12000,
        "unit": "m2", "currency": "EUR",
    }
    package = action_package(facts, "What should we do?")
    assert [item["quantity"] for item in package["proposedAllocations"]] == [800, 400, 0]
    assert package["approvalRequired"] is True
    assert "not sent" in package["customerDraft"]
    assert "1200" not in package["customerDraft"]


@pytest.mark.parametrize("mutation", ["negative", "nan", "infinity", "incorrect_value", "duplicate", "duplicate_commitment"])
def test_invalid_numeric_or_duplicate_records_fail(mutation):
    value = records()
    if mutation == "negative":
        value[0]["allocatedQty"] = -1
    elif mutation == "nan":
        value[0]["unitPrice"] = float("nan")
    elif mutation == "infinity":
        value[0]["unitPrice"] = float("inf")
    elif mutation == "incorrect_value":
        value[1]["unfilledValue"] = 1
    elif mutation == "duplicate":
        value.append(deepcopy(value[0]))
    else:
        value[1]["commitmentId"] = value[0]["commitmentId"]
    with pytest.raises(ValueError):
        validate_records(value)


def test_shared_stock_is_counted_once_and_not_exceeded():
    value = records()
    value[2]["allocatedQty"] = 1
    with pytest.raises(ValueError, match="exceeds"):
        select_context({"records": value, "source": "test"}, "REC-1")


def test_different_currency_or_stock_pools_are_not_summed():
    value = records()
    value[1]["currency"] = "USD"
    with pytest.raises(ValueError, match="one product"):
        select_context({"records": value, "source": "test"}, "REC-1")


def test_no_implicit_offline_fallback():
    with patch("construction_iq.queue.load_deployment", side_effect=ConfigurationError("not deployed")):
        with pytest.raises(ConfigurationError, match="not deployed"):
            load_queue("live")
    with pytest.raises(ValueError, match="mode"):
        load_queue("anything")


def test_live_queue_projects_shared_schema_without_reading_local_fixtures():
    manifest = {
        "workspaceId": "new-workspace",
        "items": {"graphModelId": "new-graph"},
    }
    payload = {"status": {"code": "00000"}, "result": {"data": records()}}
    with patch("construction_iq.queue.load_deployment", return_value=manifest), \
         patch("construction_iq.queue.CloudClient") as client_type, \
         patch.object(Path, "read_text", side_effect=AssertionError("A live queue must not read local data")):
        client_type.return_value.request.return_value = payload
        queue = load_queue("live")
    assert queue["source"] == "fabric_graphmodel"
    assert queue["workspaceId"] == "new-workspace"
    assert "d.`qualification_status` AS `qualificationStatus`" in queue["query"]
    assert "d.`inbound_date` AS `inboundDate`" in queue["query"]
    assert "/workspaces/new-workspace/graphModels/new-graph/" in client_type.return_value.request.call_args.args[1]


def test_missing_manifest_fails(tmp_path):
    with pytest.raises(ConfigurationError, match="does not exist"):
        load_deployment(tmp_path / "missing.json")


@pytest.mark.parametrize("suffix", ["services.ai.azure.com", "cognitiveservices.azure.com", "openai.azure.com"])
def test_known_foundry_endpoint_variants_are_bound_to_the_recorded_account(tmp_path, suffix):
    profile = DemoProfile.load()
    value = {
        "subscriptionId": profile.subscription_id, "tenantId": profile.tenant_id,
        "resourceGroup": profile.resource_group, "capacityId": profile.capacity_id,
        "workspaceName": profile.workspace_name,
        "workspaceId": "7e5adce4-0738-486b-994e-8f7726c99b19",
        "items": {key: "7e5adce4-0738-486b-994e-8f7726c99b19" for key in ("lakehouseId", "ontologyId", "graphModelId")},
        "azure": {
            "foundryAccountName": "construction-test", "searchName": "construction-search",
            "foundryEndpoint": f"https://construction-test.{suffix}",
            "projectEndpoint": "https://construction-test.services.ai.azure.com/api/projects/demo",
            "searchEndpoint": "https://construction-search.search.windows.net",
        },
    }
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    assert load_deployment(path, require_iq=False)["azure"]["foundryEndpoint"] == value["azure"]["foundryEndpoint"]
    value["azure"]["foundryEndpoint"] = f"https://different-account.{suffix}"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="foundryEndpoint"):
        load_deployment(path, require_iq=False)


def test_profile_brand_is_configurable_without_source_edits(tmp_path):
    data = json.loads((ROOT / "config" / "demo-profile.json").read_text(encoding="utf-8"))
    data["supplierName"] = "Another Fictional Supplier"
    target = tmp_path / "profile.json"
    target.write_text(json.dumps(data), encoding="utf-8")
    assert DemoProfile.load(target).supplier_name == data["supplierName"]


def test_remote_failure_is_explicit_and_never_offline():
    message = {"mode": "live", "context": context(), "question": "Protect stock"}
    with patch("construction_iq.orchestrator.load_deployment", return_value={}), \
         patch("construction_iq.orchestrator.run_specialist", side_effect=RuntimeError("permission denied")):
        lanes = collect_lanes(message)
    assert len(lanes) == 3
    assert all(lane["status"] == "failed" and lane["sourceMode"] == "live" for lane in lanes)
    assert all("permission denied" in lane["summary"] for lane in lanes)


def test_framework_workflow_with_three_lanes_and_no_model_calls():
    queue = {"records": records(), "source": "offline_synthetic_fixture"}
    lanes = [{"lane": lane, "status": "completed", "toolCalls": []} for lane in LANES]
    with patch("construction_iq.orchestrator.load_queue", return_value=queue), \
         patch("construction_iq.orchestrator.collect_lanes", return_value=lanes):
        result = run({"mode": "offline", "recordId": "REC-1", "question": "What is at risk?"})
    assert result["status"] == "completed"
    assert len(result["evidenceLanes"]) == 3
    assert result["toolCalls"] == []
    assert result["actionPackage"]["approvalRequired"]
    assert result["agentFramework"]["executors"] == ["prepare", "gather", "shape"]


def test_partial_workflow_withholds_recommendation():
    queue = {"records": records(), "source": "fabric_graphmodel"}
    lanes = [{"lane": lane, "status": "failed", "toolCalls": []} for lane in LANES]
    with patch("construction_iq.orchestrator.load_queue", return_value=queue), \
         patch("construction_iq.orchestrator.collect_lanes", return_value=lanes):
        result = run({"mode": "live", "recordId": "REC-1", "question": "What is at risk?"})
    assert result["status"] == "partial"
    assert result["actionPackage"] is None


def test_only_three_instructions_and_work_simulation_disclosure():
    assert set(INSTRUCTIONS) == {"fabricIq", "foundryIq", "workIq"}
    assert "not a live Microsoft 365" in INSTRUCTIONS["workIq"]
    assert all("Always call retrieve_evidence" in prompt for prompt in INSTRUCTIONS.values())


def test_local_api_contract_requires_completed_job_for_chat():
    spec = importlib.util.spec_from_file_location("demo_server_test", ROOT / "apps" / "construction-command-center" / "server.py")
    assert spec is not None and spec.loader is not None
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    with pytest.raises(ValueError, match="question"):
        server.start_job({"recordId": "REC-1", "question": ""})
    with pytest.raises(ValueError, match="Unsupported"):
        server.start_job({"recordId": "REC-1", "question": "Hi", "projectEndpoint": "https://invalid.example"})
    with pytest.raises(KeyError):
        server.followup({"jobId": "absent", "question": "Draft an email"})
