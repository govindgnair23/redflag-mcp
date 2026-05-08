from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from evaluate_retrieval import (  # noqa: E402
    BenchmarkFailure,
    evaluate_benchmark,
    load_benchmark,
    main,
)

from redflag_mcp.lexicalstore import create_lexical_store  # noqa: E402
from redflag_mcp.models import CorpusMetadata, RedFlagRecord  # noqa: E402


def corpus_metadata() -> CorpusMetadata:
    return CorpusMetadata(
        version="2026.04.29",
        schema_version=3,
        build_timestamp="2026-04-29T12:00:00Z",
        package_id="redflag-corpus-2026.04.29",
        file_hashes={"redflags.sqlite": "a" * 64},
        integrity_status="verified",
        record_count=2,
        source_count=2,
    )


def make_record(
    record_id: str,
    *,
    description: str,
    product_types: list[str] | None = None,
    category: str = "fraud_nexus",
    regulatory_source: str = "FinCEN Alert",
    key_terms: list[str] | None = None,
) -> RedFlagRecord:
    return RedFlagRecord(
        id=record_id,
        description=description,
        product_types=product_types or [],
        category=category,
        regulatory_source=regulatory_source,
        risk_level="high",
        source_url="https://example.com/source.pdf",
        key_terms=key_terms or [],
    )


def seeded_corpus(tmp_path: Path) -> Path:
    db_path = tmp_path / "redflags.sqlite"
    create_lexical_store(
        db_path,
        [
            make_record(
                "tbml-01",
                description="Trade-based money laundering invoice mismatch.",
                product_types=["trade_finance"],
                category="trade_based_money_laundering",
                regulatory_source="FinCEN TBML Alert",
                key_terms=["TBML"],
            ),
            make_record(
                "benefits-01",
                description="Government benefits sponsor reimbursement fraud.",
                product_types=["depository"],
                category="fraud_nexus",
                regulatory_source="FinCEN Benefits Alert",
            ),
        ],
        corpus=corpus_metadata(),
        aliases={"TBML": ["trade based money laundering"]},
    )
    return db_path


def write_benchmark(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text(yaml.safe_dump({"queries": entries}, sort_keys=True))


def test_benchmark_alias_query_retrieves_expected_id(tmp_path):
    corpus_path = seeded_corpus(tmp_path)
    benchmark_path = tmp_path / "queries.yaml"
    write_benchmark(
        benchmark_path,
        [
            {
                "id": "alias-tbml",
                "query": "TBML invoice mismatch",
                "top_n": 3,
                "expected_ids": ["tbml-01"],
            }
        ],
    )

    summary = evaluate_benchmark(corpus_path, benchmark_path)

    assert summary["passed"] == 1
    assert summary["failed"] == 0


def test_benchmark_accepts_corpus_package_zip(tmp_path):
    corpus_path = seeded_corpus(tmp_path)
    package_path = tmp_path / "redflag-corpus-test.zip"
    with zipfile.ZipFile(package_path, "w") as archive:
        archive.write(corpus_path, "redflags.sqlite")
    benchmark_path = tmp_path / "queries.yaml"
    write_benchmark(
        benchmark_path,
        [{"id": "alias-tbml", "query": "TBML", "expected_ids": ["tbml-01"]}],
    )

    summary = evaluate_benchmark(package_path, benchmark_path)

    assert summary["passed"] == 1


def test_benchmark_metadata_query_matches_expected_category_and_source(tmp_path):
    corpus_path = seeded_corpus(tmp_path)
    benchmark_path = tmp_path / "queries.yaml"
    write_benchmark(
        benchmark_path,
        [
            {
                "id": "metadata-benefits",
                "query": "government benefits reimbursement fraud",
                "top_n": 2,
                "expected_category": "fraud_nexus",
                "expected_regulatory_source": "FinCEN Benefits Alert",
            }
        ],
    )

    summary = evaluate_benchmark(corpus_path, benchmark_path)

    assert summary["passed"] == 1
    assert summary["failed"] == 0


def test_benchmark_missing_expected_fields_fails_validation(tmp_path):
    benchmark_path = tmp_path / "queries.yaml"
    write_benchmark(
        benchmark_path,
        [{"id": "invalid", "query": "missing expectations"}],
    )

    with pytest.raises(ValueError, match="expected"):
        load_benchmark(benchmark_path)


def test_benchmark_missing_corpus_path_exits_clearly(tmp_path, capsys):
    benchmark_path = tmp_path / "queries.yaml"
    write_benchmark(
        benchmark_path,
        [{"id": "alias-tbml", "query": "TBML", "expected_ids": ["tbml-01"]}],
    )

    with pytest.raises(SystemExit) as exc:
        main(["--corpus", str(tmp_path / "missing.sqlite"), "--benchmark", str(benchmark_path)])

    assert exc.value.code == 1
    assert "Corpus path not found" in capsys.readouterr().err


def test_benchmark_failure_raises_for_missing_expected_result(tmp_path):
    corpus_path = seeded_corpus(tmp_path)
    benchmark_path = tmp_path / "queries.yaml"
    write_benchmark(
        benchmark_path,
        [{"id": "alias-tbml", "query": "TBML", "expected_ids": ["missing"]}],
    )

    with pytest.raises(BenchmarkFailure):
        evaluate_benchmark(corpus_path, benchmark_path)
