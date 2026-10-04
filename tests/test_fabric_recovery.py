import importlib.util
from unittest.mock import MagicMock, patch

import pytest

from construction_iq.config import ROOT, DemoProfile
from construction_iq.fabric_api import FabricApiError, FabricRestClient, HttpResponse, gql_identifier, kql_connection, load_partial_deployment, merge_deployment


def test_documented_regional_fabric_lro_host_is_allowed():
    location = "https://wabi-west-us3-a-primary-redirect.analysis.windows.net/v1/operations/operation-id"
    assert FabricRestClient._url(location) == location


@pytest.mark.parametrize("location", [
    "https://wabi-west-us3-a-primary-redirect.analysis.windows.net.evil.example/v1/operations/id",
    "https://untrusted.analysis.windows.net/v1/operations/id",
    "https://user@api.fabric.microsoft.com/v1/operations/id",
    "http://wabi-west-us3-a-primary-redirect.analysis.windows.net/v1/operations/id",
])
def test_operation_host_validation_remains_narrow(location):
    with pytest.raises(FabricApiError):
        FabricRestClient._url(location)


def test_operation_receipt_is_persisted_before_polling_can_fail():
    location = "https://wabi-west-us3-a-primary-redirect.analysis.windows.net/v1/operations/id"
    client = FabricRestClient(token="unit-test-token")
    receipts = []
    with patch.object(client, "raw_request", return_value=HttpResponse(202, {"location": location}, "{}")), \
         patch.object(client, "_poll_lro", side_effect=FabricApiError("temporary connection failure")):
        with pytest.raises(FabricApiError):
            client.request("POST", "/workspaces/id/items", {}, on_accepted=receipts.append)
    assert receipts == [location]


def test_resuming_an_accepted_item_never_posts_another_creation(tmp_path):
    spec = importlib.util.spec_from_file_location("deploy_fabric_recovery_test", ROOT / "scripts" / "deploy_fabric.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profile = DemoProfile.load()
    path = tmp_path / "deployment.json"
    workspace_id = "a803f80f-1595-482e-ac14-0dac1230890a"
    item_id = "7e5adce4-0738-486b-994e-8f7726c99b19"
    location = "https://wabi-west-us3-a-primary-redirect.analysis.windows.net/v1/operations/test"
    merge_deployment({"workspaceId": workspace_id, "pendingItemOperations": {"notebookId": location}}, path, profile)
    client = MagicMock()
    client.wait_operation.return_value = {"id": item_id}
    client.request.return_value = {"id": item_id, "type": "Notebook", "displayName": "ConstructionSupplyIngest"}
    module.ensure_item(client, profile, workspace_id, "notebookId", "ConstructionSupplyIngest", "Notebook", path=path)
    client.wait_operation.assert_called_once_with(location)
    client.list_all.assert_not_called()
    client.request.assert_called_once_with("GET", f"/workspaces/{workspace_id}/items/{item_id}")
    manifest = load_partial_deployment(path, profile)
    assert manifest["items"]["notebookId"] == item_id
    assert manifest["pendingItemOperations"]["notebookId"] is None


def test_kql_connection_uses_the_documented_metadata_shape_without_database_name():
    item_id = "7e5adce4-0738-486b-994e-8f7726c99b19"
    uri = "https://example.kusto.fabric.microsoft.com"
    assert kql_connection({"id": item_id, "properties": {"queryServiceUri": uri}}) == (uri, item_id)
    with pytest.raises(FabricApiError):
        kql_connection({"properties": {"queryServiceUri": uri}, "displayName": "Not an identity"})


def test_reserved_gql_labels_and_properties_are_quoted():
    assert gql_identifier("Product") == "`Product`"
    assert gql_identifier("record_id") == "`record_id`"
    with pytest.raises(FabricApiError):
        gql_identifier("Product` OR true")
