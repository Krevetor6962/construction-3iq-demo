from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

from construction_iq.cloud import CloudClient, CloudError
from construction_iq.config import DATA_ROOT, load_deployment
from construction_iq.fabric_api import gql_identifier
from construction_iq.schema_contract import SCENARIO_RECORD_COLUMNS

PROPERTY_MAP = SCENARIO_RECORD_COLUMNS
REQUIRED_FIELDS = (
    "recordId", "commitmentId", "businessRiskId", "accountId", "accountName",
    "projectName", "productId", "productName", "productFamilyId", "unit", "currency",
    "orderedQty", "availableQty", "allocatedQty", "shortageQty", "unitPrice",
    "orderValue", "unfilledValue", "priority", "committedDate", "constraintId",
    "clusterId", "approvalRequired", "anchor",
)
NUMERIC_FIELDS = (
    "orderedQty", "availableQty", "allocatedQty", "shortageQty",
    "unitPrice", "orderValue", "unfilledValue",
)


def validate_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("The demand queue must be a non-empty list")
    seen: set[str] = set()
    commitments: set[str] = set()
    for record in value:
        if not isinstance(record, dict) or any(key not in record for key in REQUIRED_FIELDS):
            raise ValueError("A demand record is missing required fields")
        record_id = record["recordId"]
        if not isinstance(record_id, str) or not record_id or record_id in seen:
            raise ValueError("Demand record IDs must be nonempty and unique")
        seen.add(record_id)
        if record["commitmentId"] in commitments:
            raise ValueError("A commitment must appear exactly once in the demand queue")
        commitments.add(record["commitmentId"])
        for key in NUMERIC_FIELDS:
            number = record[key]
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0:
                raise ValueError(f"Invalid {key} in {record_id}")
        if abs(record["allocatedQty"] + record["shortageQty"] - record["orderedQty"]) > 0.001:
            raise ValueError(f"Allocation arithmetic failed for {record_id}")
        if abs(record["shortageQty"] * record["unitPrice"] - record["unfilledValue"]) > 0.01:
            raise ValueError(f"Unfilled-value arithmetic failed for {record_id}")
        if abs(record["orderedQty"] * record["unitPrice"] - record["orderValue"]) > 0.01:
            raise ValueError(f"Order-value arithmetic failed for {record_id}")
        date.fromisoformat(str(record["committedDate"])[:10])
    return value


def load_queue(mode: str = "live", data_root: Path = DATA_ROOT) -> dict[str, Any]:
    if mode == "offline":
        path = data_root / "scenario-records.json"
        if not path.is_file():
            raise ValueError("Generate the construction dataset before using offline mode")
        records = validate_records(json.loads(path.read_text(encoding="utf-8")))
        return {"source": "offline_synthetic_fixture", "mode": mode, "records": records}
    if mode != "live":
        raise ValueError("mode must be live or offline")
    return query_live_records(load_deployment())


def query_live_records(deployment: dict[str, Any], anchor_record_id: str | None = None) -> dict[str, Any]:
    match = "MATCH (d:`DemandRecord`)"
    stock_projection = ""
    if anchor_record_id is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", anchor_record_id):
            raise ValueError("Expected a schema-controlled record ID")
        match = (
            "MATCH (selected:`DemandRecord`)-[:`from_inventory`]->(stock:`InventoryPosition`)"
            f" WHERE selected.`record_id` = '{anchor_record_id}'"
            " MATCH (d:`DemandRecord`)-[:`from_inventory`]->(stock)"
        )
        stock_projection = (
            ", stock.`available_qty` AS `stockAvailableQty`"
            ", stock.`inventory_position_id` AS `stockInventoryPositionId`"
        )
    query = (
        match + " RETURN "
        + ", ".join(f"d.{gql_identifier(column)} AS {gql_identifier(key)}" for key, column in PROPERTY_MAP.items())
        + stock_projection
        + " ORDER BY `anchor` DESC, `recordId` LIMIT 1000"
    )
    result = CloudClient().request(
        "POST",
        f"https://api.fabric.microsoft.com/v1/workspaces/{deployment['workspaceId']}"
        f"/graphModels/{deployment['items']['graphModelId']}/executeQuery?preview=true",
        "https://api.fabric.microsoft.com/.default",
        {"query": query, "preview": True},
    )
    if result.get("status", {}).get("code") != "00000":
        raise CloudError(f"Live graph query failed: {result.get('status')}")
    records = validate_records(result.get("result", {}).get("data"))
    return {
        "source": "fabric_graphmodel", "mode": "live", "records": records, "query": query,
        "workspaceId": deployment["workspaceId"],
        "graphModelId": deployment["items"]["graphModelId"],
    }


def retrieve_ontology_graph(deployment: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    expected = {record["recordId"]: record for record in context["siblings"]}
    result = query_live_records(deployment, context["selected"]["recordId"])
    rows = result["records"]
    if {row["recordId"] for row in rows} != set(expected):
        raise CloudError("Live ontology graph no longer contains the selected stock-pool commitments")
    for row in rows:
        if row.get("stockAvailableQty") != row["availableQty"] or row.get("stockInventoryPositionId") != row.get("inventoryPositionId"):
            raise CloudError("The commitment projection disagrees with its linked inventory entity")
        if any(row[key] != expected[row["recordId"]][key] for key in (*NUMERIC_FIELDS, "unit", "currency", "committedDate")):
            raise CloudError("Stock facts changed while gathering evidence; refresh the queue and run again")
    return {
        "sourceType": "fabric_ontology_graph",
        "nativeKnowledgeBaseUsed": False,
        "workspaceId": deployment["workspaceId"],
        "ontologyId": deployment["items"]["ontologyId"],
        "graphModelId": deployment["items"]["graphModelId"],
        "gql": result["query"],
        "relationshipPath": ["DemandRecord", "from_inventory", "InventoryPosition", "from_inventory", "DemandRecord"],
        "references": [{"id": row["recordId"], "sourceData": row} for row in rows],
        "note": "Live read of the native ontology's generated graph, not a native natural-language KB call.",
    }


def select_context(queue: dict[str, Any], record_id: str) -> dict[str, Any]:
    records = queue["records"]
    selected = next((record for record in records if record["recordId"] == record_id), None)
    if selected is None:
        raise ValueError(f"Unknown demand record: {record_id}")
    siblings = [record for record in records if record["clusterId"] == selected["clusterId"]]
    units = {(record["unit"], record["currency"], record["productId"]) for record in siblings}
    stocks = {record["availableQty"] for record in siblings}
    if len(units) != 1 or len(stocks) != 1:
        raise ValueError("A stock pool must have one product, unit, currency, and stock balance")
    allocated = sum(record["allocatedQty"] for record in siblings)
    available = selected["availableQty"]
    if allocated > available:
        raise ValueError("Proposed allocation exceeds the shared available stock")
    return {
        "selected": selected,
        "siblings": siblings,
        "totals": {
            "orderedQty": sum(record["orderedQty"] for record in siblings),
            "availableQty": available,
            "allocatedQty": allocated,
            "shortageQty": sum(record["shortageQty"] for record in siblings),
            "orderValue": round(sum(record["orderValue"] for record in siblings), 2),
            "unfilledValue": round(sum(record["unfilledValue"] for record in siblings), 2),
            "unit": selected["unit"],
            "currency": selected["currency"],
        },
        "queueSource": queue["source"],
    }
