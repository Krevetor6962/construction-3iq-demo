from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / "config" / "demo-profile.json"
DEPLOYMENT_PATH = ROOT / "config" / "deployment.json"
DATA_ROOT = ROOT / "data" / "construction_synthetic"
FabricEvidenceMode = Literal["ontology_graph", "native_knowledge_base"]


class ConfigurationError(ValueError):
    pass


def read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigurationError(f"Required configuration does not exist: {path}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ConfigurationError(f"Expected a JSON object in {path}")
    return result


def required_text(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"Missing or invalid configuration field: {key}")
    return value.strip()


@dataclass(frozen=True)
class DemoProfile:
    display_name: str
    supplier_name: str
    currency: str
    seed: int
    as_of_date: date
    workspace_name: str
    resource_group: str
    subscription_id: str
    tenant_id: str
    capacity_id: str
    azure_region: str
    foundry_region: str
    fabric_evidence_mode: FabricEvidenceMode = "ontology_graph"

    def require_cloud_target(self) -> None:
        fields = {
            "subscriptionId": self.subscription_id,
            "tenantId": self.tenant_id,
            "capacityId": self.capacity_id,
        }
        missing = [name for name, value in fields.items() if UUID(value).int == 0]
        if missing:
            raise ConfigurationError(
                "Replace the offline placeholders in config/demo-profile.json before using cloud services: "
                + ", ".join(missing)
            )

    @classmethod
    def load(cls, path: Path = PROFILE_PATH) -> DemoProfile:
        value = read_object(path)
        for key in ("subscriptionId", "tenantId", "capacityId"):
            UUID(required_text(value, key))
        seed = value.get("seed")
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise ConfigurationError("seed must be an integer")
        currency = required_text(value, "currency")
        if len(currency) != 3 or not currency.isupper() or not currency.isalpha():
            raise ConfigurationError("currency must be a three-letter uppercase code")
        raw_mode = required_text(value, "fabricEvidenceMode")
        if raw_mode == "ontology_graph":
            evidence_mode: FabricEvidenceMode = "ontology_graph"
        elif raw_mode == "native_knowledge_base":
            evidence_mode = "native_knowledge_base"
        else:
            raise ConfigurationError("fabricEvidenceMode must explicitly select ontology_graph or native_knowledge_base")
        return cls(
            required_text(value, "displayName"),
            required_text(value, "supplierName"),
            currency,
            seed,
            date.fromisoformat(required_text(value, "asOfDate")),
            required_text(value, "workspaceName"),
            required_text(value, "resourceGroup"),
            required_text(value, "subscriptionId"),
            required_text(value, "tenantId"),
            required_text(value, "capacityId"),
            required_text(value, "azureRegion"),
            required_text(value, "foundryRegion"),
            evidence_mode,
        )


def load_deployment(path: Path = DEPLOYMENT_PATH, *, require_iq: bool = True) -> dict[str, Any]:
    manifest = read_object(path)
    profile = DemoProfile.load()
    expected = {
        "subscriptionId": profile.subscription_id,
        "tenantId": profile.tenant_id,
        "resourceGroup": profile.resource_group,
        "capacityId": profile.capacity_id,
        "workspaceName": profile.workspace_name,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ConfigurationError(f"Deployment {key} does not match the selected demo profile")
    UUID(required_text(manifest, "workspaceId"))
    items = manifest.get("items")
    azure = manifest.get("azure")
    if not isinstance(items, dict) or not isinstance(azure, dict):
        raise ConfigurationError("Deployment must contain items and azure objects")
    for key in ("lakehouseId", "ontologyId", "graphModelId"):
        UUID(required_text(items, key))
    for key in ("projectEndpoint", "foundryEndpoint", "searchEndpoint"):
        endpoint = urlparse(required_text(azure, key))
        if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password:
            raise ConfigurationError(f"Invalid HTTPS endpoint: {key}")
        suffixes = {
            "projectEndpoint": (".services.ai.azure.com",),
            "foundryEndpoint": (".services.ai.azure.com", ".cognitiveservices.azure.com", ".openai.azure.com"),
            "searchEndpoint": (".search.windows.net",),
        }[key]
        service_name = required_text(azure, "searchName" if key == "searchEndpoint" else "foundryAccountName")
        if endpoint.hostname not in {service_name + suffix for suffix in suffixes} or endpoint.query or endpoint.fragment or endpoint.port not in {None, 443}:
            raise ConfigurationError(f"{key} is not an expected Azure public-cloud endpoint")
    if require_iq:
        if manifest.get("iqConfigured") is not True:
            raise ConfigurationError("IQ configuration and its initial live checks have not completed")
        if manifest.get("fabricEvidenceMode") != profile.fabric_evidence_mode:
            raise ConfigurationError("Fabric evidence mode changed; rerun IQ configuration before using live mode")
        agents = manifest.get("agents")
        bases = manifest.get("knowledgeBases")
        sources = manifest.get("knowledgeSources")
        kinds = manifest.get("knowledgeSourceKinds")
        if not isinstance(agents, dict) or not isinstance(bases, dict) or not isinstance(sources, dict) or not isinstance(kinds, dict):
            raise ConfigurationError("IQ connections are not yet configured")
        for lane in ("fabricIq", "foundryIq", "workIq"):
            agent = agents.get(lane)
            if not isinstance(agent, dict):
                raise ConfigurationError(f"Missing specialist: {lane}")
            required_text(agent, "name")
            required_text(agent, "version")
        required_text(bases, "fabricIq")
        required_text(bases, "foundryIq")
        required_text(sources, "fabricIq")
        required_text(sources, "foundryIq")
        if kinds.get("fabricIq") != "fabricOntology" or kinds.get("foundryIq") != "file":
            raise ConfigurationError("Expected live ontology and authenticated file knowledge sources")
        required_text(manifest, "workIndex")
    return manifest
