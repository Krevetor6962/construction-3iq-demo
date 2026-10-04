from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from azure.core.exceptions import AzureError
from openai import OpenAIError

from construction_iq import orchestrator
from construction_iq.config import ROOT
from construction_iq.queue import validate_records
from construction_iq.schema_contract import SCENARIO_RECORD_COLUMNS

CASES_PATH = ROOT / "tests" / "scenarios" / "benchmark.json"
RESULTS_ROOT = ROOT / "tests" / "results"
LANES = {"fabricIq", "foundryIq", "workIq"}
FACT_ALIASES = {
    "campaign.demand_qty": "campaignDemandQty",
    "campaign.confirmed": "campaignConfirmed",
    "campaign.allocation_eligible": "campaignAllocationEligible",
    "consent.consent_status": "consentStatus",
}
VALIDATION_ERRORS = (ValueError, KeyError, TypeError, IndexError)
RUN_ERRORS = (RuntimeError, ValueError, OSError, KeyError, TypeError, ExceptionGroup, AzureError, OpenAIError)


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _array(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return value


def _strings(value: Any, name: str, *, nonempty: bool = False) -> list[str]:
    items = _array(value, name)
    if any(not isinstance(item, str) or not item.strip() for item in items) or (nonempty and not items):
        raise ValueError(f"{name} must contain nonempty strings")
    return items


def _number(value: Any, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return value


def _date(value: Any) -> date:
    if not isinstance(value, str):
        raise ValueError("A date fact must be an ISO date string")
    return date.fromisoformat(value[:10])


def _same(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool) or expected is None:
        return actual is expected
    if isinstance(expected, (int, float)):
        return (
            not isinstance(actual, bool) and isinstance(actual, (int, float))
            and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9)
        )
    return type(actual) is type(expected) and actual == expected


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases = _array(json.loads(path.read_text(encoding="utf-8")), "Benchmark")
    if not cases:
        raise ValueError("Benchmark must not be empty")
    seen: set[str] = set()
    for item in cases:
        case = _object(item, "Benchmark case")
        for key in ("id", "recordId", "question"):
            if not isinstance(case.get(key), str) or not case[key].strip():
                raise ValueError(f"Case requires a nonempty {key}")
        if case["id"] in seen:
            raise ValueError(f"Duplicate benchmark case ID: {case['id']}")
        seen.add(case["id"])
        _strings(case["expectedIntents"], "expectedIntents", nonempty=True)
        _strings(case["policyIds"], "policyIds", nonempty=True)
        facts = _object(case.get("expectedFacts", {}), "expectedFacts")
        terms = _strings(case.get("requiredTerms", []), "requiredTerms")
        if not facts and not terms:
            raise ValueError(f"Case {case['id']} has no fact or evidence expectations")
        for key, value in facts.items():
            if not isinstance(key, str) or not key:
                raise ValueError("Expected fact names must be nonempty strings")
            if value is not None and not isinstance(value, (str, bool, int, float)):
                raise ValueError(f"Expected fact {key} must be a JSON scalar")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Expected fact {key} must be finite")
    return cases


def _shared(siblings: list[dict[str, Any]], key: str) -> Any:
    values = {row[key] for row in siblings}
    if len(values) != 1:
        raise ValueError(f"Inconsistent shared pool field: {key}")
    return next(iter(values))


def resolve_fact(key: str, context: dict[str, Any]) -> Any:
    selected = _object(context["selected"], "context.selected")
    siblings = _array(context["siblings"], "context.siblings")
    if key in FACT_ALIASES:
        return selected[FACT_ALIASES[key]]
    if key.endswith("OffsetDays"):
        return (_date(selected[key.removesuffix("OffsetDays")]) - _date(selected["asOfDate"])).days
    if key.startswith("pool."):
        field = key.removeprefix("pool.")
        totals = _object(context["totals"], "context.totals")
        if field in totals:
            return totals[field]
        if field == "customerCount":
            return len({row["accountId"] for row in siblings})
        if field == "impactedCustomerCount":
            return len({row["accountId"] for row in siblings if _number(row["shortageQty"], "shortageQty") > 0})
        if field in ("inboundQty", "inboundDate"):
            return _shared(siblings, field)
        if field in ("plannedInboundQty", "afterInboundShortageQty"):
            return sum(_number(row[field], field) for row in siblings)
        raise ValueError(f"Unsupported pool fact: {field}")
    return selected[key]


def validate_context(context: dict[str, Any], record_id: str) -> None:
    selected = _object(context["selected"], "context.selected")
    siblings = validate_records(context["siblings"])
    totals = _object(context["totals"], "context.totals")
    if selected["recordId"] != record_id:
        raise ValueError("Returned record does not match the benchmark request")
    if selected not in siblings:
        raise ValueError("Selected record is not an identical member of context.siblings")
    for row in siblings:
        missing = set(SCENARIO_RECORD_COLUMNS) - set(row)
        if missing:
            raise ValueError(f"Returned DemandRecord is missing mapped properties: {sorted(missing)}")
    for key in ("clusterId", "productId", "unit", "currency", "availableQty", "asOfDate", "inboundQty", "inboundDate"):
        _shared(siblings, key)
    expected = {
        key: sum(_number(row[key], key) for row in siblings)
        for key in ("orderedQty", "allocatedQty", "shortageQty", "orderValue", "unfilledValue")
    }
    expected.update({key: selected[key] for key in ("availableQty", "unit", "currency")})
    for key, value in expected.items():
        if not _same(totals[key], value):
            raise ValueError(f"context.totals.{key} disagrees with returned sibling facts")
    if expected["allocatedQty"] > selected["availableQty"]:
        raise ValueError("Returned allocation exceeds shared stock")
    if sum(_number(row["plannedInboundQty"], "plannedInboundQty") for row in siblings) > selected["inboundQty"]:
        raise ValueError("Returned inbound proposal exceeds the shared inbound delivery")
    for row in siblings:
        if row["sourceType"] != "synthetic" or row["synthetic"] is not True:
            raise ValueError("A construction fixture record is not explicitly synthetic")
        if row["approvalRequired"] is not True or row["allocationStatus"] != "proposal":
            raise ValueError("A returned commitment bypasses proposal approval")
        if row["substitutionAllowed"] is True:
            if row["qualificationStatus"] != "human_review_required" or not row["substituteProductId"]:
                raise ValueError("A substitution candidate lacks the required human qualification boundary")
        elif row["substitutionAllowed"] is not False or row["substituteProductId"] is not None:
            raise ValueError("Invalid substitution permission or unpermitted substitute")
        later = _number(row["plannedInboundQty"], "plannedInboundQty")
        if later < 0 or later > row["shortageQty"] or not _same(
            row["afterInboundShortageQty"], row["shortageQty"] - later
        ):
            raise ValueError("Later inbound proposal does not reconcile with current shortage")
        if row["demandSignalId"] is None and any(row[key] is not None for key in (
            "campaignId", "campaignDemandQty", "campaignConfirmed", "campaignAllocationEligible"
        )):
            raise ValueError("Absent campaign evidence was replaced with invented public facts")


def _check(name: str, passed: bool) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed)}


def _has_evidence(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_evidence(child) for child in value.values())
    if isinstance(value, list):
        return any(_has_evidence(child) for child in value)
    return value is not None and value != ""


def governance_checks(result: dict[str, Any]) -> list[dict[str, Any]]:
    package = _object(result["actionPackage"], "actionPackage")
    context = _object(result["context"], "context")
    peers = {row["recordId"]: row for row in context["siblings"]}
    proposals = _array(package["proposedAllocations"], "proposedAllocations")
    proposal_ids = [proposal["recordId"] for proposal in proposals]
    exact_proposals = len(proposal_ids) == len(set(proposal_ids)) and set(proposal_ids) == set(peers)
    for proposal in proposals:
        peer = peers.get(proposal["recordId"])
        exact_proposals = exact_proposals and peer is not None
        if peer is not None:
            exact_proposals = exact_proposals and (
                _same(proposal["quantity"], peer["allocatedQty"])
                and _same(proposal["unfilledQty"], peer["shortageQty"])
                and proposal["unit"] == peer["unit"]
                and proposal["status"] == "proposal_pending_human_approval"
            )
    draft = package["customerDraft"]
    if not isinstance(draft, str):
        raise ValueError("customerDraft must be text")
    blockers = " ".join(_strings(package["blockedActions"], "blockedActions", nonempty=True)).lower()
    return [
        _check("resultApprovalRequired", result["approvalRequired"] is True),
        _check("packageApprovalRequired", package["approvalRequired"] is True),
        _check("proposalQuantitiesMatchContextAndRemainUnapproved", exact_proposals),
        _check("draftNotSentMarker", "draft" in draft.lower() and "not sent" in draft.lower()),
        _check("noAutomaticActionsMarker", "no automatic" in blockers),
        _check("qualificationRequiredMarker", "no substitute" in blockers and "qualification" in blockers),
        _check("supplyConfirmationRequiredMarker", "supply confirmation" in blockers),
    ]


def provenance_checks(result: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    lanes = [_object(item, "Evidence lane") for item in _array(result["evidenceLanes"], "evidenceLanes")]
    checks = [
        _check("requestedModePreserved", result["mode"] == mode),
        _check("queueSourceMatchesMode", result["context"]["queueSource"] == (
            "fabric_graphmodel" if mode == "live" else "offline_synthetic_fixture")),
        _check("exactlyThreeEvidenceLanes", len(lanes) == 3 and {lane["lane"] for lane in lanes} == LANES),
        _check("fabricEvidenceModeDeclared", result.get("fabricEvidenceMode") in {"ontology_graph", "native_knowledge_base"}),
    ]
    combined_calls = []
    for lane in lanes:
        name = lane["lane"]
        calls = _array(lane["toolCalls"], f"{name}.toolCalls")
        evidence = _array(lane["evidence"], f"{name}.evidence")
        combined_calls.extend(calls)
        checks.extend([
            _check(f"{name}.completed", lane["status"] == "completed"),
            _check(f"{name}.sourceMode", lane["sourceMode"] == mode),
            _check(f"{name}.hasReturnedEvidence", _has_evidence(evidence)),
            _check(f"{name}.syntheticBusinessDataDisclosed", lane["synthetic"] is True),
            _check(f"{name}.noLiveMicrosoft365Claim", lane["isLiveMicrosoft365"] is False),
        ])
        if name == "workIq":
            checks.append(_check("workIq.explicitSimulation", lane["synthetic"] is True and "simulated" in lane["label"].lower()))
        if mode == "offline":
            checks.append(_check(f"{name}.offlineNoCloudToolCalls", not calls and lane["synthetic"] is True))
        else:
            graph_mode = name == "fabricIq" and result.get("fabricEvidenceMode") == "ontology_graph"
            expected_transport = "client_function_to_fabric_rest" if graph_mode else "client_function_to_search_rest"
            retrieved = bool(calls) and all(
                call.get("lane") == name and call.get("tool") == "retrieve_evidence"
                and call.get("status") == "completed" and bool(call.get("source"))
                and call.get("transport") == expected_transport
                for call in calls
            )
            checks.append(_check(f"{name}.liveRetrievalTrace", retrieved))
            if name == "fabricIq":
                checks.append(_check("fabricIq.delegatedUserContext", bool(calls) and all(
                    call.get("delegatedUserContext") is True for call in calls)))
                checks.append(_check("fabricIq.nativeKnowledgeBaseClaimMatchesMode", bool(calls) and all(
                    call.get("nativeOntologyKnowledgeBaseUsed") is (not graph_mode) for call in calls)))
                if graph_mode:
                    checks.append(_check("fabricIq.ontologyGraphProof", any(
                        isinstance(item, dict) and item.get("sourceType") == "fabric_ontology_graph"
                        and item.get("ontologyId") and item.get("graphModelId") and item.get("gql")
                        and item.get("nativeKnowledgeBaseUsed") is False and item.get("references")
                        for item in evidence)))
            if name == "workIq":
                checks.append(_check("workIq.syntheticRetrievalTrace", bool(calls) and all(
                    call.get("syntheticCollaboration") is True for call in calls)))
    checks.append(_check("topLevelTraceMatchesLanes", result["toolCalls"] == combined_calls))
    package = result.get("actionPackage")
    answer = package.get("groundedAnswer") if isinstance(package, dict) else None
    checks.append(_check("modelAnswerMatchesExecutionMode", (
        isinstance(answer, str) and bool(answer.strip()) if mode == "live" else answer is None)))
    return checks


def evidence_availability(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    identifiers: set[str] = set()
    texts: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ("id", "documentId", "document_id", "title", "name", "url", "source", "docName", "fileName", "metadata_storage_path", "citationUrl") and isinstance(child, str):
                    identifiers.add(child.casefold())
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            texts.append(value)

    for lane in result.get("evidenceLanes", []):
        if lane.get("lane") == "foundryIq":
            visit(lane.get("evidence", []))
    text = "\n".join(texts)
    normalized = re.sub(r"\s+", " ", text).casefold()
    policies = []
    for policy_id in case["policyIds"]:
        identity = policy_id.casefold()
        found = any(identity == value or re.search(rf"(?:^|[/\\]){re.escape(identity)}\.md(?:$|[?#])", value)
                    for value in identifiers)
        found = found or re.search(rf"(?mi)^id:\s*{re.escape(policy_id)}\s*$", text) is not None
        policies.append({"id": policy_id, "observed": found})
    terms = [{"term": term, "observed": re.sub(r"\s+", " ", term).casefold() in normalized}
             for term in case.get("requiredTerms", [])]
    return {
        "basis": "Returned foundryIq.evidence only; no local policy reads by the runner",
        "policyIds": policies, "requiredTerms": terms,
        "allRequestedEvidenceObserved": all(item["observed"] for item in policies + terms),
        "interpretation": "Evidence availability observations, not required verbatim model wording or a semantic score.",
    }


def evaluate_result(case: dict[str, Any], result: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode not in ("offline", "live"):
        raise ValueError("mode must be offline or live")
    context = _object(result.get("context"), "result.context")
    checks = [_check("workflowCompleted", result.get("status") == "completed"),
              _check("requestedRecordPreserved", result.get("recordId") == case["recordId"]),
              _check("requestedQuestionPreserved", result.get("question") == case["question"])]
    try:
        validate_context(context, case["recordId"])
        checks.append(_check("returnedContextIntegrity", True))
    except VALIDATION_ERRORS as exc:
        checks.append({"name": "returnedContextIntegrity", "passed": False, "error": str(exc)})
    for name, function in (
        ("governance", lambda: governance_checks(result)),
        ("provenance", lambda: provenance_checks(result, mode)),
    ):
        try:
            checks.extend(function())
        except VALIDATION_ERRORS as exc:
            checks.append({"name": f"{name}Shape", "passed": False, "error": str(exc)})
    fact_checks = []
    for key, expected in case.get("expectedFacts", {}).items():
        item = {"field": key, "expected": expected, "source": "result.context"}
        try:
            actual = resolve_fact(key, context)
            item.update({"actual": actual, "passed": _same(actual, expected)})
        except VALIDATION_ERRORS as exc:
            item.update({"passed": False, "error": str(exc)})
        fact_checks.append(item)
    package = result.get("actionPackage")
    answer = package.get("groundedAnswer") if isinstance(package, dict) else None
    review_required = mode == "live" or isinstance(answer, str)
    passed = all(check["passed"] for check in checks + fact_checks)
    return {
        "id": case["id"], "recordId": case["recordId"], "question": case["question"],
        "expectedIntents": case["expectedIntents"], "status": "passed" if passed else "failed",
        "checksPassed": passed, "factChecks": fact_checks, "governanceAndProvenanceChecks": checks,
        "evidenceAvailability": evidence_availability(case, result),
        "generatedAnswer": {
            "text": answer, "reviewRequired": review_required,
            "reviewStatus": "pending_human_review" if review_required else "not_applicable_no_generated_answer",
            "semanticAssessment": "not_performed",
            "expectedIntentsForReview": case["expectedIntents"],
        },
        "result": result,
    }


def _persist_report(report: dict[str, Any], path: Path) -> None:
    cases = report["cases"]
    report["summary"] = {
        "casesExpected": report["caseCount"], "casesRun": len(cases),
        "passed": sum(case["status"] == "passed" for case in cases),
        "failed": sum(case["status"] == "failed" for case in cases),
        "errors": sum(case["status"] == "error" for case in cases),
        "casesWithEvidenceGaps": sum(not case.get("evidenceAvailability", {}).get("allRequestedEvidenceObserved", False)
                                   for case in cases),
        "checksPassed": len(cases) == report["caseCount"] and all(case["checksPassed"] for case in cases),
        "generatedAnswerReviewRequired": report["mode"] == "live" or any(
            case["generatedAnswer"]["reviewRequired"] for case in cases),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + "\n", encoding="utf-8")


def run_benchmark(
    mode: str,
    cases_path: Path = CASES_PATH,
    output_path: Path | None = None,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    if mode not in ("offline", "live"):
        raise ValueError("mode must be offline or live")
    cases = load_cases(cases_path)
    target = output_path if output_path is not None else RESULTS_ROOT / f"benchmark-{mode}.json"
    previous: dict[str, Any] = {}
    original_started = None
    if resume:
        saved = _object(json.loads(target.read_text(encoding="utf-8")), "Saved benchmark")
        if saved.get("mode") != mode or saved.get("caseCount") != len(cases):
            raise ValueError("Saved benchmark mode or case count differs; use a new output path")
        previous = {case["id"]: case for case in saved["cases"]}
        if len(previous) != len(saved["cases"]) or not set(previous).issubset({case["id"] for case in cases}):
            raise ValueError("Saved benchmark has duplicated or unrelated case IDs")
        for case in cases:
            old = previous.get(case["id"])
            if old and (old["recordId"], old["question"]) != (case["recordId"], case["question"]):
                raise ValueError("Saved benchmark inputs changed; use a new output path")
        original_started = saved["startedAt"]
    report: dict[str, Any] = {
        "schemaVersion": 1, "mode": mode, "caseCount": len(cases),
        "startedAt": original_started or datetime.now(UTC).isoformat(), "completedAt": None,
        "resumedAt": datetime.now(UTC).isoformat() if resume else None,
        "validationScope": "deterministic_offline_fixture_workflow" if mode == "offline" else "live_orchestrator_context_and_retrieval_provenance",
        "cloudChecksAttempted": mode == "live",
        "interpretation": (
            "Offline checks exercise actual orchestration over synthetic fixtures. No cloud check or model answer evaluation ran."
            if mode == "offline" else
            "Checks use actual orchestrator-returned context and retrieval traces. Generated answers require separate human review; no semantic score is assigned."
        ),
        "cases": [],
    }
    _persist_report(report, target)
    for case in cases:
        old = previous.get(case["id"])
        if old and isinstance(old.get("result"), dict):
            observed = evaluate_result(case, old["result"], mode)
            if observed["checksPassed"] and observed["evidenceAvailability"]["allRequestedEvidenceObserved"]:
                observed["execution"] = "revalidated_persisted_response_no_new_cloud_call"
                if old.get("previousAttempts"):
                    observed["previousAttempts"] = old["previousAttempts"]
                report["cases"].append(observed)
                _persist_report(report, target)
                continue
        print(f"Running {mode} benchmark case {case['id']}", flush=True)
        try:
            result = orchestrator.run({"mode": mode, "recordId": case["recordId"], "question": case["question"]})
            evaluated = evaluate_result(case, result, mode)
        except RUN_ERRORS as exc:
            print(f"Benchmark {case['id']} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            evaluated = {
                "id": case["id"], "recordId": case["recordId"], "question": case["question"],
                "expectedIntents": case["expectedIntents"], "status": "error", "checksPassed": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "governanceAndProvenanceChecks": [{"name": "orchestratorReturnedUsableResult", "passed": False}],
                "generatedAnswer": {"text": None, "reviewRequired": mode == "live",
                                    "reviewStatus": "no_answer_due_to_error", "semanticAssessment": "not_performed"},
            }
        evaluated["execution"] = "new_orchestrator_run"
        if old:
            evaluated["previousAttempts"] = [*old.get("previousAttempts", []), {
                key: value for key, value in old.items() if key != "previousAttempts"
            }]
        report["cases"].append(evaluated)
        _persist_report(report, target)
    report["completedAt"] = datetime.now(UTC).isoformat()
    _persist_report(report, target)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Check returned benchmark facts/provenance; generated answers need human review.")
    parser.add_argument("--mode", choices=("offline", "live"), required=True)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true", help="Revalidate saved responses and rerun only failed or incomplete cases, preserving failed attempts.")
    args = parser.parse_args()
    report = run_benchmark(args.mode, args.cases, args.output, resume=args.resume)
    target = args.output if args.output is not None else RESULTS_ROOT / f"benchmark-{args.mode}.json"
    print(json.dumps({"report": str(target), "mode": args.mode, **report["summary"]}, indent=2))
    return 0 if report["summary"]["checksPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
