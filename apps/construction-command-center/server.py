from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import threading
import time
import uuid
from copy import deepcopy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from construction_iq.config import ConfigurationError, DemoProfile, load_deployment
from construction_iq.orchestrator import action_package, run, synthesize
from construction_iq.queue import load_queue

LOG = logging.getLogger("construction-command-center")
STATIC = Path(__file__).resolve().parent / "static"
LOCK = threading.RLock()
JOBS: dict[str, dict[str, Any]] = {}
STAGES = ("prepare", "fabricIq", "foundryIq", "workIq", "actionPackage")


def health() -> dict[str, Any]:
    profile = DemoProfile.load()
    try:
        load_deployment()
    except ConfigurationError as exc:
        cloud = {"configured": False, "status": "not_ready", "message": str(exc)}
    else:
        cloud = {"configured": True, "status": "not_probed", "message": "Live retrieval is verified when you run the demo."}
    return {
        "app": "construction-command-center", "localStatus": "ready",
        "displayName": profile.display_name, "supplierName": profile.supplier_name,
        "asOfDate": profile.as_of_date.isoformat(), "currency": profile.currency,
        "fabricEvidenceMode": profile.fabric_evidence_mode,
        "cloud": cloud, "workIq": "synthetic_not_live_microsoft365",
    }


def get_job(job_id: str) -> dict[str, Any]:
    with LOCK:
        if job_id not in JOBS:
            raise KeyError("Job not found; local job state is cleared when the server restarts")
        return deepcopy(JOBS[job_id])


def start_job(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) - {"question", "recordId", "mode"}:
        raise ValueError("Unsupported orchestration request fields")
    if payload.get("mode", "live") not in {"live", "offline"}:
        raise ValueError("mode must be live or offline")
    if not isinstance(payload.get("question"), str) or not payload["question"].strip():
        raise ValueError("question is required")
    if not isinstance(payload.get("recordId"), str) or not payload["recordId"]:
        raise ValueError("recordId is required")
    with LOCK:
        if sum(job["status"] == "running" for job in JOBS.values()) >= 2:
            raise RuntimeError("Two demo runs are already active; wait for them to finish")
        if len(JOBS) >= 100:
            completed = next((key for key, value in JOBS.items() if value["status"] != "running"), None)
            if completed is not None:
                del JOBS[completed]
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {
            "jobId": job_id, "status": "running", "createdAt": time.time(),
            "request": payload, "result": None, "error": None,
            "stages": {stage: {"status": "pending", "summary": "Waiting"} for stage in STAGES},
        }

    def progress(event: dict[str, Any]) -> None:
        with LOCK:
            JOBS[job_id]["stages"][event["stage"]] = event

    def execute() -> None:
        try:
            result = run(payload, progress=progress)
            with LOCK:
                JOBS[job_id]["result"] = result
                JOBS[job_id]["status"] = result["status"]
        except Exception as exc:
            LOG.exception("Orchestration job failed: %s", job_id)
            with LOCK:
                JOBS[job_id]["status"] = "failed"
                JOBS[job_id]["error"] = str(exc)

    threading.Thread(target=execute, daemon=True, name=f"construction-{job_id}").start()
    return get_job(job_id)


def followup(payload: dict[str, Any]) -> dict[str, Any]:
    question = payload.get("question")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
        raise ValueError("Follow-up question must contain 1 to 4000 characters")
    job = get_job(str(payload.get("jobId", "")))
    result = job.get("result")
    if job["status"] != "completed" or not result:
        raise ValueError("Follow-up requires a completed, fully grounded run")
    package = action_package(result["context"], question)
    if result["mode"] == "live":
        answer = synthesize(
            {"question": question, "context": result["context"], "lanes": result["evidenceLanes"]},
            package,
        )
    else:
        answer = package["customerDraft"] if "email" in question.lower() or "draft" in question.lower() else package["summary"]
        answer = "Offline demonstration - no model or live retrieval.\n" + answer
    return {"answer": answer, "mode": result["mode"], "reusedEvidenceFrom": job["jobId"], "approvalRequired": True}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.handle_route("GET")

    def do_POST(self) -> None:
        self.handle_route("POST")

    def handle_route(self, method: str) -> None:
        try:
            self.route(method)
        except KeyError as exc:
            self.send_json({"status": "failed", "error": str(exc)}, HTTPStatus.NOT_FOUND)
        except (ValueError, ConfigurationError) as exc:
            LOG.warning("Invalid request or configuration: %s", exc)
            self.send_json({"status": "failed", "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            LOG.exception("Request failed")
            self.send_json({"status": "failed", "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def route(self, method: str) -> None:
        host = urlparse("//" + self.headers.get("Host", ""))
        if host.hostname not in {"127.0.0.1", "localhost"} or host.port != self.server.server_port:
            raise ValueError("Only the local demo origin is permitted")
        parsed = urlparse(self.path)
        if method == "GET":
            if parsed.path == "/api/health":
                self.send_json(health())
            elif parsed.path == "/api/scenarios":
                mode = parse_qs(parsed.query).get("mode", ["live"])[0]
                self.send_json(load_queue(mode))
            elif parsed.path.startswith("/api/jobs/"):
                self.send_json(get_job(parsed.path.rsplit("/", 1)[-1]))
            elif parsed.path.startswith("/api/"):
                raise KeyError("Unknown API endpoint")
            else:
                relative = "index.html" if parsed.path == "/" else parsed.path.lstrip("/")
                target = (STATIC / relative).resolve()
                if not target.is_relative_to(STATIC) or not target.is_file():
                    raise KeyError("Static asset not found")
                content = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(content)
            return
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            raise ValueError("Cross-origin requests are not permitted")
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise ValueError("Content-Type must be application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 32768:
            raise ValueError("Request body must be between 1 and 32768 bytes")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        if parsed.path == "/api/orchestrate/start":
            self.send_json(start_job(payload), HTTPStatus.ACCEPTED)
        elif parsed.path == "/api/orchestrate/chat":
            self.send_json(followup(payload))
        else:
            raise KeyError("Unknown API endpoint")

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=True, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        LOG.info(format, *args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local construction supplier demo (loopback only).")
    parser.add_argument("--port", type=int, default=8095)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        LOG.info("Open http://127.0.0.1:%s - synthetic data; human approval required", args.port)
        server.serve_forever()
