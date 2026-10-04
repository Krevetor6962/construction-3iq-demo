from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest

from construction_iq.config import ROOT
from construction_iq.orchestrator import run

SPEC = importlib.util.spec_from_file_location("construction_benchmark_runner", ROOT / "scripts" / "run_benchmark.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.fixture(scope="module")
def cases():
    return runner.load_cases()


@pytest.fixture(scope="module")
def actual_result(cases):
    case = cases[0]
    return run({"mode": "offline", "recordId": case["recordId"], "question": case["question"]})


def live_shaped_result(actual_result):
    """A unit-test response shape, never a live cloud invocation."""
    result = deepcopy(actual_result)
    result["mode"] = "live"
    result["fabricEvidenceMode"] = "native_knowledge_base"
    result["context"]["queueSource"] = "fabric_graphmodel"
    result["actionPackage"]["groundedAnswer"] = "Synthetic unit-test answer requiring human review."
    calls = []
    for lane in result["evidenceLanes"]:
        lane["sourceMode"] = "live"
        lane["synthetic"] = True
        trace = {
            "lane": lane["lane"], "tool": "retrieve_evidence", "status": "completed",
            "source": "synthetic-unit-test-source", "transport": "client_function_to_search_rest",
            "delegatedUserContext": lane["lane"] == "fabricIq",
            "syntheticCollaboration": lane["lane"] == "workIq",
            "nativeOntologyKnowledgeBaseUsed": lane["lane"] == "fabricIq",
        }
        lane["toolCalls"] = [trace]
        calls.append(trace)
    result["toolCalls"] = calls
    return result


def test_file_knowledge_source_citations_resolve_actual_returned_document_names():
    case = {"policyIds": ["allocation", "delivery"], "requiredTerms": ["human approval"]}
    result = {"evidenceLanes": [{"lane": "foundryIq", "evidence": [{
        "references": [
            {"type": "file", "id": "0", "docName": "allocation.md", "sourceData": {"snippet": "Human approval is required."}},
            {"type": "file", "id": "1", "sourceData": {"metadata_storage_path": "delivery.md"}},
        ],
    }]}]}
    observation = runner.evidence_availability(case, result)
    assert observation["allRequestedEvidenceObserved"]
    result["evidenceLanes"][0]["evidence"][0]["references"][0]["docName"] = "unrelated.md"
    assert not runner.evidence_availability(case, result)["allRequestedEvidenceObserved"]

def test_explicit_ontology_graph_mode_requires_graph_evidence_without_a_native_kb_claim(actual_result):
    result = live_shaped_result(actual_result)
    result["fabricEvidenceMode"] = "ontology_graph"
    lane = next(item for item in result["evidenceLanes"] if item["lane"] == "fabricIq")
    call = lane["toolCalls"][0]
    call["transport"] = "client_function_to_fabric_rest"
    call["nativeOntologyKnowledgeBaseUsed"] = False
    lane["evidence"] = [{
        "sourceType": "fabric_ontology_graph", "ontologyId": "unit-ontology", "graphModelId": "unit-graph",
        "gql": "MATCH (d:`DemandRecord`) RETURN d", "nativeKnowledgeBaseUsed": False,
        "references": [{"id": "unit-record", "sourceData": {"orderedQty": 800}}],
    }]
    checks = runner.provenance_checks(result, "live")
    assert all(check["passed"] for check in checks)
    call["nativeOntologyKnowledgeBaseUsed"] = True
    checks = runner.provenance_checks(result, "live")
    assert any(not check["passed"] for check in checks)

def test_all_25_cases_run_through_real_offline_orchestrator(tmp_path):
    output = tmp_path / "benchmark-offline.json"
    report = runner.run_benchmark("offline", output_path=output)
    assert report["caseCount"] == 25
    assert report["summary"]["passed"] == 25
    assert report["summary"]["failed"] == report["summary"]["errors"] == 0
    assert report["summary"]["checksPassed"] is True


def test_resume_revalidates_persisted_results_without_repeating_successful_runs(tmp_path):
    output = tmp_path / "benchmark-offline.json"
    runner.run_benchmark("offline", output_path=output)
    from unittest.mock import patch
    with patch.object(runner.orchestrator, "run", side_effect=AssertionError("A completed run must be reused")):
        report = runner.run_benchmark("offline", output_path=output, resume=True)
    assert report["summary"]["passed"] == 25
    assert all(case["execution"] == "revalidated_persisted_response_no_new_cloud_call" for case in report["cases"])
    assert report["summary"]["casesWithEvidenceGaps"] == 0
    assert report["cloudChecksAttempted"] is False
    assert report["validationScope"] == "deterministic_offline_fixture_workflow"
    assert report["summary"]["generatedAnswerReviewRequired"] is False
    assert report["completedAt"] is not None
    assert json.loads(output.read_text(encoding="utf-8")) == report
    for case in report["cases"]:
        assert case["result"]["agentFramework"]["executors"] == ["prepare", "gather", "shape"]
        assert case["result"]["context"]["queueSource"] == "offline_synthetic_fixture"
        assert case["result"]["question"] == case["question"]
        assert case["generatedAnswer"]["text"] is None
        assert case["generatedAnswer"]["semanticAssessment"] == "not_performed"
        assert case["generatedAnswer"]["reviewRequired"] is False
        assert case["governanceAndProvenanceChecks"]
        assert all(check["passed"] for check in case["governanceAndProvenanceChecks"])
    assert "semanticScore" not in json.dumps(report)


def test_fact_resolution_reads_only_result_context(actual_result, monkeypatch):
    context = deepcopy(actual_result["context"])

    def forbidden_read(*args, **kwargs):
        raise AssertionError("Fact evaluation must not read any local file")

    monkeypatch.setattr(Path, "read_text", forbidden_read)
    assert runner.resolve_fact("campaign.demand_qty", context) == 300
    assert runner.resolve_fact("campaign.confirmed", context) is False
    assert runner.resolve_fact("campaign.allocation_eligible", context) is False
    assert runner.resolve_fact("consent.consent_status", context) == "granted"
    assert runner.resolve_fact("pool.availableQty", context) == 1200
    assert runner.resolve_fact("pool.customerCount", context) == 3
    assert runner.resolve_fact("pool.impactedCustomerCount", context) == 2
    assert runner.resolve_fact("pool.unfilledValue", context) == 12000
    for row in context["siblings"]:
        for field in ("asOfDate", "committedDate", "milestoneDate"):
            row[field] = (date.fromisoformat(row[field]) + timedelta(days=45)).isoformat()
    context["selected"] = context["siblings"][0]
    assert runner.resolve_fact("committedDateOffsetDays", context) == 3
    assert runner.resolve_fact("milestoneDateOffsetDays", context) == 4
    context["selected"]["campaignDemandQty"] = 317
    assert runner.resolve_fact("campaign.demand_qty", context) == 317
    context["selected"]["consentStatus"] = "denied"
    assert runner.resolve_fact("consent.consent_status", context) == "denied"


def test_pool_and_date_facts_use_returned_inbound_records(cases):
    case = next(item for item in cases if item["id"] == "inbound-conservation")
    result = run({"mode": "offline", "recordId": case["recordId"], "question": case["question"]})
    context = result["context"]
    assert runner.resolve_fact("pool.inboundQty", context) == 35
    assert runner.resolve_fact("pool.plannedInboundQty", context) == 35
    assert runner.resolve_fact("inboundDateOffsetDays", context) == 10
    context["siblings"][0]["inboundQty"] = 99
    with pytest.raises(ValueError, match="Inconsistent"):
        runner.resolve_fact("pool.inboundQty", context)


@pytest.mark.parametrize("mutation", [
    "totals", "duplicate_commitment", "mixed_cluster", "missing_property",
    "approved", "proposal", "question", "invented_campaign", "inbound_shortage", "substitution",
])
def test_returned_context_or_governance_regressions_fail(cases, actual_result, mutation):
    result = deepcopy(actual_result)
    context = result["context"]
    if mutation == "totals":
        context["totals"]["shortageQty"] += 1
    elif mutation == "duplicate_commitment":
        context["siblings"].append(deepcopy(context["siblings"][0]))
    elif mutation == "mixed_cluster":
        context["siblings"][1]["clusterId"] = "DIFFERENT-POOL"
    elif mutation == "missing_property":
        del context["siblings"][0]["campaignDemandQty"]
    elif mutation == "approved":
        result["actionPackage"]["approvalRequired"] = False
    elif mutation == "proposal":
        result["actionPackage"]["proposedAllocations"][0]["quantity"] += 1
    elif mutation == "invented_campaign":
        context["siblings"][0]["demandSignalId"] = None
    elif mutation == "inbound_shortage":
        context["siblings"][1]["afterInboundShortageQty"] = 0
    elif mutation == "substitution":
        context["siblings"][0]["substitutionAllowed"] = True
        context["siblings"][0]["qualificationStatus"] = "approved_equivalent"
    else:
        result["question"] = "Different question"
    evaluated = runner.evaluate_result(cases[0], result, "offline")
    assert evaluated["checksPassed"] is False
    assert any(not check["passed"] for check in evaluated["governanceAndProvenanceChecks"])


def test_missing_campaign_or_snapshot_is_not_filled_from_files(actual_result):
    context = deepcopy(actual_result["context"])
    del context["selected"]["campaignDemandQty"]
    with pytest.raises(KeyError):
        runner.resolve_fact("campaign.demand_qty", context)
    del context["selected"]["asOfDate"]
    with pytest.raises(KeyError):
        runner.resolve_fact("committedDateOffsetDays", context)
    context["selected"]["campaignConfirmed"] = None
    assert runner.resolve_fact("campaign.confirmed", context) is None
    assert runner._same(None, False) is False
    assert runner._same(0, False) is False


def test_offline_result_cannot_pass_as_live_cloud_validation(cases, actual_result):
    evaluated = runner.evaluate_result(cases[0], actual_result, "live")
    assert evaluated["checksPassed"] is False
    failed = {check["name"] for check in evaluated["governanceAndProvenanceChecks"] if not check["passed"]}
    assert "requestedModePreserved" in failed
    assert "queueSourceMatchesMode" in failed
    assert "fabricIq.liveRetrievalTrace" in failed
    assert evaluated["generatedAnswer"]["reviewRequired"] is True


def test_live_answer_is_retained_for_review_without_a_semantic_score(cases, actual_result):
    result = live_shaped_result(actual_result)
    case = deepcopy(cases[0])
    case["requiredTerms"] = ["already net of other reservations"]
    evaluated = runner.evaluate_result(case, result, "live")
    assert evaluated["checksPassed"] is True
    assert evaluated["generatedAnswer"]["text"] == result["actionPackage"]["groundedAnswer"]
    assert evaluated["generatedAnswer"]["reviewRequired"] is True
    assert evaluated["generatedAnswer"]["reviewStatus"] == "pending_human_review"
    assert evaluated["generatedAnswer"]["semanticAssessment"] == "not_performed"
    assert evaluated["evidenceAvailability"]["requiredTerms"][0]["observed"] is True
    assert case["requiredTerms"][0] not in result["actionPackage"]["groundedAnswer"]
    assert "semanticScore" not in json.dumps(evaluated)


@pytest.mark.parametrize("mutation", ["delegation", "failed_lane", "empty_evidence", "work_not_synthetic", "live365", "unexpected_tool"])
def test_live_retrieval_provenance_failures_are_explicit(cases, actual_result, mutation):
    result = live_shaped_result(actual_result)
    lanes = {lane["lane"]: lane for lane in result["evidenceLanes"]}
    if mutation == "delegation":
        lanes["fabricIq"]["toolCalls"][0]["delegatedUserContext"] = False
    elif mutation == "failed_lane":
        lanes["foundryIq"]["status"] = "failed"
    elif mutation == "empty_evidence":
        lanes["fabricIq"]["evidence"] = [{}]
    elif mutation == "work_not_synthetic":
        lanes["workIq"]["synthetic"] = False
    elif mutation == "live365":
        lanes["workIq"]["isLiveMicrosoft365"] = True
    else:
        lanes["workIq"]["toolCalls"][0]["tool"] = "send_message"
    evaluated = runner.evaluate_result(cases[0], result, "live")
    assert evaluated["checksPassed"] is False
    assert any(not check["passed"] for check in evaluated["governanceAndProvenanceChecks"])


def test_evidence_availability_does_not_use_model_claims_or_local_policies(cases, actual_result, monkeypatch):
    result = deepcopy(actual_result)
    lane = next(item for item in result["evidenceLanes"] if item["lane"] == "foundryIq")
    lane["evidence"] = []
    lane["summary"] = "I used allocation.md and all required terms."
    result["actionPackage"]["groundedAnswer"] = "allocation: already net of other reservations"
    case = deepcopy(cases[0])
    case["requiredTerms"] = ["already net of other reservations"]
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: pytest.fail("No local policy fallback permitted"))
    observed = runner.evidence_availability(case, result)
    assert observed["policyIds"] == [{"id": "allocation", "observed": False}]
    assert observed["requiredTerms"] == [{"term": "already net of other reservations", "observed": False}]
    assert observed["allRequestedEvidenceObserved"] is False


def test_orchestrator_errors_are_persisted_and_never_fallback(cases, tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "cases.json"
    fixture.write_text(json.dumps(cases[:2]), encoding="utf-8")
    output = tmp_path / "benchmark-live.json"
    requests = []

    def fail(request):
        requests.append(request)
        raise RuntimeError("Synthetic test: delegated retrieval unavailable")

    original_read = Path.read_text

    def guarded_read(path, *args, **kwargs):
        assert path == fixture, "Runner must not read local context/CSV/policies as a live fallback"
        return original_read(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(runner.orchestrator, "run", fail)
        scoped.setattr(Path, "read_text", guarded_read)
        report = runner.run_benchmark("live", cases_path=fixture, output_path=output)
    assert len(requests) == 2
    assert all(request["mode"] == "live" for request in requests)
    assert [request["question"] for request in requests] == [case["question"] for case in cases[:2]]
    assert report["summary"]["errors"] == 2
    assert report["summary"]["checksPassed"] is False
    assert all(case["status"] == "error" for case in report["cases"])
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert "delegated retrieval unavailable" in capsys.readouterr().err


def test_fixture_loader_requires_list_and_unique_case_ids(cases, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a list"):
        runner.load_cases(path)
    path.write_text(json.dumps([cases[0], cases[0]]), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        runner.load_cases(path)


def test_cli_requires_explicit_mode(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_benchmark.py"])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2
