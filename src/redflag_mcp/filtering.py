from __future__ import annotations

from typing import Any

from redflag_mcp.config import INDUSTRY_GROUP_MAPPINGS, SUBJECT_MAPPINGS


def matches_subjects(row: dict[str, Any], subjects: list[str] | None) -> bool:
    requested = _clean_list(subjects)
    if not requested:
        return True
    return any(_matches_subject(row, subject) for subject in requested)


def matches_industry_groups(
    row: dict[str, Any], industry_groups: list[str] | None
) -> bool:
    requested = _clean_list(industry_groups)
    if not requested:
        return True
    industry_types = set(row.get("industry_types") or [])
    return any(
        industry_types.intersection(INDUSTRY_GROUP_MAPPINGS.get(group, ()))
        for group in requested
    )


def _matches_subject(row: dict[str, Any], subject: str) -> bool:
    mapping = SUBJECT_MAPPINGS.get(subject)
    if mapping is None:
        return False
    if row.get("category") in mapping["category"]:
        return True
    if set(mapping["typology_family"]).intersection(row.get("typology_family") or []):
        return True
    return bool(
        set(mapping["transaction_patterns"]).intersection(
            row.get("transaction_patterns") or []
        )
    )


def _clean_list(values: list[str] | None) -> list[str]:
    return [value for value in values or [] if value]
