from __future__ import annotations

import json
import io
import urllib.error
from types import SimpleNamespace
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest
from openai import RateLimitError

from construction_iq.cloud import CloudClient, CloudError, credential, identifier, model_call, retrieve_collaboration, retrieve_knowledge
from construction_iq.specialists import invoke_agent
from construction_iq.config import ConfigurationError, DemoProfile


def deployment() -> dict:
    return {
        "azure": {"searchEndpoint": "https://construction-test.search.windows.net"},
        "knowledgeBases": {"fabricIq": "construction-fabric-kb", "foundryIq": "construction-policy-kb"},
        "knowledgeSources": {"fabricIq": "construction-fabric-ks", "foundryIq": "construction-policy-ks"},
        "knowledgeSourceKinds": {"fabricIq": "fabricOntology", "foundryIq": "file"},
        "workIndex": "construction-work-context",
    }


def test_cli_credential_uses_one_unambiguous_subscription_selector():
    profile = replace(DemoProfile.load(),
        subscription_id="11111111-1111-4111-8111-111111111111",
        tenant_id="22222222-2222-4222-8222-222222222222",
        capacity_id="33333333-3333-4333-8333-333333333333",
    )
    with patch("construction_iq.cloud.DemoProfile.load", return_value=profile), \
         patch("construction_iq.cloud.AzureCliCredential") as constructor:
        credential()
    assert constructor.call_args.kwargs["subscription"]
    assert "tenant_id" not in constructor.call_args.kwargs


def test_offline_placeholders_never_reach_cloud_authentication():
    profile = replace(DemoProfile.load(), subscription_id="00000000-0000-0000-0000-000000000000")
    with patch("construction_iq.cloud.DemoProfile.load", return_value=profile), \
         patch("construction_iq.cloud.AzureCliCredential") as constructor:
        with pytest.raises(ConfigurationError, match="offline placeholders"):
            credential()
    constructor.assert_not_called()


def test_model_rate_limit_waits_for_a_token_window_then_returns_a_real_response():
    response = MagicMock(status_code=429, headers={})
    error = RateLimitError("token rate limit", response=response, body={})
    operation = MagicMock(side_effect=[error, "real-response"])
    with patch("construction_iq.cloud.time.sleep") as sleep:
        assert model_call(operation) == "real-response"
    sleep.assert_called_once_with(60.0)
    assert operation.call_count == 2


def test_model_rate_limit_honors_retry_hint_and_remains_bounded():
    response = MagicMock(status_code=429, headers={"retry-after-ms": "2500"})
    error = RateLimitError("token rate limit", response=response, body={})
    operation = MagicMock(side_effect=error)
    with patch("construction_iq.cloud.time.sleep") as sleep:
        with pytest.raises(RateLimitError):
            model_call(operation)
    assert operation.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [2.5, 2.5]


def test_model_retry_does_not_hide_other_errors():
    operation = MagicMock(side_effect=RuntimeError("invalid agent definition"))
    with patch("construction_iq.cloud.time.sleep") as sleep:
        with pytest.raises(RuntimeError, match="invalid agent"):
            model_call(operation)
    sleep.assert_not_called()


def test_paused_capacity_is_an_explicit_error_without_retry_or_fallback():
    with patch("construction_iq.cloud.credential") as auth:
        auth.return_value.get_token.return_value = SimpleNamespace(token="unit-test")
        client = CloudClient()
    opener = MagicMock()
    opener.open.side_effect = urllib.error.HTTPError(
        "https://api.fabric.microsoft.com/v1/test", 404, "inactive", {},
        io.BytesIO(b'{"errorCode":"CapacityNotActive","message":"capacity inactive"}'),
    )
    with patch("urllib.request.build_opener", return_value=opener), patch("construction_iq.cloud.time.sleep") as sleep:
        with pytest.raises(CloudError, match="paused/inactive"):
            client.request("POST", "https://api.fabric.microsoft.com/v1/test", "https://api.fabric.microsoft.com/.default", {})
    assert opener.open.call_count == 1
    sleep.assert_not_called()


def test_fabric_retrieval_requires_delegation_and_citations():
    client = MagicMock()
    client.search.return_value = {"references": [{"id": "1", "sourceData": {"fabricRawData": "rows"}}]}
    result = retrieve_knowledge(client, deployment(), "fabricIq", "Who shares stock?")
    assert result["references"]
    assert client.search.call_args.kwargs["delegated"] is True
    assert "construction-fabric-kb" in client.search.call_args.args[1]
    source_params = client.search.call_args.args[2]["knowledgeSourceParams"][0]
    assert source_params["kind"] == "fabricOntology"
    assert source_params["includeReferenceSourceData"] is True
    assert source_params["failOnError"] is True
    client.search.return_value = {"references": []}
    with pytest.raises(CloudError, match="no cited knowledge"):
        retrieve_knowledge(client, deployment(), "fabricIq", "Question")


def test_policy_retrieval_is_not_falsely_claimed_as_delegated_fabric():
    client = MagicMock()
    client.search.return_value = {"references": [{"id": "policy-1"}]}
    retrieve_knowledge(client, deployment(), "foundryIq", "What is permitted?")
    assert client.search.call_args.kwargs["delegated"] is False
    assert client.search.call_args.args[2]["knowledgeSourceParams"][0]["kind"] == "file"


def test_collaboration_is_scoped_and_explicitly_synthetic():
    client = MagicMock()
    client.search.return_value = {"value": [{"id": "note-1"}]}
    result = retrieve_collaboration(client, deployment(), ["C-1", "C-'2"])
    sent = client.search.call_args.args[2]
    assert "recordId eq 'C-1'" in sent["filter"]
    assert "recordId eq 'C-''2'" in sent["filter"]
    assert "sourceType eq 'synthetic'" in sent["filter"]
    assert result["isLiveMicrosoft365"] is False


def test_delegated_header_is_fresh_not_part_of_payload_or_response():
    with patch("construction_iq.cloud.credential") as get_credential:
        get_credential.return_value.get_token.return_value = SimpleNamespace(token="unit-test-token")
        client = CloudClient()
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"references":[{"id":"1"}]}'
    opener = MagicMock()
    opener.open.return_value = response
    with patch("urllib.request.build_opener", return_value=opener):
        result = client.search(
            "https://construction-test.search.windows.net",
            "knowledgebases/construction-fabric-kb/retrieve",
            {"messages": []}, delegated=True,
        )
    request = opener.open.call_args.args[0]
    headers = {name.lower(): value for name, value in request.header_items()}
    assert headers["authorization"] == "Bearer unit-test-token"
    assert headers["x-ms-query-source-authorization"] == "unit-test-token"
    assert b"unit-test-token" not in request.data
    assert "unit-test-token" not in json.dumps(result)


def test_tokens_are_not_requested_for_non_azure_destinations():
    with patch("construction_iq.cloud.credential") as get_credential:
        client = CloudClient()
    with pytest.raises(ValueError, match="only sends tokens"):
        client.request("GET", "https://example.com/", "https://search.azure.com/.default")
    get_credential.return_value.get_token.assert_not_called()


@pytest.mark.parametrize("value", ["../another", "name?api-key=x", "", "quote'name"])
def test_cloud_identifiers_cannot_change_the_target(value):
    with pytest.raises(ValueError):
        identifier(value)


def test_foundry_function_loop_returns_actual_retrieval_evidence():
    function_call = SimpleNamespace(
        type="function_call", name="retrieve_evidence",
        arguments='{"question":"Who shares this stock?"}', call_id="call-1",
    )
    initial = SimpleNamespace(output=[function_call], output_text="", id="response-1")
    completed = SimpleNamespace(output=[], output_text="Cited grounded answer [policy-1].", id="response-2")
    project = MagicMock()
    project.__enter__.return_value = project
    client = project.get_openai_client.return_value.__enter__.return_value
    client.conversations.create.return_value = SimpleNamespace(id="conversation-1")
    client.responses.create.side_effect = [initial, completed]
    retrieve = MagicMock(return_value={"references": [{"id": "policy-1"}]})
    with patch("construction_iq.specialists.AIProjectClient", return_value=project), \
         patch("construction_iq.specialists.credential"):
        answer, response_id = invoke_agent(
            "https://example.services.ai.azure.com/api/projects/demo",
            "construction-foundryiq-specialist", "1", "Protect commitments", retrieve,
        )
    assert answer == completed.output_text
    assert response_id == "response-2"
    retrieve.assert_called_once_with("Who shares this stock?")
    followup = client.responses.create.call_args_list[1].kwargs
    assert json.loads(followup["input"][0]["output"])["references"][0]["id"] == "policy-1"
    assert followup["extra_body"]["agent_reference"]["version"] == "1"
    client.conversations.delete.assert_called_once_with(conversation_id="conversation-1")


def test_unsupported_agent_tool_cannot_execute_external_actions():
    project = MagicMock()
    project.__enter__.return_value = project
    client = project.get_openai_client.return_value.__enter__.return_value
    client.conversations.create.return_value = SimpleNamespace(id="conversation-1")
    client.responses.create.return_value = SimpleNamespace(
        output=[SimpleNamespace(type="function_call", name="send_email")], output_text="", id="response-1",
    )
    with patch("construction_iq.specialists.AIProjectClient", return_value=project), \
         patch("construction_iq.specialists.credential"):
        with pytest.raises(CloudError, match="unsupported tool"):
            invoke_agent(
                "https://example.services.ai.azure.com/api/projects/demo",
                "construction-workiq-specialist", "1", "Send this", MagicMock(),
            )
