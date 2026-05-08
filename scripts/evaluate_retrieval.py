#!/usr/bin/env python3
"""Run a small hosted lexical retrieval benchmark."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redflag_mcp.tools import RedFlagService  # noqa: E402

LOGGER = logging.getLogger(__name__)


class BenchmarkFailure(AssertionError):
    """Raised when one or more benchmark queries miss expected results."""


@dataclass(frozen=True)
class BenchmarkQuery:
    id: str
    query: str
    top_n: int = 5
    expected_ids: list[str] | None = None
    expected_category: str | None = None
    expected_regulatory_source: str | None = None


def load_benchmark(path: Path) -> list[BenchmarkQuery]:
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict) or not isinstance(data.get("queries"), list):
        raise ValueError("Benchmark file must contain a top-level queries list")

    queries: list[BenchmarkQuery] = []
    for index, raw_query in enumerate(data["queries"], start=1):
        if not isinstance(raw_query, dict):
            raise ValueError(f"Benchmark query {index} must be a mapping")
        if not raw_query.get("id") or not raw_query.get("query"):
            raise ValueError(f"Benchmark query {index} requires id and query")
        has_expected = any(
            raw_query.get(field_name)
            for field_name in (
                "expected_ids",
                "expected_category",
                "expected_regulatory_source",
            )
        )
        if not has_expected:
            raise ValueError(f"Benchmark query {raw_query['id']} requires expected fields")
        queries.append(
            BenchmarkQuery(
                id=str(raw_query["id"]),
                query=str(raw_query["query"]),
                top_n=int(raw_query.get("top_n") or 5),
                expected_ids=[str(value) for value in raw_query.get("expected_ids") or []]
                or None,
                expected_category=(
                    str(raw_query["expected_category"])
                    if raw_query.get("expected_category")
                    else None
                ),
                expected_regulatory_source=(
                    str(raw_query["expected_regulatory_source"])
                    if raw_query.get("expected_regulatory_source")
                    else None
                ),
            )
        )
    return queries


def evaluate_benchmark(corpus_path: Path, benchmark_path: Path) -> dict[str, Any]:
    if not corpus_path.exists():
        raise FileNotFoundError(f"Corpus path not found: {corpus_path}")

    with _sqlite_corpus_path(corpus_path) as sqlite_path:
        service = RedFlagService.from_corpus_path(sqlite_path)
        queries = load_benchmark(benchmark_path)
        failures: list[str] = []
        for benchmark_query in queries:
            response = service.search_red_flags(
                query=benchmark_query.query,
                limit=benchmark_query.top_n,
            )
            results = response["results"]
            if not _matches_expectations(benchmark_query, results):
                result_ids = [result["id"] for result in results]
                failures.append(
                    f"{benchmark_query.id}: expected match not found in top "
                    f"{benchmark_query.top_n}; got {result_ids}"
                )

    if failures:
        raise BenchmarkFailure("; ".join(failures))

    return {
        "total": len(queries),
        "passed": len(queries),
        "failed": 0,
        "corpus_path": str(corpus_path),
        "benchmark_path": str(benchmark_path),
    }


@contextmanager
def _sqlite_corpus_path(corpus_path: Path):
    if corpus_path.suffix != ".zip":
        yield corpus_path
        return

    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_path = Path(temp_dir) / "redflags.sqlite"
        with zipfile.ZipFile(corpus_path) as archive:
            sqlite_path.write_bytes(archive.read("redflags.sqlite"))
        yield sqlite_path


def _matches_expectations(
    benchmark_query: BenchmarkQuery,
    results: list[dict[str, Any]],
) -> bool:
    if benchmark_query.expected_ids:
        result_ids = {str(result.get("id")) for result in results}
        return bool(result_ids.intersection(benchmark_query.expected_ids))

    has_metadata_expectation = (
        benchmark_query.expected_category is not None
        or benchmark_query.expected_regulatory_source is not None
    )
    if not has_metadata_expectation:
        return False

    for result in results:
        category_matches = (
            benchmark_query.expected_category is None
            or result.get("category") == benchmark_query.expected_category
        )
        source_matches = (
            benchmark_query.expected_regulatory_source is None
            or result.get("regulatory_source")
            == benchmark_query.expected_regulatory_source
        )
        if category_matches and source_matches:
            return True
    return False


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate hosted lexical retrieval against a smoke benchmark."
    )
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=Path("data/eval/hosted_retrieval_queries.yaml"),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        summary = evaluate_benchmark(args.corpus, args.benchmark)
    except (BenchmarkFailure, FileNotFoundError, ValueError) as exc:
        LOGGER.error("%s", exc)
        sys.stderr.write(f"{exc}\n")
        raise SystemExit(1) from exc
    LOGGER.info(
        "Retrieval benchmark passed: %s/%s queries",
        summary["passed"],
        summary["total"],
    )


if __name__ == "__main__":
    main()
