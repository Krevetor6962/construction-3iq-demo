from copy import deepcopy
from unittest.mock import patch

import pytest

from construction_iq.cloud import CloudError
from construction_iq.queue import load_queue, query_live_records, retrieve_ontology_graph, select_context


def test_graph_query_traverses_stock_relations_instead_of_trusting_a_client_peer_list():
    manifest = {"workspaceId": "workspace", "items": {"graphModelId": "graph"}}
    rows = load_queue("offline")["records"][:3]
    with patch("construction_iq.queue.CloudClient") as client:
        client.return_value.request.return_value = {"status": {"code": "00000"}, "result": {"data": rows}}
        result = query_live_records(manifest, "REC-CON-0001")
    assert "[:`from_inventory`]->(stock:`InventoryPosition`)" in result["query"]
    assert "MATCH (d:`DemandRecord`)-[:`from_inventory`]->(stock)" in result["query"]
    assert "stock.`available_qty` AS `stockAvailableQty`" in result["query"]


def test_graph_tool_rejects_inventory_projection_drift():
    context = select_context(load_queue("offline"), "REC-CON-0001")
    rows = deepcopy(context["siblings"])
    for row in rows:
        row["stockAvailableQty"] = row["availableQty"]
        row["stockInventoryPositionId"] = row["inventoryPositionId"]
    rows[0]["stockAvailableQty"] -= 1
    with patch("construction_iq.queue.query_live_records", return_value={"records": rows, "query": "live-query"}):
        with pytest.raises(CloudError, match="linked inventory entity"):
            retrieve_ontology_graph({}, context)


def test_graph_tool_rejects_new_or_missing_peer_commitments():
    context = select_context(load_queue("offline"), "REC-CON-0001")
    with patch("construction_iq.queue.query_live_records", return_value={"records": context["siblings"][:2], "query": "live-query"}):
        with pytest.raises(CloudError, match="stock-pool commitments"):
            retrieve_ontology_graph({}, context)


def test_invalid_selected_record_cannot_inject_a_graph_query():
    with pytest.raises(ValueError, match="schema-controlled"):
        query_live_records({}, "REC' RETURN true //")
