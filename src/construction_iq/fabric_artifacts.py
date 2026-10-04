from __future__ import annotations

import base64
import csv
import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from construction_iq.config import DATA_ROOT, ROOT
from construction_iq.fabric_api import FabricApiError
from construction_iq.schema_contract import ALL_TABLES, ColumnSpec, TableSpec

FABRIC_LAKEHOUSE_NAME = "ConstructionSupplyLakehouse"
FABRIC_EVENTHOUSE_NAME = "ConstructionSupplyEventhouse"
FABRIC_KQL_DATABASE_NAME = "ConstructionSupplyEvents"
FABRIC_ONTOLOGY_NAME = "ConstructionSupplyOntology"
FABRIC_INGEST_NOTEBOOK_NAME = "ConstructionSupplyIngest"
FABRIC_LAKEHOUSE_SCHEMA = "dbo"
ONTOLOGY_SOURCE = ROOT / "ontology" / "construction" / "graph-model" / "construction-ontology.json"
REMOTE_DATA_ROOT = "Files/construction_synthetic"
INGEST_RECEIPT_PATH = f"{REMOTE_DATA_ROOT}/ingest-validation.json"
TABLE_BY_NAME = {table.name: table for table in ALL_TABLES}
KEY_ONTOLOGY_PATH = (
    "UnifiedProfile", "Audience", "Activation", "Campaign", "DemandSignal",
    "ProductFamily", "Product", "SupplyConstraint", "CustomerCommitment", "BusinessRisk",
)


@dataclass(frozen=True)
class RelationshipBinding:
    source_label: str
    edge_label: str
    target_label: str
    table_name: str
    source_column: str
    target_column: str


def source_model(path: Path = ONTOLOGY_SOURCE) -> tuple[dict[str, TableSpec], dict[str, str], tuple[RelationshipBinding, ...]]:
    graph = json.loads(path.read_text(encoding="utf-8"))
    entities: dict[str, TableSpec] = {}
    keys: dict[str, str] = {}
    for node in graph["nodeLabels"]:
        label, key = node["label"], node["idProperty"]
        if label in entities or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", label):
            raise FabricApiError(f"Invalid or duplicated ontology label {label!r}.")
        candidates = [
            table for table in ALL_TABLES
            if next((column.name for column in table.columns if column.name.endswith("_id")), None) == key
        ]
        if len(candidates) != 1:
            raise FabricApiError(f"Ontology label {label} must resolve to exactly one primary-key table.")
        entities[label], keys[label] = candidates[0], key
    bindings: list[RelationshipBinding] = []
    seen: set[tuple[str, str, str]] = set()
    for source, edge, target in graph["directedEdges"]:
        if (source, edge, target) in seen or not re.fullmatch(r"[a-z][a-z0-9_]*", edge):
            raise FabricApiError(f"Invalid or duplicate relationship {source}/{edge}/{target}.")
        seen.add((source, edge, target))
        if source not in entities or target not in entities:
            raise FabricApiError(f"Relationship {source}/{edge}/{target} references an unknown entity.")
        source_key, target_key = keys[source], keys[target]
        required_keys = {source_key, target_key}
        candidates = [
            table for table in (entities[target], entities[source])
            if required_keys <= {column.name for column in table.columns}
        ]
        # These relationships use junction facts, not the denormalized demand-record read model.
        bridge = {
            ("SupplyConstraint", "exposes_commitment", "CustomerCommitment"): "business_risks",
            ("UnifiedProfile", "member_of_audience", "Audience"): "audience_memberships",
        }.get((source, edge, target))
        if candidates:
            selected = candidates[0]
        elif bridge and bridge in TABLE_BY_NAME:
            selected = TABLE_BY_NAME[bridge]
        else:
            raise FabricApiError(f"No direct entity table or explicit junction binding for {source}/{edge}/{target}.")
        if not required_keys <= {column.name for column in selected.columns}:
            raise FabricApiError(f"Relationship {edge} references missing columns in {selected.name}.")
        bindings.append(RelationshipBinding(source, edge, target, selected.name, source_key, target_key))
    if set(table.name for table in entities.values()) != set(TABLE_BY_NAME):
        raise FabricApiError("Every dataset table must have one ontology entity, including static event-table mirrors.")
    return entities, keys, tuple(bindings)


def key_path_edges_present() -> dict[str, Any]:
    _, _, bindings = source_model()
    edges = {(binding.source_label, binding.target_label) for binding in bindings}
    missing = [f"{a}->{b}" for a, b in zip(KEY_ONTOLOGY_PATH, KEY_ONTOLOGY_PATH[1:]) if (a, b) not in edges and (b, a) not in edges]
    return {"complete": not missing, "path": list(KEY_ONTOLOGY_PATH), "missing_edges": missing}


def _stable_id(key: str) -> str:
    # Native ontology IDs must fit in JavaScript's safe 53-bit integer range.
    return str((int.from_bytes(hashlib.sha256(("construction3iq:" + key).encode()).digest()[:8], "big") & 0x1FFFFFFFFFFFFF) or 1)


def _stable_uuid(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "https://construction.example/ontology/" + key))


def _part(path: str, value: dict[str, Any]) -> dict[str, str]:
    return {"path": path, "payload": base64.b64encode(json.dumps(value, separators=(",", ":")).encode()).decode(), "payloadType": "InlineBase64"}


def ontology_type(column: ColumnSpec) -> str:
    return {"bool": "Boolean", "utc_timestamp": "DateTime", "date": "DateTime", "double": "Double", "decimal": "Double", "int": "BigInt"}.get(column.column_type, "String")


def ontology_definition(workspace_id: str, lakehouse_id: str) -> dict[str, Any]:
    uuid.UUID(workspace_id)
    uuid.UUID(lakehouse_id)
    entities, keys, bindings = source_model()
    parts = [_part("definition.json", {}), _part(".platform", {"metadata": {"type": "Ontology", "displayName": FABRIC_ONTOLOGY_NAME}})]
    for label, table in entities.items():
        entity_id = _stable_id("entity:" + label)
        property_id = lambda name: _stable_id(f"property:{label}:{name}")
        definition = {
            "id": entity_id, "namespace": "usertypes", "baseEntityTypeId": None, "name": label,
            "entityIdParts": [property_id(keys[label])], "displayNamePropertyId": property_id(keys[label]),
            "namespaceType": "Custom", "visibility": "Visible", "timeseriesProperties": [],
            "properties": [{"id": property_id(column.name), "name": column.name, "redefines": None,
                            "baseTypeNamespaceType": None, "valueType": ontology_type(column)} for column in table.columns],
        }
        binding_id = _stable_uuid("entity-binding:" + label)
        parts.extend([
            _part(f"EntityTypes/{entity_id}/definition.json", definition),
            _part(f"EntityTypes/{entity_id}/DataBindings/{binding_id}.json", {
                "id": binding_id,
                "dataBindingConfiguration": {
                    "dataBindingType": "NonTimeSeries",
                    "propertyBindings": [{"sourceColumnName": column.name, "targetPropertyId": property_id(column.name)} for column in table.columns],
                    "sourceTableProperties": {"sourceType": "LakehouseTable", "workspaceId": workspace_id,
                                              "itemId": lakehouse_id, "sourceTableName": table.name, "sourceSchema": FABRIC_LAKEHOUSE_SCHEMA},
                },
            }),
        ])
    for binding in bindings:
        alias = f"{binding.source_label}:{binding.edge_label}:{binding.target_label}"
        relationship_id = _stable_id("relationship:" + alias)
        context_id = _stable_uuid("relationship-context:" + alias)
        parts.extend([
            _part(f"RelationshipTypes/{relationship_id}/definition.json", {
                "namespace": "usertypes", "id": relationship_id, "name": binding.edge_label, "namespaceType": "Custom",
                "source": {"entityTypeId": _stable_id("entity:" + binding.source_label)},
                "target": {"entityTypeId": _stable_id("entity:" + binding.target_label)},
            }),
            _part(f"RelationshipTypes/{relationship_id}/Contextualizations/{context_id}.json", {
                "id": context_id,
                "dataBindingTable": {"workspaceId": workspace_id, "itemId": lakehouse_id, "sourceTableName": binding.table_name,
                                     "sourceSchema": FABRIC_LAKEHOUSE_SCHEMA, "sourceType": "LakehouseTable"},
                "sourceKeyRefBindings": [{"sourceColumnName": binding.source_column, "targetPropertyId": _stable_id(f"property:{binding.source_label}:{keys[binding.source_label]}")}],
                "targetKeyRefBindings": [{"sourceColumnName": binding.target_column, "targetPropertyId": _stable_id(f"property:{binding.target_label}:{keys[binding.target_label]}")}],
            }),
        ])
    return {"parts": parts}


def dataset_contract(data_root: Path = DATA_ROOT) -> dict[str, Any]:
    entities, keys, _ = source_model()
    primary_keys = {table.name: keys[label] for label, table in entities.items()}
    tables: list[dict[str, Any]] = []
    for table in ALL_TABLES:
        path = data_root / table.folder / f"{table.name}.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != [column.name for column in table.columns]:
                raise FabricApiError(f"CSV header differs from schema: {path}")
            seen: set[str] = set()
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise FabricApiError(f"Malformed CSV row: {path}")
                for column in table.columns:
                    if not row[column.name] and not column.nullable:
                        raise FabricApiError(f"Null {column.name} in {path}")
                    if row[column.name] and column.enum_values and row[column.name] not in column.enum_values:
                        raise FabricApiError(f"Invalid enum {column.name} in {path}")
                key = row[primary_keys[table.name]]
                if not key or key in seen:
                    raise FabricApiError(f"Empty/duplicate primary key {key!r} in {path}")
                seen.add(key)
        if not seen:
            raise FabricApiError(f"Dataset table is empty: {path}")
        tables.append({
            "name": table.name, "folder": table.folder, "primaryKey": primary_keys[table.name],
            "columns": [asdict(column) for column in table.columns],
            "count": len(seen), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    signature = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    return {"tables": tables, "datasetSignature": signature}


def build_ingest_notebook_definition(workspace_id: str, lakehouse_id: str, contract: dict[str, Any]) -> dict[str, Any]:
    uuid.UUID(workspace_id)
    uuid.UUID(lakehouse_id)
    root = f"abfss://{workspace_id}@onelake.dfs.fabric.microsoft.com/{lakehouse_id}"
    source = f'''import hashlib
import json
import notebookutils
from pyspark.sql import functions as F

contract = json.loads({json.dumps(contract)!r})
root = {root!r}
spark.conf.set("spark.sql.session.timeZone", "UTC")
spark.sql("CREATE SCHEMA IF NOT EXISTS dbo")
types = {{"utc_timestamp": "timestamp", "date": "date", "double": "double", "decimal": "decimal(18,2)", "int": "int", "bool": "boolean", "string": "string", "enum": "string"}}
counts = {{}}
for spec in contract["tables"]:
    path = root + "/{REMOTE_DATA_ROOT}/" + spec["folder"] + "/" + spec["name"] + ".csv"
    content = spark.read.format("binaryFile").load(path).select("content").first()[0]
    if hashlib.sha256(content).hexdigest() != spec["sha256"]:
        raise ValueError("Uploaded CSV digest mismatch: " + spec["name"])
    raw = spark.read.option("header", "true").option("mode", "FAILFAST").csv(path)
    if raw.columns != [column["name"] for column in spec["columns"]]:
        raise ValueError("CSV schema mismatch: " + spec["name"])
    typed = raw
    for column in spec["columns"]:
        name = column["name"]
        converted = F.col(name).cast(types[column["column_type"]])
        if raw.filter(F.col(name).isNotNull() & converted.isNull()).limit(1).count():
            raise ValueError("Invalid type: " + spec["name"] + "." + name)
        typed = typed.withColumn(name, converted)
        if not column["nullable"] and typed.filter(F.col(name).isNull()).limit(1).count():
            raise ValueError("Required value missing: " + spec["name"] + "." + name)
        if column["enum_values"] and typed.filter(~F.col(name).isin(column["enum_values"])).limit(1).count():
            raise ValueError("Invalid enum: " + spec["name"] + "." + name)
    count = typed.count()
    if count != spec["count"] or typed.select(spec["primaryKey"]).distinct().count() != count:
        raise ValueError("Row count / primary-key mismatch: " + spec["name"])
    target = "dbo." + spec["name"]
    typed.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(target)
    persisted = spark.table(target)
    if persisted.count() != count or persisted.schema != typed.schema:
        raise ValueError("Persisted Delta schema/count mismatch: " + target)
    counts[spec["name"]] = count
receipt = {{"datasetSignature": contract["datasetSignature"], "counts": counts, "schemaValidated": True}}
notebookutils.fs.put(root + "/{INGEST_RECEIPT_PATH}", json.dumps(receipt, sort_keys=True), True)
print(json.dumps(receipt, sort_keys=True))
'''
    notebook = {
        "cells": [{"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": source.splitlines(keepends=True)}],
        "metadata": {
            "language_info": {"name": "python"},
            "dependencies": {"lakehouse": {"default_lakehouse": lakehouse_id, "default_lakehouse_workspace_id": workspace_id, "default_lakehouse_name": FABRIC_LAKEHOUSE_NAME}},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }
    return {"format": "ipynb", "parts": [_part("notebook-content.ipynb", notebook)]}


def kql_type(column: ColumnSpec) -> str:
    return {"utc_timestamp": "datetime", "date": "datetime", "int": "int", "double": "real", "decimal": "decimal", "bool": "bool"}.get(column.column_type, "string")


def eventhouse_replace_command(table: TableSpec, data_root: Path) -> str:
    columns = ", ".join(f"{column.name}:{kql_type(column)}" for column in table.columns)
    values: list[str] = []
    with (data_root / table.folder / f"{table.name}.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            for column in table.columns:
                value, kind = row[column.name], kql_type(column)
                if kind == "string":
                    values.append(json.dumps(value))
                elif not value:
                    if not column.nullable:
                        raise FabricApiError(f"Null {table.name}.{column.name}")
                    values.append(f"{kind}(null)")
                elif kind == "bool":
                    if value.lower() not in {"true", "false"}:
                        raise FabricApiError(f"Invalid Boolean {table.name}.{column.name}")
                    values.append(value.lower())
                else:
                    if not re.fullmatch(r"[0-9eE+.:TZ -]+", value):
                        raise FabricApiError(f"Invalid KQL literal {table.name}.{column.name}")
                    values.append(f"{kind}({value})")
    return f".set-or-replace {table.name} <| datatable({columns})[\n" + ",\n".join(values) + "\n]"
