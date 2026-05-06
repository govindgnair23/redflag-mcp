from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_corpus import build_corpus_package, build_release_index  # noqa: E402
from verify_corpus import verify_corpus_package  # noqa: E402


def write_source(path: Path, record_id: str = "001-test-01") -> None:
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "id": record_id,
                    "description": "Trade-based money laundering through invoices.",
                    "product_types": ["trade_finance"],
                    "industry_types": ["import_export"],
                    "customer_profiles": ["cross_border_business"],
                    "geographic_footprints": ["domestic_us"],
                    "regulatory_source": "FinCEN Alert",
                    "risk_level": "high",
                    "category": "trade_based_money_laundering",
                    "source_url": "https://example.com/source.pdf",
                    "typology_family": "trade_based_money_laundering",
                    "transaction_patterns": ["invoice_mismatch"],
                    "key_terms": ["TBML"],
                }
            ]
        )
    )


def test_build_and_verify_corpus_package(tmp_path):
    source = tmp_path / "source.yaml"
    aliases = tmp_path / "aliases.yaml"
    source_metadata = tmp_path / "source_metadata.yaml"
    registry = tmp_path / "sources.yaml"
    output_dir = tmp_path / "dist"
    write_source(source)
    aliases.write_text(yaml.safe_dump({"TBML": ["trade based money laundering"]}))
    source_metadata.write_text(
        yaml.safe_dump(
            {
                "001": {
                    "title": "Test Source",
                    "authority": "FinCEN",
                    "jurisdiction": "US",
                    "redistribution_status": "url_only",
                }
            }
        )
    )
    registry.write_text(yaml.safe_dump({"001": {"url": "https://example.com/source.pdf"}}))

    result = build_corpus_package(
        [source],
        output_dir=output_dir,
        version="2026.04.29",
        build_timestamp="2026-04-29T12:00:00Z",
        aliases_path=aliases,
        source_metadata_path=source_metadata,
        source_registry_path=registry,
    )
    verification = verify_corpus_package(result.package_path)

    assert result.package_path.name == "redflag-corpus-2026.04.29.zip"
    assert verification.status == "verified"
    assert verification.version == "2026.04.29"
    assert verification.schema_version == 1
    assert verification.record_count == 1
    assert verification.file_hashes["redflags.sqlite"] == result.manifest["file_hashes"]["redflags.sqlite"]


def test_rebuild_produces_same_sqlite_hash_for_same_inputs(tmp_path):
    source = tmp_path / "source.yaml"
    aliases = tmp_path / "aliases.yaml"
    source_metadata = tmp_path / "source_metadata.yaml"
    registry = tmp_path / "sources.yaml"
    write_source(source)
    aliases.write_text(yaml.safe_dump({"TBML": ["trade based money laundering"]}))
    source_metadata.write_text("{}")
    registry.write_text(yaml.safe_dump({"001": {"url": "https://example.com/source.pdf"}}))

    first = build_corpus_package(
        [source],
        output_dir=tmp_path / "first",
        version="2026.04.29",
        build_timestamp="2026-04-29T12:00:00Z",
        aliases_path=aliases,
        source_metadata_path=source_metadata,
        source_registry_path=registry,
    )
    second = build_corpus_package(
        [source],
        output_dir=tmp_path / "second",
        version="2026.04.29",
        build_timestamp="2026-04-29T12:00:00Z",
        aliases_path=aliases,
        source_metadata_path=source_metadata,
        source_registry_path=registry,
    )

    assert first.manifest["file_hashes"]["redflags.sqlite"] == second.manifest["file_hashes"]["redflags.sqlite"]


def test_build_empty_corpus_fails(tmp_path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("[]")

    with pytest.raises(ValueError, match="No valid source records"):
        build_corpus_package(
            [empty],
            output_dir=tmp_path / "dist",
            version="2026.04.29",
            build_timestamp="2026-04-29T12:00:00Z",
        )


def test_verify_detects_sqlite_hash_mismatch(tmp_path):
    source = tmp_path / "source.yaml"
    write_source(source)
    result = build_corpus_package(
        [source],
        output_dir=tmp_path / "dist",
        version="2026.04.29",
        build_timestamp="2026-04-29T12:00:00Z",
    )
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(result.package_path) as original, zipfile.ZipFile(
        tampered, "w"
    ) as replacement:
        for name in original.namelist():
            data = original.read(name)
            if name == "redflags.sqlite":
                data = data + b"tampered"
            replacement.writestr(name, data)

    verification = verify_corpus_package(tampered)

    assert verification.status == "failed"
    assert "hash mismatch" in verification.message


def test_malformed_package_without_manifest_fails(tmp_path):
    package = tmp_path / "bad.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("redflags.sqlite", b"not a database")

    verification = verify_corpus_package(package)

    assert verification.status == "failed"
    assert "manifest.json" in verification.message


def test_release_index_identifies_latest_compatible_version(tmp_path):
    source = tmp_path / "source.yaml"
    write_source(source)
    old = build_corpus_package(
        [source],
        output_dir=tmp_path / "old",
        version="2026.04.28",
        build_timestamp="2026-04-28T12:00:00Z",
    )
    new = build_corpus_package(
        [source],
        output_dir=tmp_path / "new",
        version="2026.04.29",
        build_timestamp="2026-04-29T12:00:00Z",
    )

    index = build_release_index([old.package_path, new.package_path])

    assert index["latest_compatible_version"] == "2026.04.29"
    assert index["releases"][0]["version"] == "2026.04.29"
    assert "sha256" in index["releases"][0]


def test_source_metadata_controls_url_only_packaging(tmp_path):
    source = tmp_path / "source.yaml"
    source_metadata = tmp_path / "source_metadata.yaml"
    registry = tmp_path / "sources.yaml"
    write_source(source)
    source_metadata.write_text(
        yaml.safe_dump({"001": {"title": "URL Only", "redistribution_status": "url_only"}})
    )
    registry.write_text(yaml.safe_dump({"001": {"url": "https://example.com/source.pdf"}}))

    result = build_corpus_package(
        [source],
        output_dir=tmp_path / "dist",
        version="2026.04.29",
        build_timestamp="2026-04-29T12:00:00Z",
        source_metadata_path=source_metadata,
        source_registry_path=registry,
    )

    with zipfile.ZipFile(result.package_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))

    assert manifest["sources"]["001"]["redistribution_status"] == "url_only"
    assert manifest["sources"]["001"]["bundle_source_asset"] is False


def test_enriched_yaml_fields_are_included_in_lexical_index(tmp_path):
    source = tmp_path / "source.yaml"
    write_source(source)
    result = build_corpus_package(
        [source],
        output_dir=tmp_path / "dist",
        version="2026.04.29",
        build_timestamp="2026-04-29T12:00:00Z",
    )

    from redflag_mcp.lexicalstore import LexicalStore

    with zipfile.ZipFile(result.package_path) as archive:
        sqlite_path = tmp_path / "redflags.sqlite"
        sqlite_path.write_bytes(archive.read("redflags.sqlite"))

    results = LexicalStore.open(sqlite_path).search("invoice_mismatch")

    assert [record.id for record in results] == ["001-test-01"]
