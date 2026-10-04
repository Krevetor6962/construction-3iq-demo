from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable, TypeVar
from urllib.parse import quote, urlparse

from azure.identity import AzureCliCredential
from openai import RateLimitError

from construction_iq.config import DemoProfile

SEARCH_API = "2026-08-01-preview"
LOG = logging.getLogger(__name__)
T = TypeVar("T")


class CloudError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def model_call(operation: Callable[[], T]) -> T:
    for attempt in range(3):
        try:
            return operation()
        except RateLimitError as exc:
            if attempt == 2:
                raise
            milliseconds = exc.response.headers.get("retry-after-ms")
            header = milliseconds or exc.response.headers.get("retry-after")
            delay = 60.0
            if header:
                try:
                    delay = float(header) / (1000 if milliseconds else 1)
                except ValueError:
                    LOG.warning("Unrecognized model Retry-After header; using a 60-second token-window wait")
            if not 0 <= delay <= 120:
                LOG.error("Model retry delay exceeds the bounded retry window; surfacing the rate limit")
                raise
            LOG.warning("Model token rate limit: waiting %.1f seconds before retry %d of 2", max(1, delay), attempt + 1)
            time.sleep(max(1, delay))
    raise CloudError("Model call exhausted its bounded retry budget")


def credential() -> AzureCliCredential:
    profile = DemoProfile.load()
    profile.require_cloud_target()
    return AzureCliCredential(
        subscription=profile.subscription_id,
        process_timeout=30,
    )


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid cloud item identifier")
    return quote(value, safe="")


class CloudClient:
    def __init__(self) -> None:
        self.credential = credential()

    def request(
        self,
        method: str,
        url: str,
        scope: str,
        body: dict[str, Any] | bytes | None = None,
        *,
        delegated: bool = False,
        timeout: int = 180,
        content_type: str = "application/json",
        content_disposition: str | None = None,
    ) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
            raise ValueError("Cloud endpoints must use authenticated HTTPS URLs without embedded credentials")
        if not parsed.hostname.endswith((".search.windows.net", ".fabric.microsoft.com")):
            raise ValueError("This client only sends tokens to Azure Search and Fabric")
        token = self.credential.get_token(scope).token
        headers = {"Authorization": f"Bearer {token}", "Content-Type": content_type}
        if content_disposition:
            headers["Content-Disposition"] = content_disposition
        if delegated:
            headers["x-ms-query-source-authorization"] = token
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8") if body is not None else None
        attempts = 1 if isinstance(body, bytes) and method.upper() == "POST" else 3
        for attempt in range(attempts):
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                    raw = response.read()
                    result = json.loads(raw) if raw else {}
                    if not isinstance(result, dict):
                        raise CloudError("Cloud service returned an unexpected response shape")
                    return result
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if '"CapacityNotActive"' in detail:
                    raise CloudError(
                        "The selected Fabric capacity is paused/inactive. Live mode cannot run. "
                        "Resume the existing capacity through your approved administration process, "
                        "or explicitly select Offline synthetic demo. No fallback was used."
                    ) from None
                if exc.code in {429, 502, 503, 504} and attempt < attempts - 1:
                    delay = exc.headers.get("Retry-After", "")
                    wait = int(delay) if delay.isdigit() else 60 if exc.code == 429 else 2 ** (attempt + 1)
                    if wait > 120:
                        raise CloudError("Cloud service requested a retry delay beyond the bounded wait") from None
                    LOG.warning("Cloud HTTP %s: waiting %s seconds before retry", exc.code, max(1, wait))
                    time.sleep(max(1, wait))
                    continue
                safe_detail = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", detail)[:900]
                raise CloudError(f"{method} request failed (HTTP {exc.code}): {safe_detail}") from None
            except (urllib.error.URLError, TimeoutError) as exc:
                raise CloudError(f"Cloud request timed out or could not connect: {exc.reason if isinstance(exc, urllib.error.URLError) else type(exc).__name__}") from None
        raise CloudError("Cloud request exhausted its retry budget")

    def upload_search_file(
        self, endpoint: str, source: str, name: str, content: bytes, file_id: str | None = None
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise ValueError("Policy file names must be simple names without paths or header control characters")
        path = f"knowledgesources/{identifier(source)}/files"
        if file_id:
            path = f"knowledgesources('{identifier(source)}')/files('{identifier(file_id)}')"
        return self.request(
            "PUT" if file_id else "POST",
            f"{endpoint.rstrip('/')}/{path}?api-version={SEARCH_API}",
            "https://search.azure.com/.default", content,
            content_type="application/octet-stream",
            content_disposition=f'attachment; filename="{name}"',
            timeout=240,
        )

    def search(
        self,
        endpoint: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        method: str = "POST",
        delegated: bool = False,
    ) -> dict[str, Any]:
        return self.request(
            method,
            f"{endpoint.rstrip('/')}/{path}?api-version={SEARCH_API}",
            "https://search.azure.com/.default",
            body,
            delegated=delegated,
        )


def retrieve_knowledge(
    client: CloudClient, deployment: dict[str, Any], lane: str, question: str
) -> dict[str, Any]:
    if lane not in {"fabricIq", "foundryIq"}:
        raise ValueError("Only the Fabric and policy lanes use knowledge bases")
    name = deployment["knowledgeBases"][lane]
    result = client.search(
        deployment["azure"]["searchEndpoint"],
        f"knowledgebases/{identifier(name)}/retrieve",
        {
            "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
            "includeActivity": True,
            "knowledgeSourceParams": [{
                "knowledgeSourceName": deployment["knowledgeSources"][lane],
                "kind": deployment["knowledgeSourceKinds"][lane],
                "alwaysQuerySource": True,
                "failOnError": True,
                "includeReferences": True,
                "includeReferenceSourceData": True,
            }],
        },
        delegated=lane == "fabricIq",
    )
    if not result.get("references"):
        raise CloudError(f"{lane} returned no cited knowledge. No fallback was used.")
    return result


def retrieve_collaboration(
    client: CloudClient, deployment: dict[str, Any], record_ids: list[str]
) -> dict[str, Any]:
    if not record_ids:
        raise ValueError("At least one record is required for collaboration retrieval")
    filters = " or ".join(f"recordId eq '{record.replace(chr(39), chr(39) * 2)}'" for record in record_ids)
    result = client.search(
        deployment["azure"]["searchEndpoint"],
        f"indexes/{identifier(deployment['workIndex'])}/docs/search",
        {"search": "*", "filter": f"({filters}) and sourceType eq 'synthetic'", "top": 100},
    )
    documents = result.get("value", [])
    if not documents:
        raise CloudError("No synthetic collaboration context found for these commitments")
    return {"documents": documents, "sourceType": "synthetic", "isLiveMicrosoft365": False}
