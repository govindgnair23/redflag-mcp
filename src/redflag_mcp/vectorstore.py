from __future__ import annotations

from pathlib import Path
from typing import Any

import lancedb  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]

from redflag_mcp.config import EMBEDDING_DIM, VECTORS_DIR
from redflag_mcp.models import RedFlagRecord, RedFlagResult

TABLE_NAME = "red_flags"
LIST_FILTER_FIELDS = (
    "product_types",
    "industry_types",
    "customer_profiles",
    "geographic_footprints",
)
SCALAR_FILTER_FIELDS = ("category", "risk_level")
DISTINCT_FILTER_FIELDS = LIST_FILTER_FIELDS + SCALAR_FILTER_FIELDS


def open_store(path: Path | str = VECTORS_DIR) -> lancedb.db.DBConnection:
    return lancedb.connect(Path(path))


def red_flag_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("description", pa.string()),
            pa.field("product_types", pa.list_(pa.string())),
            pa.field("industry_types", pa.list_(pa.string())),
            pa.field("customer_profiles", pa.list_(pa.string())),
            pa.field("geographic_footprints", pa.list_(pa.string())),
            pa.field("regulatory_source", pa.string()),
            pa.field("risk_level", pa.string()),
            pa.field("category", pa.string()),
            pa.field("simulation_type", pa.string()),
            pa.field("source_url", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
        ]
    )


def get_or_create_table(
    db: lancedb.db.DBConnection,
    table_name: str = TABLE_NAME,
) -> lancedb.table.LanceTable:
    if table_name in _table_names(db):
        return db.open_table(table_name)
    return db.create_table(table_name, schema=red_flag_schema())


def upsert_records(table: lancedb.table.LanceTable, records: list[RedFlagRecord]) -> int:
    if not records:
        return 0
    rows = [record.model_dump() for record in records]
    table.merge_insert("id").when_matched_update_all().when_not_matched_insert_all().execute(
        rows
    )
    return len(rows)


def search(
    table: lancedb.table.LanceTable,
    query_vector: list[float],
    *,
    limit: int = 5,
    product_types: list[str] | None = None,
    industry_types: list[str] | None = None,
    customer_profiles: list[str] | None = None,
    geographic_footprints: list[str] | None = None,
    category: str | None = None,
    risk_level: str | None = None,
) -> list[RedFlagResult]:
    if limit <= 0 or table.count_rows() == 0:
        return []

    filters = {
        "product_types": _clean_list(product_types),
        "industry_types": _clean_list(industry_types),
        "customer_profiles": _clean_list(customer_profiles),
        "geographic_footprints": _clean_list(geographic_footprints),
        "category": category,
        "risk_level": risk_level,
    }
    scalar_where = _scalar_where(category=category, risk_level=risk_level)
    fetch_limit = min(table.count_rows(), max(limit * 8, 50))

    try:
        builder = table.search(query_vector)
        if scalar_where:
            builder = builder.where(scalar_where)
        rows = builder.limit(fetch_limit).to_list()
    except Exception:
        rows = table.search(query_vector).limit(fetch_limit).to_list()

    results: list[RedFlagResult] = []
    for row in rows:
        if not _matches_filters(row, filters):
            continue
        distance = row.get("_distance")
        score = None if distance is None else 1.0 / (1.0 + float(distance))
        results.append(_row_to_record(row).to_result(score=score))
        if len(results) >= limit:
            break
    return results


def get_by_id(table: lancedb.table.LanceTable, red_flag_id: str) -> RedFlagResult | None:
    for row in _all_rows(table):
        if row.get("id") == red_flag_id:
            return _row_to_record(row).to_result()
    return None


def list_distinct_values(table: lancedb.table.LanceTable) -> dict[str, list[str]]:
    values: dict[str, set[str]] = {field: set() for field in DISTINCT_FILTER_FIELDS}
    for row in _all_rows(table):
        for field in LIST_FILTER_FIELDS:
            for value in row.get(field) or []:
                values[field].add(value)
        for field in SCALAR_FILTER_FIELDS:
            value = row.get(field)
            if value:
                values[field].add(value)
    return {field: sorted(field_values) for field, field_values in values.items()}


def _all_rows(table: lancedb.table.LanceTable) -> list[dict[str, Any]]:
    if table.count_rows() == 0:
        return []
    return table.head(table.count_rows()).to_pylist()


def _table_names(db: lancedb.db.DBConnection) -> list[str]:
    result = db.list_tables()
    if isinstance(result, list):
        return result
    return list(result.tables)


def _row_to_record(row: dict[str, Any]) -> RedFlagRecord:
    cleaned = {key: value for key, value in row.items() if not key.startswith("_")}
    return RedFlagRecord(**cleaned)


def _clean_list(values: list[str] | None) -> list[str]:
    return [value for value in values or [] if value]


def _matches_filters(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    for field in LIST_FILTER_FIELDS:
        required = filters[field]
        if required and not set(required).intersection(row.get(field) or []):
            return False
    for field in SCALAR_FILTER_FIELDS:
        required = filters[field]
        if required and row.get(field) != required:
            return False
    return True


def _scalar_where(*, category: str | None, risk_level: str | None) -> str | None:
    conditions = []
    if category:
        conditions.append(f"category = '{_escape_sql_string(category)}'")
    if risk_level:
        conditions.append(f"risk_level = '{_escape_sql_string(risk_level)}'")
    return " AND ".join(conditions) if conditions else None


def _escape_sql_string(value: str) -> str:
    return value.replace("'", "''")
