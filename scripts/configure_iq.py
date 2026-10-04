from __future__ import annotations

import argparse
import hashlib
import json
import logging
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition

from construction_iq.cloud import CloudClient, CloudError, credential, retrieve_knowledge
from construction_iq.config import ROOT, DemoProfile, load_deployment
from construction_iq.fabric_api import merge_deployment
from construction_iq.specialists import INSTRUCTIONS
from construction_iq.queue import query_live_records, retrieve_ontology_graph, select_context

LOG = logging.getLogger("configure-iq")
FABRIC_SOURCE = "construction-fabric-ks"
POLICY_SOURCE = "construction-policy-ks"
BASES = {"fabricIq": "construction-fabric-kb", "foundryIq": "construction-policy-kb"}
WORK_INDEX = "construction-work-context"


def persist(manifest: dict[str, Any]) -> None:
    merge_deployment(manifest)


def upload_policies(client: CloudClient, manifest: dict[str, Any]) -> int:
    files = sorted((ROOT / "knowledge" / "policies").glob("*.md"))
    if len(files) != 8:
        raise ValueError("Generate the eight synthetic policy documents before deployment")
    endpoint = manifest["azure"]["searchEndpoint"]
    listing = client.search(endpoint, f"knowledgesources/{POLICY_SOURCE}/files", method="GET")
    existing_files = listing.get("value")
    if not isinstance(existing_files, list):
        raise CloudError("File knowledge source returned no file-list array")
    receipts = manifest.setdefault("policyFiles", {})
    for path in files:
        existing = [item for item in existing_files if item.get("fileName") == path.name]
        if len(existing) > 1:
            raise CloudError(f"Multiple files named {path.name} exist in the owned knowledge source; refusing ambiguous replacement")
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        receipt = receipts.get(path.name, {})
        if existing and receipt.get("sha256") == digest and receipt.get("fileId") == existing[0].get("fileId") and not existing[0].get("errorMessage"):
            continue
        uploaded = client.upload_search_file(
            endpoint, POLICY_SOURCE, path.name, content,
            file_id=existing[0]["fileId"] if existing else None,
        )
        if not uploaded.get("fileId") or uploaded.get("errorMessage"):
            raise CloudError(f"Policy ingestion did not succeed: {json.dumps(uploaded)}")
        receipts[path.name] = {"fileId": uploaded["fileId"], "sha256": digest, "bytes": len(content)}
        persist(manifest)
        LOG.info("Ingested authenticated synthetic policy file %s", path.name)
    actual = client.search(endpoint, f"knowledgesources/{POLICY_SOURCE}/files", method="GET").get("value", [])
    if {item.get("fileName") for item in actual} != {path.name for path in files} or any(item.get("errorMessage") for item in actual):
        raise CloudError("The managed file source does not contain exactly the eight successfully ingested policies")
    return len(files)


def openai_model(azure: dict[str, Any], key: str) -> dict[str, Any]:
    deployment = azure[key]
    return {
        "kind": "azureOpenAI",
        "azureOpenAIParameters": {
            "resourceUri": azure["foundryEndpoint"].rstrip("/"),
            "deploymentId": deployment,
            "modelName": deployment,
        },
    }


def create_knowledge_base(client: CloudClient, manifest: dict[str, Any], lane: str, source_name: str, source_kind: str) -> None:
    client.search(manifest["azure"]["searchEndpoint"], f"knowledgebases/{BASES[lane]}", {
        "name": BASES[lane],
        "description": f"Isolated construction demo {lane} knowledge base.",
        "knowledgeSources": [{"name": source_name}],
        "models": [openai_model(manifest["azure"], "chatDeployment")],
        "retrievalReasoningEffort": {"kind": "low"},
        "outputMode": "answerSynthesis",
        "answerInstructions": (
            "Use only source evidence and cite its identifiers. All construction business data is synthetic. "
            "Never approve an allocation, substitute, delivery promise, or external communication."
        ),
    }, method="PUT")
    manifest.setdefault("knowledgeBases", {})[lane] = BASES[lane]
    manifest.setdefault("knowledgeSources", {})[lane] = source_name
    manifest.setdefault("knowledgeSourceKinds", {})[lane] = source_kind
    persist(manifest)


def create_fabric_knowledge(client: CloudClient, manifest: dict[str, Any]) -> None:
    azure = manifest["azure"]
    endpoint = azure["searchEndpoint"]
    client.search(endpoint, f"knowledgesources/{FABRIC_SOURCE}", {
        "name": FABRIC_SOURCE,
        "kind": "fabricOntology",
        "description": "Live construction supplier ontology; delegated user permissions required.",
        "fabricOntologyParameters": {
            "workspaceId": manifest["workspaceId"],
            "ontologyId": manifest["items"]["ontologyId"],
        },
    }, method="PUT")
    create_knowledge_base(client, manifest, "fabricIq", FABRIC_SOURCE, "fabricOntology")


def create_policy_knowledge(client: CloudClient, manifest: dict[str, Any]) -> None:
    azure = manifest["azure"]
    client.search(azure["searchEndpoint"], f"knowledgesources/{POLICY_SOURCE}", {
        "name": POLICY_SOURCE,
        "kind": "file",
        "description": "Eight synthetic construction supplier policies; no customer documents.",
        "fileParameters": {
            "ingestionParameters": {
                "contentExtractionMode": "minimal",
                "embeddingModel": openai_model(azure, "embeddingDeployment"),
            },
        },
    }, method="PUT")
    create_knowledge_base(client, manifest, "foundryIq", POLICY_SOURCE, "file")


def create_work_index(client: CloudClient, manifest: dict[str, Any]) -> None:
    endpoint = manifest["azure"]["searchEndpoint"]
    fields = [
        {"name": "id", "type": "Edm.String", "key": True, "filterable": True},
        {"name": "recordId", "type": "Edm.String", "filterable": True},
        {"name": "accountId", "type": "Edm.String", "filterable": True},
        {"name": "sourceType", "type": "Edm.String", "filterable": True},
        {"name": "title", "type": "Edm.String", "searchable": True},
        {"name": "content", "type": "Edm.String", "searchable": True},
        {"name": "owner", "type": "Edm.String", "searchable": True},
        {"name": "approvalOwner", "type": "Edm.String", "searchable": True},
    ]
    client.search(endpoint, f"indexes/{WORK_INDEX}", {"name": WORK_INDEX, "fields": fields}, method="PUT")
    documents = json.loads((ROOT / "knowledge" / "work-context" / "search-documents.json").read_text(encoding="utf-8"))
    allowed = {field["name"] for field in fields}
    if not isinstance(documents, list) or len(documents) < 200:
        raise ValueError("Expected synthetic collaboration context for every commitment")
    for document in documents:
        if document.get("sourceType") != "synthetic" or not allowed.issubset(document):
            raise ValueError("Collaboration document violates the explicitly synthetic index contract")
    for start in range(0, len(documents), 100):
        batch = [{"@search.action": "mergeOrUpload", **{key: document[key] for key in allowed}} for document in documents[start:start + 100]]
        result = client.search(endpoint, f"indexes/{WORK_INDEX}/docs/index", {"value": batch})
        results = result.get("value", [])
        if len(results) != len(batch) or any(not item.get("status") for item in results):
            raise CloudError(f"Collaboration indexing failed: {json.dumps(results)[:1000]}")
    manifest["workIndex"] = WORK_INDEX
    persist(manifest)


def create_agents(manifest: dict[str, Any]) -> None:
    azure = manifest["azure"]
    agents = manifest.setdefault("agents", {})
    with AIProjectClient(endpoint=azure["projectEndpoint"], credential=credential()) as project:
        for lane, instructions in INSTRUCTIONS.items():
            if lane == "fabricIq":
                instructions += (
                    "\nThis environment explicitly uses live ontology-generated graph retrieval. "
                    "Do not claim the native ontology natural-language knowledge base executed."
                    if manifest["fabricEvidenceMode"] == "ontology_graph"
                    else "\nThis environment uses the native ontology knowledge base."
                )
            name = f"construction-{lane.lower()}-specialist"
            tool = FunctionTool(
                name="retrieve_evidence",
                description="Retrieve scoped, cited evidence for the selected construction commitments. Read-only.",
                parameters={
                    "type": "object", "properties": {"question": {"type": "string"}},
                    "required": ["question"], "additionalProperties": False,
                },
                strict=True,
            )
            definition = PromptAgentDefinition(
                model=azure["chatDeployment"], instructions=instructions, tools=[tool],
            )
            signature = hashlib.sha256(json.dumps(definition.as_dict(), sort_keys=True).encode()).hexdigest()
            existing = agents.get(lane)
            if existing and existing.get("definitionHash") == signature:
                version = project.agents.get_version(agent_name=existing["name"], agent_version=existing["version"])
                if version.metadata and version.metadata.get("definitionHash") == signature:
                    LOG.info("Reusing specialist %s version %s", existing["name"], existing["version"])
                    continue
                raise CloudError(f"Remote definition metadata differs from the recorded agent {name}")
            created = project.agents.create_version(
                agent_name=name, definition=definition, draft=False,
                description="Synthetic construction demo; client-side read-only evidence tool.",
                metadata={"demo": "construction-three-iq", "definitionHash": signature},
            )
            agents[lane] = {"name": created.name, "version": str(created.version), "definitionHash": signature}
            persist(manifest)
            LOG.info("Created specialist %s version %s", created.name, created.version)


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure only the new deployment's IQ knowledge and specialists.")
    parser.add_argument("--approve", action="store_true", help="Required confirmation after the separate cloud deployment approval.")
    args = parser.parse_args()
    if not args.approve:
        parser.error("This mutates new cloud resources. Obtain deployment approval, then pass --approve.")
    manifest = load_deployment(require_iq=False)
    profile = DemoProfile.load()
    if manifest["resourceGroup"] != profile.resource_group:
        raise ValueError("Wrong deployment target")
    manifest["iqConfigured"] = False
    manifest["fabricEvidenceMode"] = profile.fabric_evidence_mode
    persist(manifest)
    client = CloudClient()
    create_policy_knowledge(client, manifest)
    upload_policies(client, manifest)
    create_fabric_knowledge(client, manifest)
    create_work_index(client, manifest)
    if profile.fabric_evidence_mode == "native_knowledge_base":
        retrieve_knowledge(client, manifest, "fabricIq", "List the commitments sharing the constrained insulation stock and their ordered and allocated quantities.")
        manifest["nativeOntologyKnowledgeBaseStatus"] = "verified"
    else:
        queue = query_live_records(manifest)
        context = select_context(queue, queue["records"][0]["recordId"])
        retrieve_ontology_graph(manifest, context)
        manifest["nativeOntologyKnowledgeBaseStatus"] = "not_used"
    retrieve_knowledge(client, manifest, "foundryIq", "What approval is required before promising a constrained delivery quantity?")
    create_agents(manifest)
    manifest["iqConfigured"] = True
    manifest["acceptanceVerified"] = False
    persist(manifest)
    LOG.info("IQ configured; end-to-end acceptance is still required.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    raise SystemExit(main())
