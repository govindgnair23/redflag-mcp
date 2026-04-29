from __future__ import annotations

import heapq
import hashlib
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

import lancedb  # type: ignore[import-untyped]
import pyarrow as pa  # type: ignore[import-untyped]

from redflag_mcp.config import EMBEDDING_DIM, VECTORS_DIR
from redflag_mcp.models import (
    RedFlagRecord,
    RedFlagResult,
    RedFlagSourceDetail,
    RedFlagSourceSummary,
    SourceRedFlagSnippet,
)

TABLE_NAME = "red_flags"
SOURCE_DETAIL_SNIPPET_LIMIT = 10
LIST_FILTER_FIELDS = (
    "product_types",
    "industry_types",
    "customer_profiles",
    "geographic_footprints",
    "typology_family",
    "transaction_patterns",
)
SCALAR_FILTER_FIELDS = ("category", "risk_level")
DISTINCT_FILTER_FIELDS = LIST_FILTER_FIELDS + SCALAR_FILTER_FIELDS
RISK_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class RedFlagFilters:
    product_types: list[str] | None = None
    industry_types: list[str] | None = None
    customer_profiles: list[str] | None = None
    geographic_footprints: list[str] | None = None
    typology_family: list[str] | None = None
    transaction_patterns: list[str] | None = None
    category: str | None = None
    risk_level: str | None = None
    regulatory_source: str | None = None
    source_url: str | None = None
    source_id: str | None = None

    def has_any(self) -> bool:
        return any(
            _clean_list(getattr(self, field_name)) for field_name in LIST_FILTER_FIELDS
        ) or any(
            getattr(self, field_name)
            for field_name in (
                *SCALAR_FILTER_FIELDS,
                "regulatory_source",
                "source_url",
                "source_id",
            )
        )


@dataclass
class _SourceGroup:
    source_id: str
    regulatory_source: str
    source_url: str | None
    rows: list[dict[str, Any]] = dataclass_field(default_factory=list)

    def add(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        if self.source_url is None and row.get("source_url"):
            self.source_url = row["source_url"]
        if self.regulatory_source == "Unknown source" and row.get("regulatory_source"):
            self.regulatory_source = row["regulatory_source"]


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
            pa.field("typology_family", pa.list_(pa.string())),
            pa.field("transaction_patterns", pa.list_(pa.string())),
            pa.field("key_terms", pa.list_(pa.string())),
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


def upsert_records(
    table: lancedb.table.LanceTable, records: list[RedFlagRecord]
) -> int:
    if not records:
        return 0
    rows = [record.model_dump() for record in records]
    table.merge_insert(
        "id"
    ).when_matched_update_all().when_not_matched_insert_all().execute(rows)
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

    filters = RedFlagFilters(
        product_types=product_types,
        industry_types=industry_types,
        customer_profiles=customer_profiles,
        geographic_footprints=geographic_footprints,
        category=category,
        risk_level=risk_level,
    )
    scalar_where = _scalar_where(
        category=filters.category, risk_level=filters.risk_level
    )
    row_count = table.count_rows()
    fetch_limit = (
        row_count
        if _has_list_filters(filters)
        else min(row_count, max(limit * 8, 50))
    )

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


def filter_red_flags(
    table: lancedb.table.LanceTable,
    *,
    limit: int = 20,
    filters: RedFlagFilters | None = None,
) -> list[RedFlagResult]:
    if limit <= 0 or table.count_rows() == 0:
        return []

    filters = filters or RedFlagFilters()
    matching_rows = (
        row
        for row in _all_rows(table)
        if _matches_filters(row, filters)
        and (
            filters.regulatory_source is None
            or row.get("regulatory_source") == filters.regulatory_source
        )
        and (filters.source_url is None or row.get("source_url") == filters.source_url)
        and (filters.source_id is None or _source_id(row) == filters.source_id)
    )
    rows = heapq.nsmallest(limit, matching_rows, key=_metadata_result_sort_key)
    return [_row_to_record(row).to_result() for row in rows]


def get_by_id(
    table: lancedb.table.LanceTable, red_flag_id: str
) -> RedFlagResult | None:
    for row in _all_rows(table):
        if row.get("id") == red_flag_id:
            return _row_to_record(row).to_result()
    return None


def list_sources(table: lancedb.table.LanceTable) -> list[RedFlagSourceSummary]:
    groups = _source_groups(table)
    return [_source_summary(group) for group in groups.values()]


def get_source(
    table: lancedb.table.LanceTable, source_id: str
) -> RedFlagSourceDetail | None:
    group = _source_group(table, source_id)
    if group is None:
        return None

    summary = _source_summary(group)
    rows = sorted(group.rows, key=lambda row: row.get("id") or "")
    return RedFlagSourceDetail(
        **summary.model_dump(),
        industry_types=_sorted_list_values(rows, "industry_types"),
        customer_profiles=_sorted_list_values(rows, "customer_profiles"),
        geographic_footprints=_sorted_list_values(rows, "geographic_footprints"),
        red_flags=[
            SourceRedFlagSnippet(
                id=row["id"],
                description_snippet=_description_snippet(row.get("description") or ""),
                category=row.get("category"),
                risk_level=row.get("risk_level"),
            )
            for row in rows[:SOURCE_DETAIL_SNIPPET_LIMIT]
        ],
    )


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


def _source_groups(table: lancedb.table.LanceTable) -> dict[str, _SourceGroup]:
    groups: dict[str, _SourceGroup] = {}
    for row in _all_rows(table):
        source_id = _source_id(row)
        group = groups.setdefault(source_id, _source_group_for_row(row, source_id))
        group.add(row)
    return dict(sorted(groups.items(), key=lambda item: item[0]))


def _source_group(
    table: lancedb.table.LanceTable, source_id: str
) -> _SourceGroup | None:
    group = None
    for row in _all_rows(table):
        if _source_id(row) != source_id:
            continue
        group = group or _source_group_for_row(row, source_id)
        group.add(row)
    return group


def _source_group_for_row(row: dict[str, Any], source_id: str) -> _SourceGroup:
    return _SourceGroup(
        source_id=source_id,
        regulatory_source=row.get("regulatory_source") or "Unknown source",
        source_url=row.get("source_url"),
    )


def _source_summary(group: _SourceGroup) -> RedFlagSourceSummary:
    rows = sorted(group.rows, key=lambda row: row.get("id") or "")
    return RedFlagSourceSummary(
        source_id=group.source_id,
        regulatory_source=group.regulatory_source,
        source_url=group.source_url,
        red_flag_count=len(rows),
        categories=_sorted_scalar_values(rows, "category"),
        risk_levels=_sorted_scalar_values(rows, "risk_level"),
        product_types=_sorted_list_values(rows, "product_types"),
        red_flag_ids=[row["id"] for row in rows],
    )


def _source_id(row: dict[str, Any]) -> str:
    if row.get("source_url"):
        return f"url-{_stable_hash(row['source_url'])}"
    if row.get("regulatory_source"):
        return f"name-{_stable_hash(row['regulatory_source'])}"
    return "unknown-source"


def _stable_hash(value: str) -> str:
    return hashlib.sha1(value.strip().lower().encode("utf-8")).hexdigest()[:12]


def _sorted_scalar_values(rows: list[dict[str, Any]], field: str) -> list[str]:
    return sorted({row[field] for row in rows if row.get(field)})


def _sorted_list_values(rows: list[dict[str, Any]], field: str) -> list[str]:
    values: set[str] = set()
    for row in rows:
        values.update(row.get(field) or [])
    return sorted(values)


def _description_snippet(description: str, max_length: int = 220) -> str:
    normalized = " ".join(description.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 3].rstrip()}..."


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


def _matches_filters(row: dict[str, Any], filters: RedFlagFilters) -> bool:
    for field in LIST_FILTER_FIELDS:
        required = _clean_list(getattr(filters, field))
        if required and not set(required).intersection(row.get(field) or []):
            return False
    for field in SCALAR_FILTER_FIELDS:
        required = getattr(filters, field)
        if required and row.get(field) != required:
            return False
    return True


def _has_list_filters(filters: RedFlagFilters) -> bool:
    return any(_clean_list(getattr(filters, field)) for field in LIST_FILTER_FIELDS)


def _metadata_result_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    risk_rank = RISK_ORDER.get(row.get("risk_level") or "", len(RISK_ORDER))
    source_label = row.get("regulatory_source") or row.get("source_url") or ""
    return (risk_rank, source_label, row.get("id") or "")


def _scalar_where(*, category: str | None, risk_level: str | None) -> str | None:
    conditions = []
    if category:
        conditions.append(f"category = '{_escape_sql_string(category)}'")
    if risk_level:
        conditions.append(f"risk_level = '{_escape_sql_string(risk_level)}'")
    return " AND ".join(conditions) if conditions else None


def _escape_sql_string(value: str) -> str:
    return value.replace("'", "''")
