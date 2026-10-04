from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import UUID

from construction_iq.config import DEPLOYMENT_PATH, DemoProfile

FABRIC_API_BASE = "https://api.fabric.microsoft.com/v1"
FABRIC_RESOURCE = "https://api.fabric.microsoft.com"
KUSTO_RESOURCE = "https://kusto.kusto.windows.net"
STORAGE_RESOURCE = "https://storage.azure.com"
ONELAKE_DFS_BASE = "https://onelake.dfs.fabric.microsoft.com"


class FabricApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.payload = payload


def gql_identifier(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise FabricApiError(f"Invalid schema-controlled GQL identifier: {name!r}")
    return f"`{name}`"


def manifest_base(profile: DemoProfile) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "subscriptionId": profile.subscription_id,
        "tenantId": profile.tenant_id,
        "resourceGroup": profile.resource_group,
        "capacityId": profile.capacity_id,
        "workspaceName": profile.workspace_name,
    }


def load_partial_deployment(path: Path = DEPLOYMENT_PATH, profile: DemoProfile | None = None) -> dict[str, Any]:
    expected = manifest_base(profile or DemoProfile.load())
    if not path.exists():
        return expected
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise FabricApiError(f"Deployment manifest is not a JSON object: {path}")
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise FabricApiError(f"Deployment manifest {key} does not match the selected profile.")
    for key in ("items", "azure"):
        if key in manifest and not isinstance(manifest[key], dict):
            raise FabricApiError(f"Deployment manifest {key} must be an object.")
    return manifest


@contextmanager
def manifest_lock(path: Path, timeout_seconds: float = 30) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise FabricApiError(f"Manifest lock busy: {lock_path}. Check for another writer; do not remove an active lock.")
            time.sleep(0.1)
    try:
        os.close(descriptor)
        yield
    finally:
        lock_path.unlink()


def _merge(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value


def merge_deployment(
    updates: dict[str, Any], path: Path = DEPLOYMENT_PATH, profile: DemoProfile | None = None,
) -> dict[str, Any]:
    profile = profile or DemoProfile.load()
    path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_lock(path):
        manifest = load_partial_deployment(path, profile)
        for key, value in manifest_base(profile).items():
            if key in updates and updates[key] != value:
                raise FabricApiError(f"Cannot change manifest identity field {key}.")
        if manifest.get("workspaceId") and updates.get("workspaceId", manifest["workspaceId"]) != manifest["workspaceId"]:
            raise FabricApiError("Cannot replace the owned workspace ID.")
        for section in ("items", "azure"):
            for key, value in updates.get(section, {}).items():
                existing = manifest.get(section, {}).get(key)
                if existing is not None and existing != value:
                    raise FabricApiError(f"Cannot replace owned deployment reference {section}.{key}.")
        _merge(manifest, updates)
        descriptor, temporary = tempfile.mkstemp(prefix=".deployment-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return manifest


def get_az_token(resource: str, profile: DemoProfile | None = None) -> str:
    profile = profile or DemoProfile.load()
    profile.require_cloud_target()
    executable = shutil.which("az") or shutil.which("az.cmd")
    if not executable:
        raise FabricApiError("Azure CLI is required. Install/sign in separately before cloud deployment.")
    result = subprocess.run(
        [executable, "account", "get-access-token", "--resource", resource, "--subscription", profile.subscription_id,
         "--query", "{accessToken:accessToken,tenant:tenant,subscription:subscription}", "--output", "json", "--only-show-errors"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode:
        raise FabricApiError(f"Azure CLI token acquisition failed for {resource}: {result.stderr.strip()}")
    payload = json.loads(result.stdout)
    if payload.get("tenant") != profile.tenant_id or payload.get("subscription") != profile.subscription_id:
        raise FabricApiError("Azure CLI token context does not match the configured subscription and tenant.")
    token = payload.get("accessToken")
    if not isinstance(token, str) or not token.strip():
        raise FabricApiError(f"Azure CLI returned an empty token for {resource}.")
    return token.strip()


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: str

    def json(self) -> dict[str, Any]:
        value = json.loads(self.body) if self.body.strip() else {}
        if not isinstance(value, dict):
            raise FabricApiError("Expected a JSON object in the service response.")
        return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


class _TokenHttpClient:
    def __init__(self, resource: str, token: str | None = None) -> None:
        self.resource = resource
        self._supplied_token = token
        self._cached_token: str | None = None
        self._token_time = 0.0

    def _send(self, method: str, url: str, data: bytes | None = None, content_type: str | None = None) -> HttpResponse:
        if not self._supplied_token and (not self._cached_token or time.monotonic() - self._token_time > 2400):
            self._cached_token = get_az_token(self.resource)
            self._token_time = time.monotonic()
        headers = {"Authorization": f"Bearer {self._supplied_token or self._cached_token}", "Accept": "application/json"}
        if self.resource == STORAGE_RESOURCE:
            headers["x-ms-version"] = "2021-06-08"
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=120) as response:
                return HttpResponse(response.status, {k.lower(): v for k, v in response.headers.items()}, response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = text
            raise FabricApiError(f"{method} {url} failed (HTTP {error.code}): {text}", error.code, payload) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise FabricApiError(f"{method} {url} failed: {error}") from error


class FabricRestClient(_TokenHttpClient):
    def __init__(self, token: str | None = None) -> None:
        super().__init__(FABRIC_RESOURCE, token)

    @staticmethod
    def _url(path_or_url: str) -> str:
        url = path_or_url if path_or_url.startswith("https://") else FABRIC_API_BASE + path_or_url
        parsed = urllib.parse.urlsplit(url)
        allowed_host = parsed.netloc == "api.fabric.microsoft.com" or re.fullmatch(
            r"wabi-[a-z0-9-]+-redirect\.analysis\.windows\.net", parsed.netloc
        ) is not None
        if parsed.scheme != "https" or not allowed_host or not parsed.path.startswith("/v1/"):
            raise FabricApiError(f"Refusing an unexpected Fabric endpoint: {url}")
        return url

    def raw_request(self, method: str, path_or_url: str, body: dict[str, Any] | None = None) -> HttpResponse:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        return self._send(method.upper(), self._url(path_or_url), data, "application/json" if data is not None else None)

    def request(
        self, method: str, path_or_url: str, body: dict[str, Any] | None = None,
        follow_lro: bool = True, timeout_seconds: int = 1800,
        on_accepted: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        response = self.raw_request(method, path_or_url, body)
        if response.status == 202 and follow_lro:
            location = response.headers.get("location")
            if not location:
                raise FabricApiError("Fabric accepted a request but omitted its operation Location.")
            self._url(location)
            if on_accepted is not None:
                on_accepted(location)
            return self._poll_lro(response, timeout_seconds)
        return response.json()

    def wait_operation(self, location: str, timeout_seconds: int = 1800) -> dict[str, Any]:
        return self._poll_lro(HttpResponse(202, {"location": location, "retry-after": "1"}, "{}"), timeout_seconds)

    def list_all(self, path_or_url: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        visited: set[str] = set()
        next_url = path_or_url
        for _ in range(1000):
            if next_url in visited:
                raise FabricApiError("Fabric pagination returned a repeated continuation URI.")
            visited.add(next_url)
            payload = self.request("GET", next_url)
            values = payload.get("value")
            if not isinstance(values, list):
                raise FabricApiError("Fabric list response is missing its value array.", payload=payload)
            results.extend(values)
            next_url = payload.get("continuationUri", "")
            if not next_url:
                if payload.get("continuationToken"):
                    raise FabricApiError("Fabric returned a continuation token without a URI; pagination is incomplete.")
                return results
        raise FabricApiError("Fabric pagination exceeded 1000 pages.")

    def _poll_lro(self, response: HttpResponse, timeout_seconds: int) -> dict[str, Any]:
        location = response.headers.get("location")
        if not location:
            raise FabricApiError("Fabric accepted a request but omitted the long-running-operation Location.")
        self._url(location)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(min(30, max(1, int(response.headers.get("retry-after", "5")))))
            response = self.raw_request("GET", location)
            payload = response.json()
            status = payload.get("status")
            if status == "Succeeded":
                return self.request("GET", location.rstrip("/") + "/result", follow_lro=False)
            if status == "Completed":
                return payload
            if status in {"Failed", "Cancelled", "Canceled", "Deduped"}:
                raise FabricApiError(f"Fabric operation {location} ended {status}: {json.dumps(payload)}", payload=payload)
            if status not in {"NotStarted", "Running", "InProgress", "Undefined"}:
                raise FabricApiError(f"Unknown Fabric operation status {status!r}: {json.dumps(payload)}", payload=payload)
        raise FabricApiError(f"Timed out waiting for Fabric operation {location}.")

    def run_job(self, workspace_id: str, item_id: str, job_type: str, body: dict[str, Any] | None = None, timeout_seconds: int = 3600) -> dict[str, Any]:
        path = f"/workspaces/{workspace_id}/items/{item_id}/jobs/instances?jobType={urllib.parse.quote(job_type)}"
        response = self.raw_request("POST", path, body)
        if response.status != 202 or not response.headers.get("location"):
            raise FabricApiError("Job submission did not return HTTP 202 with an exact job Location.", payload=response.json())
        return self.wait_job(workspace_id, item_id, response.headers["location"], timeout_seconds)

    def wait_job(self, workspace_id: str, item_id: str, location: str, timeout_seconds: int = 3600) -> dict[str, Any]:
        expected = f"/v1/workspaces/{workspace_id}/items/{item_id}/jobs/instances/"
        if not urllib.parse.urlsplit(self._url(location)).path.startswith(expected):
            raise FabricApiError("Job Location does not belong to the submitted item.")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            job = self.request("GET", location, follow_lro=False)
            if job.get("status") == "Completed":
                return job
            if job.get("status") in {"Failed", "Cancelled", "Canceled", "Deduped"}:
                raise FabricApiError(f"Fabric job failed: {json.dumps(job)}", payload=job)
            if job.get("status") not in {"NotStarted", "Running", "InProgress"}:
                raise FabricApiError(f"Unknown Fabric job state: {json.dumps(job)}", payload=job)
            time.sleep(10)
        raise FabricApiError(f"Timed out waiting for Fabric job at {location}.")

    def query_graph(self, workspace_id: str, graph_id: str, query: str) -> list[dict[str, Any]]:
        result = self.request("POST", f"/workspaces/{workspace_id}/graphModels/{graph_id}/executeQuery?preview=true", {"query": query, "preview": True})
        if result.get("status", {}).get("code") != "00000":
            raise FabricApiError(f"Live graph query failed: {json.dumps(result)}", payload=result)
        rows = result.get("result", {}).get("data")
        if not isinstance(rows, list) or not rows:
            raise FabricApiError("Live graph query returned no result rows.", payload=result)
        return rows


class OneLakeClient(_TokenHttpClient):
    def __init__(self, token: str | None = None) -> None:
        super().__init__(STORAGE_RESOURCE, token)

    @staticmethod
    def _url(workspace_id: str, lakehouse_id: str, path: str) -> str:
        UUID(workspace_id)
        UUID(lakehouse_id)
        if not path.startswith("Files/") or any(part in {"", ".", ".."} for part in path.split("/")) or "\\" in path:
            raise FabricApiError("OneLake operations are restricted to explicit relative Files paths.")
        return f"{ONELAKE_DFS_BASE}/{workspace_id}/{lakehouse_id}/{urllib.parse.quote(path, safe='/')}"

    def upload_file(self, workspace_id: str, lakehouse_id: str, local_path: Path, remote_path: str) -> None:
        parts = remote_path.split("/")
        for index in range(2, len(parts)):
            url = self._url(workspace_id, lakehouse_id, "/".join(parts[:index]))
            try:
                self._send("PUT", url + "?resource=directory", b"")
            except FabricApiError as error:
                code = error.payload.get("error", {}).get("code") if isinstance(error.payload, dict) else None
                if error.status != 409 or code != "PathAlreadyExists":
                    raise
        url = self._url(workspace_id, lakehouse_id, remote_path)
        self._send("PUT", url + "?resource=file", b"")
        position = 0
        with local_path.open("rb") as handle:
            while chunk := handle.read(4 * 1024 * 1024):
                self._send("PATCH", f"{url}?action=append&position={position}", chunk, "application/octet-stream")
                position += len(chunk)
        self._send("PATCH", f"{url}?action=flush&position={position}", b"")

    def read_json(self, workspace_id: str, lakehouse_id: str, remote_path: str) -> dict[str, Any]:
        return self._send("GET", self._url(workspace_id, lakehouse_id, remote_path)).json()


def kql_connection(database: dict[str, Any]) -> tuple[str, str]:
    query_uri = database.get("properties", {}).get("queryServiceUri")
    database_id = database.get("id")
    if not isinstance(query_uri, str) or not query_uri or not isinstance(database_id, str):
        raise FabricApiError("KQL metadata must expose its queryServiceUri and item ID.", payload=database)
    UUID(database_id)
    # Fabric exposes no databaseName property; the item ID is its stable Kusto selector.
    return query_uri, database_id


class KustoClient(_TokenHttpClient):
    def __init__(self, query_service_uri: str, database_name: str, token: str | None = None) -> None:
        super().__init__(KUSTO_RESOURCE, token)
        parsed = urllib.parse.urlsplit(query_service_uri)
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port
            or not parsed.hostname.endswith((".kusto.fabric.microsoft.com", ".kusto.windows.net"))
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
        ):
            raise FabricApiError("Expected a Fabric/Kusto HTTPS query-service origin.")
        self.query_service_uri = query_service_uri.rstrip("/")
        self.database_name = database_name

    def _execute(self, endpoint: str, csl: str) -> dict[str, Any]:
        data = json.dumps({"db": self.database_name, "csl": csl}).encode("utf-8")
        result = self._send("POST", self.query_service_uri + endpoint, data, "application/json").json()
        if result.get("error") or result.get("Errors"):
            raise FabricApiError(f"Kusto returned an error: {json.dumps(result)}", payload=result)
        for table in result.get("Tables", []):
            if table.get("TableName") == "QueryStatus":
                columns = [column.get("ColumnName") for column in table.get("Columns", [])]
                if "Severity" in columns and any(int(row[columns.index("Severity")]) <= 2 for row in table.get("Rows", [])):
                    raise FabricApiError(f"Kusto query did not complete successfully: {json.dumps(table)}", payload=table)
        return result

    def execute_query(self, csl: str) -> dict[str, Any]:
        return self._execute("/v1/rest/query", csl)

    def execute_mgmt(self, csl: str) -> dict[str, Any]:
        return self._execute("/v1/rest/mgmt", csl)

    def scalar_count(self, table_name: str) -> int:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", table_name):
            raise FabricApiError("Invalid KQL table identifier.")
        payload = self.execute_query(f"{table_name} | count")
        tables = [table for table in payload.get("Tables", []) if table.get("Rows") and table.get("TableName") != "QueryStatus"]
        if not tables:
            raise FabricApiError(f"KQL count returned no rows for {table_name}.", payload=payload)
        return int(tables[0]["Rows"][0][0])


def verify_owned_workspace(fabric: FabricRestClient, manifest: dict[str, Any], profile: DemoProfile) -> dict[str, Any]:
    workspace_id = manifest.get("workspaceId")
    if not workspace_id:
        raise FabricApiError("No owned workspaceId is recorded; deploy the new Fabric workspace first.")
    UUID(workspace_id)
    workspace = fabric.request("GET", f"/workspaces/{workspace_id}")
    if workspace.get("id") != workspace_id or workspace.get("displayName") != profile.workspace_name:
        raise FabricApiError("Recorded workspace ID/name does not match the configured new workspace.")
    if workspace.get("capacityId", "").lower() != profile.capacity_id.lower():
        raise FabricApiError("Owned workspace is not on the configured capacity. Capacity reassignment is not automatic.")
    return workspace


def require_fabric_items(manifest: dict[str, Any]) -> dict[str, Any]:
    items = manifest.get("items", {})
    for key in ("lakehouseId", "eventhouseId", "kqlDatabaseId", "ontologyId", "graphModelId", "notebookId"):
        value = items.get(key)
        if not isinstance(value, str):
            raise FabricApiError(f"Fabric deployment is incomplete: items.{key} is missing.")
        UUID(value)
    for key in ("kqlQueryUri", "kqlDatabaseName"):
        if not isinstance(items.get(key), str) or not items[key]:
            raise FabricApiError(f"Fabric deployment is incomplete: items.{key} is missing.")
    return items


def _main() -> None:
    parser = argparse.ArgumentParser(description="Atomically merge infrastructure outputs without requiring the other workstream.")
    parser.add_argument("--merge", required=True, type=Path)
    args = parser.parse_args()
    updates = json.loads(args.merge.read_text(encoding="utf-8-sig"))
    if not isinstance(updates, dict):
        raise FabricApiError("Manifest update must be an object.")
    merge_deployment(updates)


if __name__ == "__main__":
    _main()
