from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Literal, cast

from redflag_mcp.models import (
    CorpusMetadata,
    RedFlagRecord,
    RedFlagResult,
    RedFlagSourceDetail,
    RedFlagSourceSummary,
    SourceRedFlagSnippet,
)

LEXICAL_SCHEMA_VERSION = 3
SOURCE_DETAIL_SNIPPET_LIMIT = 10
LIST_FILTER_FIELDS = (
    "product_types",
    "industry_types",
    "customer_profiles",
    "geographic_footprints",
    "typology_family",
    "transaction_patterns",
)
SCALAR_FILTER_FIELDS = ("category", "risk_level", "regulator", "regulator_jurisdiction")
DISTINCT_FILTER_FIELDS = LIST_FILTER_FIELDS + SCALAR_FILTER_FIELDS
JSON_LIST_FIELDS = (*LIST_FILTER_FIELDS, "key_terms")
RISK_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class LexicalRedFlagFilters:
    product_types: list[str] | None = None
    industry_types: list[str] | None = None
    customer_profiles: list[str] | None = None
    geographic_footprints: list[str] | None = None
    typology_family: list[str] | None = None
    transaction_patterns: list[str] | None = None
    category: str | None = None
    risk_level: str | None = None
    regulator: str | None = None
    regulator_jurisdiction: str | None = None
    issued_after: str | None = None
    issued_before: str | None = None
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
                "issued_after",
                "issued_before",
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


@dataclass
class _ExpandedQuery:
    terms: list[str]
    signals: list[str]


@dataclass
class LexicalStore:
    db_path: Path
    corpus: CorpusMetadata

    @classmethod
    def open(cls, db_path: Path | str) -> LexicalStore:
        path = Path(db_path)
        with _connect(path) as connection:
            schema_version = _metadata_value(connection, "schema_version")
            if schema_version != str(LEXICAL_SCHEMA_VERSION):
                raise ValueError(
                    "Unsupported corpus schema version: "
                    f"{schema_version or 'missing'}"
                )
            integrity_status = _required_metadata_value(connection, "integrity_status")
            if integrity_status not in {"unverified", "verified", "failed"}:
                raise ValueError(f"Unsupported integrity status: {integrity_status}")
            corpus = CorpusMetadata(
                version=_required_metadata_value(connection, "version"),
                schema_version=int(schema_version),
                build_timestamp=_required_metadata_value(connection, "build_timestamp"),
                package_id=_required_metadata_value(connection, "package_id"),
                file_hashes=json.loads(
                    _required_metadata_value(connection, "file_hashes")
                ),
                integrity_status=cast(
                    Literal["unverified", "verified", "failed"],
                    integrity_status,
                ),
                record_count=int(_required_metadata_value(connection, "record_count")),
                source_count=int(_required_metadata_value(connection, "source_count")),
            )
        return cls(db_path=path, corpus=corpus)

    def count_rows(self) -> int:
        with _connect(self.db_path) as connection:
            return int(connection.execute("SELECT COUNT(*) FROM red_flags").fetchone()[0])

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        product_types: list[str] | None = None,
        industry_types: list[str] | None = None,
        customer_profiles: list[str] | None = None,
        geographic_footprints: list[str] | None = None,
        typology_family: list[str] | None = None,
        transaction_patterns: list[str] | None = None,
        category: str | None = None,
        risk_level: str | None = None,
        regulator: str | None = None,
        regulator_jurisdiction: str | None = None,
        issued_after: str | None = None,
        issued_before: str | None = None,
    ) -> list[RedFlagResult]:
        if limit <= 0:
            return []
        filters = LexicalRedFlagFilters(
            product_types=product_types,
            industry_types=industry_types,
            customer_profiles=customer_profiles,
            geographic_footprints=geographic_footprints,
            typology_family=typology_family,
            transaction_patterns=transaction_patterns,
            category=category,
            risk_level=risk_level,
            regulator=regulator,
            regulator_jurisdiction=regulator_jurisdiction,
            issued_after=issued_after,
            issued_before=issued_before,
        )
        expanded = self._expand_query(query)
        if not expanded.terms:
            return self.filter_red_flags(limit=limit, filters=filters)

        match_query = " OR ".join(_fts_phrase(term) for term in expanded.terms)
        with _connect(self.db_path) as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT red_flags.*, bm25(red_flag_fts) AS rank
                    FROM red_flag_fts
                    JOIN red_flags ON red_flags.id = red_flag_fts.id
                    WHERE red_flag_fts.searchable MATCH ?
                    """,
                    (match_query,),
                ).fetchall()
            ]

        rows = [row for row in rows if _matches_all_filters(row, filters)]
        rows.sort(key=_lexical_result_sort_key)
        results: list[RedFlagResult] = []
        for row in rows[:limit]:
            rank = float(row.get("rank") or 0.0)
            result = _row_to_record(row).to_result(score=1.0 / (1.0 + abs(rank)))
            result.fit_signals = [
                *expanded.signals,
                *_metadata_fit_signals(result, filters),
            ]
            if not result.fit_signals:
                result.fit_signals = ["Lexical match to query terms."]
            result.fit_explanation = " ".join(result.fit_signals[:3])
            results.append(result)
        return results

    def filter_red_flags(
        self,
        *,
        limit: int = 20,
        filters: LexicalRedFlagFilters | None = None,
    ) -> list[RedFlagResult]:
        if limit <= 0:
            return []
        filters = filters or LexicalRedFlagFilters()
        rows = [
            row
            for row in self._all_rows()
            if _matches_all_filters(row, filters)
            and (
                filters.regulatory_source is None
                or row.get("regulatory_source") == filters.regulatory_source
            )
            and (filters.source_url is None or row.get("source_url") == filters.source_url)
            and (filters.source_id is None or _source_id(row) == filters.source_id)
        ]
        rows.sort(key=_metadata_result_sort_key)
        return [_row_to_record(row).to_result() for row in rows[:limit]]

    def get_by_id(self, red_flag_id: str) -> RedFlagResult | None:
        with _connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM red_flags WHERE id = ?",
                (red_flag_id,),
            ).fetchone()
        if row is None:
            return None
        return _row_to_record(dict(row)).to_result()

    def list_distinct_values(self) -> dict[str, list[str]]:
        values: dict[str, set[str]] = {field: set() for field in DISTINCT_FILTER_FIELDS}
        for row in self._all_rows():
            for field in LIST_FILTER_FIELDS:
                values[field].update(row.get(field) or [])
            for field in SCALAR_FILTER_FIELDS:
                value = row.get(field)
                if value:
                    values[field].add(value)
        return {field: sorted(field_values) for field, field_values in values.items()}

    def list_sources(self) -> list[RedFlagSourceSummary]:
        groups = self._source_groups()
        return [_source_summary(group) for group in groups.values()]

    def get_source(self, source_id: str) -> RedFlagSourceDetail | None:
        group = self._source_group(source_id)
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
                    description_snippet=_description_snippet(
                        row.get("description") or ""
                    ),
                    category=row.get("category"),
                    risk_level=row.get("risk_level"),
                )
                for row in rows[:SOURCE_DETAIL_SNIPPET_LIMIT]
            ],
        )

    def _expand_query(self, query: str) -> _ExpandedQuery:
        terms = _query_terms(query)
        signals: list[str] = []
        with _connect(self.db_path) as connection:
            aliases = {
                row["alias"].lower(): json.loads(row["expansions"])
                for row in connection.execute("SELECT alias, expansions FROM aliases")
            }
        expanded_terms = list(terms)
        for term in terms:
            expansions = aliases.get(term.lower())
            if not expansions:
                continue
            expanded_terms.extend(expansions)
            signals.append(f"Expanded alias {term} to {', '.join(expansions)}.")
        return _ExpandedQuery(terms=_dedupe(expanded_terms), signals=signals)

    def _all_rows(self) -> list[dict[str, Any]]:
        with _connect(self.db_path) as connection:
            return [
                _decode_row(dict(row))
                for row in connection.execute("SELECT * FROM red_flags").fetchall()
            ]

    def _source_groups(self) -> dict[str, _SourceGroup]:
        groups: dict[str, _SourceGroup] = {}
        for row in self._all_rows():
            source_id = _source_id(row)
            group = groups.setdefault(source_id, _source_group_for_row(row, source_id))
            group.add(row)
        return dict(sorted(groups.items(), key=lambda item: item[0]))

    def _source_group(self, source_id: str) -> _SourceGroup | None:
        group = None
        for row in self._all_rows():
            if _source_id(row) != source_id:
                continue
            group = group or _source_group_for_row(row, source_id)
            group.add(row)
        return group


def create_lexical_store(
    db_path: Path | str,
    records: list[RedFlagRecord],
    *,
    corpus: CorpusMetadata,
    aliases: dict[str, list[str]],
    extra_search_text: dict[str, list[str]] | None = None,
) -> None:
    path = Path(db_path)
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    corpus = corpus.model_copy(
        update={
            "schema_version": LEXICAL_SCHEMA_VERSION,
            "record_count": len(records),
            "source_count": len({_source_id(record.model_dump()) for record in records}),
        }
    )
    with _connect(path) as connection:
        _create_schema(connection)
        _write_metadata(connection, corpus)
        for alias, expansions in sorted(aliases.items(), key=lambda item: item[0].lower()):
            connection.execute(
                "INSERT INTO aliases (alias, expansions) VALUES (?, ?)",
                (alias, json.dumps(expansions, sort_keys=True)),
            )
        for record in sorted(records, key=lambda item: item.id):
            row = record.model_dump()
            connection.execute(
                """
                INSERT INTO red_flags (
                    id, description, product_types, industry_types, customer_profiles,
                    geographic_footprints, regulatory_source, regulator,
                    regulator_jurisdiction, issued_date,
                    risk_level, category, simulation_type, source_url,
                    typology_family, transaction_patterns, key_terms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["description"],
                    json.dumps(row["product_types"], sort_keys=True),
                    json.dumps(row["industry_types"], sort_keys=True),
                    json.dumps(row["customer_profiles"], sort_keys=True),
                    json.dumps(row["geographic_footprints"], sort_keys=True),
                    row.get("regulatory_source"),
                    row.get("regulator"),
                    row.get("regulator_jurisdiction"),
                    row.get("issued_date"),
                    row.get("risk_level"),
                    row.get("category"),
                    row.get("simulation_type"),
                    row.get("source_url"),
                    json.dumps(row["typology_family"], sort_keys=True),
                    json.dumps(row["transaction_patterns"], sort_keys=True),
                    json.dumps(row["key_terms"], sort_keys=True),
                ),
            )
            connection.execute(
                "INSERT INTO red_flag_fts (id, searchable) VALUES (?, ?)",
                (row["id"], _searchable_text(row, extra_search_text=extra_search_text)),
            )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode = OFF")
    connection.execute("PRAGMA synchronous = OFF")
    connection.execute(
        "CREATE TABLE corpus_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        """
        CREATE TABLE red_flags (
            id TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            product_types TEXT NOT NULL,
            industry_types TEXT NOT NULL,
            customer_profiles TEXT NOT NULL,
            geographic_footprints TEXT NOT NULL,
            regulatory_source TEXT,
            regulator TEXT,
            regulator_jurisdiction TEXT,
            issued_date TEXT,
            risk_level TEXT,
            category TEXT,
            simulation_type TEXT,
            source_url TEXT,
            typology_family TEXT NOT NULL,
            transaction_patterns TEXT NOT NULL,
            key_terms TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "CREATE VIRTUAL TABLE red_flag_fts USING fts5(id UNINDEXED, searchable)"
    )
    connection.execute(
        "CREATE TABLE aliases (alias TEXT PRIMARY KEY, expansions TEXT NOT NULL)"
    )


def _write_metadata(connection: sqlite3.Connection, corpus: CorpusMetadata) -> None:
    payload = corpus.model_dump()
    for key, value in payload.items():
        if key == "file_hashes":
            stored = json.dumps(value, sort_keys=True)
        else:
            stored = str(value)
        connection.execute(
            "INSERT INTO corpus_metadata (key, value) VALUES (?, ?)",
            (key, stored),
        )


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _metadata_value(connection: sqlite3.Connection, key: str) -> str | None:
    try:
        row = connection.execute(
            "SELECT value FROM corpus_metadata WHERE key = ?",
            (key,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    return str(row["value"])


def _required_metadata_value(connection: sqlite3.Connection, key: str) -> str:
    value = _metadata_value(connection, key)
    if value is None:
        raise ValueError(f"Missing corpus metadata: {key}")
    return value


def _decode_row(row: dict[str, Any]) -> dict[str, Any]:
    for field in JSON_LIST_FIELDS:
        if isinstance(row.get(field), str):
            row[field] = json.loads(row[field] or "[]")
        else:
            row[field] = row.get(field) or []
    return row


def _row_to_record(row: dict[str, Any]) -> RedFlagRecord:
    cleaned = {
        key: value
        for key, value in _decode_row(dict(row)).items()
        if key in RedFlagRecord.model_fields
    }
    return RedFlagRecord(**cleaned)


def _query_terms(query: str) -> list[str]:
    return _dedupe(re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)?", query))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _fts_phrase(term: str) -> str:
    return f'"{term.replace(chr(34), " ").strip()}"'


def _searchable_text(
    row: dict[str, Any],
    *,
    extra_search_text: dict[str, list[str]] | None = None,
) -> str:
    values: list[str] = [
        str(row.get("description") or ""),
        str(row.get("category") or ""),
        str(row.get("risk_level") or ""),
        str(row.get("regulatory_source") or ""),
        str(row.get("regulator_jurisdiction") or ""),
        str(row.get("source_url") or ""),
    ]
    for field in LIST_FILTER_FIELDS:
        values.extend(row.get(field) or [])
    for field in ("typology_family", "transaction_patterns", "key_terms"):
        value = row.get(field)
        if isinstance(value, list):
            values.extend(str(item) for item in value)
        elif value:
            values.append(str(value))
    values.extend(extra_search_text.get(str(row.get("id")), []) if extra_search_text else [])
    return " ".join(values)


def _metadata_fit_signals(
    result: RedFlagResult, filters: LexicalRedFlagFilters
) -> list[str]:
    signals: list[str] = []
    for label, result_attr in (
        ("Product type", "product_types"),
        ("Industry type", "industry_types"),
        ("Customer profile", "customer_profiles"),
        ("Geographic footprint", "geographic_footprints"),
    ):
        requested = _clean_list(getattr(filters, result_attr))
        matches = sorted(set(requested).intersection(getattr(result, result_attr)))
        if matches:
            signals.append(f"{label} matches {', '.join(matches)}.")
    if filters.category and result.category == filters.category:
        signals.append(f"Category matches {filters.category}.")
    elif result.category:
        signals.append(f"Category is {result.category}.")
    if filters.risk_level and result.risk_level == filters.risk_level:
        signals.append(f"Risk level matches {filters.risk_level}.")
    elif result.risk_level:
        signals.append(f"Risk level is {result.risk_level}.")
    if filters.regulator and result.regulator == filters.regulator:
        signals.append(f"Regulator matches {filters.regulator}.")
    elif result.regulator:
        signals.append(f"Regulator is {result.regulator}.")
    if (
        filters.regulator_jurisdiction
        and result.regulator_jurisdiction == filters.regulator_jurisdiction
    ):
        signals.append(
            f"Regulator jurisdiction matches {filters.regulator_jurisdiction}."
        )
    elif result.regulator_jurisdiction:
        signals.append(f"Regulator jurisdiction is {result.regulator_jurisdiction}.")
    if result.regulatory_source:
        signals.append(f"Source is {result.regulatory_source}.")
    return signals


def _matches_all_filters(row: dict[str, Any], filters: LexicalRedFlagFilters) -> bool:
    decoded = _decode_row(dict(row))
    for field in LIST_FILTER_FIELDS:
        required = _clean_list(getattr(filters, field))
        if required and not set(required).intersection(decoded.get(field) or []):
            return False
    for field in SCALAR_FILTER_FIELDS:
        required = getattr(filters, field)
        if required and decoded.get(field) != required:
            return False
    if filters.issued_after and (decoded.get("issued_date") or "") < filters.issued_after:
        return False
    if filters.issued_before and (decoded.get("issued_date") or "") > filters.issued_before:
        return False
    return True


def _clean_list(values: list[str] | None) -> list[str]:
    return [value for value in values or [] if value]


def _lexical_result_sort_key(row: dict[str, Any]) -> tuple[float, int, str, str]:
    return (
        float(row.get("rank") or 0.0),
        RISK_ORDER.get(row.get("risk_level") or "", len(RISK_ORDER)),
        row.get("regulatory_source") or row.get("source_url") or "",
        row.get("id") or "",
    )


def _metadata_result_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    risk_rank = RISK_ORDER.get(row.get("risk_level") or "", len(RISK_ORDER))
    source_label = row.get("regulatory_source") or row.get("source_url") or ""
    return (risk_rank, source_label, row.get("id") or "")


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
