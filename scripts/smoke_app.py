from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any

from construction_iq.config import ROOT


def api(base: str, route: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        base.rstrip("/") + route,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.load(response)


def run_job(base: str, record_id: str, question: str, mode: str) -> dict[str, Any]:
    job = api(base, "/api/orchestrate/start", {"recordId": record_id, "question": question, "mode": mode})
    deadline = time.monotonic() + 900
    while job["status"] == "running":
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Orchestration {job['jobId']} exceeded the acceptance timeout")
        time.sleep(2)
        job = api(base, f"/api/jobs/{job['jobId']}")
    if job["status"] != "completed":
        raise RuntimeError(f"Orchestration did not complete: {json.dumps(job)}")
    result = job["result"]
    if set(lane["lane"] for lane in result["evidenceLanes"]) != {"fabricIq", "foundryIq", "workIq"}:
        raise AssertionError("Expected exactly three evidence lanes")
    if not result["actionPackage"]["approvalRequired"]:
        raise AssertionError("Human approval requirement was lost")
    work = next(lane for lane in result["evidenceLanes"] if lane["lane"] == "workIq")
    if not work["synthetic"] or work["isLiveMicrosoft365"]:
        raise AssertionError("Synthetic collaboration provenance was lost")
    if mode == "live":
        if result["context"]["queueSource"] != "fabric_graphmodel":
            raise AssertionError("Live queue did not come from Fabric")
        if {call["lane"] for call in result["toolCalls"] if call["status"] == "completed"} != {"fabricIq", "foundryIq", "workIq"}:
            raise AssertionError("Missing actual retrieval tool-call proof")
        for lane in result["evidenceLanes"]:
            if lane["lane"] != "workIq" and not any(evidence.get("references") for evidence in lane["evidence"]):
                raise AssertionError(f"Missing retrieved citations for {lane['lane']}")
    elif result["toolCalls"]:
        raise AssertionError("Offline run unexpectedly claimed remote tool calls")
    return job


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise three real local API presenter journeys and persist proof.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8095")
    parser.add_argument("--mode", choices=("live", "offline"), default="live")
    args = parser.parse_args()
    queue = api(args.base_url, f"/api/scenarios?mode={args.mode}")
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in queue["records"]:
        if record["anchor"] and record["clusterId"] not in seen:
            selected.append(record)
            seen.add(record["clusterId"])
    if len(selected) < 3:
        raise AssertionError("Expected at least three curated constraint clusters")
    journeys = []
    for record, question in zip(selected[:3], (
        "Which customer commitments should we protect first, and which other customers share the shortage?",
        "Is an alternative material automatically approved? Explain the policy and human checkpoint.",
        "What can the account manager say now, and what must wait for supply confirmation?",
    )):
        print(f"Running {args.mode} journey for {record['recordId']}", flush=True)
        job = run_job(args.base_url, record["recordId"], question, args.mode)
        followup = api(args.base_url, "/api/orchestrate/chat", {
            "jobId": job["jobId"], "question": "Draft a customer-safe email that does not overpromise quantities or delivery dates.",
        })
        if not followup.get("answer") or followup["reusedEvidenceFrom"] != job["jobId"]:
            raise AssertionError("Follow-up did not reuse this run's evidence")
        journeys.append({"recordId": record["recordId"], "result": job["result"], "followup": followup})
    result = {
        "mode": args.mode, "status": "passed", "journeys": journeys,
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
        "cloudAcceptance": args.mode == "live",
    }
    output = ROOT / "tests" / "results" / f"app-smoke-{args.mode}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(f"Three {args.mode} journeys passed. Results: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
