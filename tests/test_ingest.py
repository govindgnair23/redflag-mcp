from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ingest import (  # noqa: E402
    build_records,
    discover_source_files,
    filter_source_paths_by_range,
    ingest_sources,
    load_sources,
    merge_metadata,
    missing_metadata_fields,
    parse_serial_range,
    run_write_back_yaml,
    select_write_back_paths,
    warn_free_form_values,
    write_back_yaml_sources,
)
from redflag_mcp.config import EMBEDDING_DIM  # noqa: E402
from redflag_mcp.models import RedFlagSource  # noqa: E402
from redflag_mcp.vectorstore import get_or_create_table, list_distinct_values, open_store  # noqa: E402


class FakeModel:
    def encode(self, sentences: list[str], **kwargs: object) -> list[list[float]]:
        return [[float(index)] + [0.0] * (EMBEDDING_DIM - 1) for index, _ in enumerate(sentences)]


TARGET_FILES = [
    Path("data/source/001_federal_child_nutrition_fraud.yaml"),
    Path("data/source/002_oil_smuggling_cartels.yaml"),
    Path("data/source/003_bulk_cash_smuggling_repatriation.yaml"),
]


def test_load_target_yaml_files_produces_37_valid_records():
    sources, invalid = load_sources(TARGET_FILES)

    assert len(sources) == 37
    assert invalid == 0


def test_complete_metadata_does_not_trigger_tagger():
    source = RedFlagSource(
        id="complete-01",
        description="Complete record",
        product_types=["depository"],
        industry_types=["retail"],
        customer_profiles=["cash_intensive_business"],
        geographic_footprints=["domestic_us"],
        regulatory_source="FinCEN Alert",
        risk_level="high",
        category="structuring",
        typology_family=["fraud_proceeds"],
        transaction_patterns=["structuring"],
        key_terms=["cash deposit"],
        regulator="FinCEN",
        issued_date="2022-03",
    )

    def tagger(_source: RedFlagSource, _missing: list[str]) -> dict:
        raise AssertionError("tagger should not be called for complete metadata")

    records, enriched_count = build_records([source], embedding_model=FakeModel(), tagger=tagger)

    assert enriched_count == 0
    assert records[0].industry_types == ["retail"]


def test_missing_rich_metadata_is_enriched_with_mocked_tagger():
    source = RedFlagSource(
        id="missing-01",
        description="Small oil company wires funds near the southwest border",
        product_types=["depository"],
        regulatory_source="FinCEN Alert",
        risk_level="medium",
        category="fraud_nexus",
    )

    def tagger(_source: RedFlagSource, missing: list[str]) -> dict:
        assert "industry_types" in missing
        return {
            "industry_types": ["oil_and_gas"],
            "customer_profiles": ["small_business"],
            "geographic_footprints": ["southwest_border"],
        }

    records, enriched_count = build_records([source], embedding_model=FakeModel(), tagger=tagger)

    assert enriched_count == 1
    assert records[0].industry_types == ["oil_and_gas"]
    assert records[0].customer_profiles == ["small_business"]
    assert records[0].geographic_footprints == ["southwest_border"]


def test_explicit_source_selection_excludes_other_yaml(tmp_path, tmp_vectors_dir):
    selected = tmp_path / "selected.yaml"
    other = tmp_path / "other.yaml"
    selected.write_text(
        yaml.safe_dump([{"id": "selected-01", "description": "Selected"}])
    )
    other.write_text(yaml.safe_dump([{"id": "other-01", "description": "Other"}]))

    summary = ingest_sources([selected], vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    table = get_or_create_table(open_store(tmp_vectors_dir))
    assert summary.valid_records == 1
    assert table.count_rows() == 1
    assert list_distinct_values(table)["category"] == []


def test_missing_api_key_path_preserves_metadata_and_logs_warning(caplog):
    source = RedFlagSource(id="minimal-01", description="Minimal")

    with caplog.at_level(logging.WARNING):
        records, enriched_count = build_records([source], embedding_model=FakeModel())

    assert enriched_count == 0
    assert records[0].industry_types == []
    assert "missing metadata fields" in caplog.text


def test_invalid_records_are_reported_without_aborting_other_files(tmp_path):
    valid = tmp_path / "valid.yaml"
    invalid = tmp_path / "invalid.yaml"
    malformed = tmp_path / "malformed.yaml"
    valid.write_text(yaml.safe_dump([{"id": "valid-01", "description": "Valid"}]))
    invalid.write_text(
        yaml.safe_dump(
            [{"id": "invalid-01", "description": "Invalid", "risk_level": "critical"}]
        )
    )
    malformed.write_text("[")

    sources, invalid_count = load_sources([invalid, malformed, valid])

    assert [source.id for source in sources] == ["valid-01"]
    assert invalid_count == 2


def test_ingestion_twice_keeps_one_row_per_id(tmp_path, tmp_vectors_dir):
    source = tmp_path / "source.yaml"
    source.write_text(yaml.safe_dump([{"id": "one-01", "description": "One"}]))

    ingest_sources([source], vector_dir=tmp_vectors_dir, embedding_model=FakeModel())
    ingest_sources([source], vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    table = get_or_create_table(open_store(tmp_vectors_dir))
    assert table.count_rows() == 1


def test_discover_source_files_excludes_hidden_manifest(tmp_path):
    visible = tmp_path / "visible.yaml"
    hidden = tmp_path / ".extracted_sources.yaml"
    visible.write_text("[]")
    hidden.write_text("[]")

    assert discover_source_files(tmp_path) == [visible]


def test_missing_metadata_fields_detects_empty_lists_and_scalars():
    source = RedFlagSource(
        id="missing-01",
        description="Missing",
        product_types=[],
        risk_level="medium",
    )

    missing = missing_metadata_fields(source)

    assert "product_types" in missing
    assert "industry_types" in missing
    assert "risk_level" not in missing


def test_missing_metadata_fields_detects_absent_enriched_fields():
    source = RedFlagSource(id="enriched-missing-01", description="No enrichment fields set")

    missing = missing_metadata_fields(source)

    assert "typology_family" in missing
    assert "transaction_patterns" in missing
    assert "key_terms" in missing


def test_complete_enrichment_does_not_trigger_tagger_for_enriched_fields():
    source = RedFlagSource(
        id="complete-enriched-01",
        description="Fully enriched record",
        product_types=["depository"],
        industry_types=["import_export"],
        customer_profiles=["cross_border_business"],
        geographic_footprints=["domestic_us"],
        regulatory_source="FinCEN Alert",
        risk_level="high",
        category="layering",
        typology_family=["trade_based_money_laundering"],
        transaction_patterns=["trade_document_manipulation"],
        key_terms=["invoice fraud", "TBML"],
        regulator="FinCEN",
        issued_date="2022-03",
    )

    def tagger(_source: RedFlagSource, _missing: list[str]) -> dict:
        raise AssertionError("tagger should not be called for fully enriched record")

    records, enriched_count = build_records([source], embedding_model=FakeModel(), tagger=tagger)

    assert enriched_count == 0
    assert records[0].typology_family == ["trade_based_money_laundering"]
    assert records[0].transaction_patterns == ["trade_document_manipulation"]
    assert records[0].key_terms == ["invoice fraud", "TBML"]


def test_tagger_enriches_missing_new_fields():
    source = RedFlagSource(
        id="new-fields-missing-01",
        description="TBML invoice scheme for layering proceeds",
        product_types=["depository"],
        industry_types=["import_export"],
        customer_profiles=["cross_border_business"],
        geographic_footprints=["domestic_us"],
        regulatory_source="FinCEN Alert",
        risk_level="medium",
        category="layering",
    )

    def tagger(_source: RedFlagSource, missing: list[str]) -> dict:
        assert "typology_family" in missing
        assert "transaction_patterns" in missing
        assert "key_terms" in missing
        return {
            "typology_family": ["trade_based_money_laundering"],
            "transaction_patterns": ["trade_document_manipulation"],
            "key_terms": ["TBML", "invoice fraud"],
        }

    records, enriched_count = build_records([source], embedding_model=FakeModel(), tagger=tagger)

    assert enriched_count == 1
    assert records[0].typology_family == ["trade_based_money_laundering"]
    assert records[0].transaction_patterns == ["trade_document_manipulation"]
    assert records[0].key_terms == ["TBML", "invoice fraud"]


def test_merge_metadata_normalizes_scalar_list_field_patch():
    source = RedFlagSource(
        id="scalar-list-patch-01",
        description="TBML invoice scheme for layering proceeds",
    )

    merged = merge_metadata(
        source,
        {
            "typology_family": "trade_based_money_laundering",
            "transaction_patterns": "trade_document_manipulation",
            "key_terms": "TBML",
        },
        ["typology_family", "transaction_patterns", "key_terms"],
    )

    assert merged.typology_family == ["trade_based_money_laundering"]
    assert merged.transaction_patterns == ["trade_document_manipulation"]
    assert merged.key_terms == ["TBML"]


def test_warn_free_form_values_logs_for_unknown_vocabulary(caplog):
    from redflag_mcp.config import TYPOLOGY_FAMILIES

    with caplog.at_level(logging.WARNING):
        warn_free_form_values(
            "test-01",
            "typology_family",
            ["trade_based_money_laundering", "some_exotic_new_type"],
            TYPOLOGY_FAMILIES,
        )

    assert "some_exotic_new_type" in caplog.text
    assert "typology_family" in caplog.text


def test_warn_free_form_values_silent_for_known_vocabulary(caplog):
    from redflag_mcp.config import TYPOLOGY_FAMILIES

    with caplog.at_level(logging.WARNING):
        warn_free_form_values(
            "test-02",
            "typology_family",
            ["trade_based_money_laundering", "sanctions_evasion"],
            TYPOLOGY_FAMILIES,
        )

    assert caplog.text == ""


def test_write_back_yaml_sources_round_trips_enriched_records(tmp_path):
    target = tmp_path / "sources.yaml"
    sources = [
        RedFlagSource(
            id="roundtrip-01",
            description="Trade-based layering scheme.",
            product_types=["depository"],
            regulatory_source="FinCEN Alert",
            risk_level="medium",
            category="layering",
            typology_family=["trade_based_money_laundering"],
            transaction_patterns=["trade_document_manipulation"],
            key_terms=["TBML", "invoice"],
        ),
        RedFlagSource(
            id="roundtrip-02",
            description="Structuring cash deposits.",
            product_types=["depository"],
            regulatory_source="FinCEN Alert",
            risk_level="high",
            category="structuring",
            typology_family=["fraud_proceeds"],
            transaction_patterns=["structuring"],
            key_terms=["cash", "CTR avoidance"],
        ),
    ]

    write_back_yaml_sources(sources, target)

    reloaded, invalid = load_sources([target])
    assert invalid == 0
    assert len(reloaded) == 2
    assert reloaded[0].typology_family == ["trade_based_money_laundering"]
    assert reloaded[1].transaction_patterns == ["structuring"]
    assert reloaded[1].key_terms == ["cash", "CTR avoidance"]


def test_missing_metadata_fields_detects_absent_regulator_and_date():
    source = RedFlagSource(id="reg-missing-01", description="No regulator or date")

    missing = missing_metadata_fields(source)

    assert "regulator" in missing
    assert "regulator_jurisdiction" not in missing
    assert "issued_date" in missing


def test_complete_metadata_with_regulator_and_date_does_not_trigger_tagger():
    source = RedFlagSource(
        id="reg-complete-01",
        description="Fully enriched record with regulator and date",
        product_types=["depository"],
        industry_types=["retail"],
        customer_profiles=["cash_intensive_business"],
        geographic_footprints=["domestic_us"],
        regulatory_source="FinCEN Alert FIN-2022-Alert001",
        risk_level="high",
        category="structuring",
        typology_family=["fraud_proceeds"],
        transaction_patterns=["structuring"],
        key_terms=["cash deposit"],
        regulator="FinCEN",
        issued_date="2022-03-07",
    )

    def tagger(_source: RedFlagSource, _missing: list[str]) -> dict:
        raise AssertionError("tagger should not be called for complete metadata")

    records, enriched_count = build_records([source], embedding_model=FakeModel(), tagger=tagger)

    assert enriched_count == 0
    assert records[0].regulator == "FinCEN"
    assert records[0].regulator_jurisdiction == "US"
    assert records[0].issued_date == "2022-03-07"


def test_tagger_enriches_missing_regulator():
    source = RedFlagSource(
        id="reg-enrich-01",
        description="FATF guidance on virtual assets",
        product_types=["crypto"],
        industry_types=["crypto"],
        customer_profiles=["cross_border_business"],
        geographic_footprints=["domestic_us"],
        regulatory_source="FATF Guidance on Virtual Assets",
        risk_level="high",
        category="sanctions_evasion",
        typology_family=["crypto_asset_money_laundering"],
        transaction_patterns=["cryptocurrency_mixing"],
        key_terms=["virtual asset", "VASP"],
        issued_date="2021-10",
    )

    def tagger(_source: RedFlagSource, missing: list[str]) -> dict:
        assert "regulator" in missing
        assert "regulator_jurisdiction" not in missing
        return {"regulator": "FATF"}

    records, enriched_count = build_records([source], embedding_model=FakeModel(), tagger=tagger)

    assert enriched_count == 1
    assert records[0].regulator == "FATF"
    assert records[0].regulator_jurisdiction == "FATF"


def test_ingest_derives_regulator_jurisdiction_without_tagger_request():
    source = RedFlagSource(
        id="fr-reg-01",
        description="AMF red flag",
        product_types=["securities"],
        industry_types=["professional_services"],
        customer_profiles=["cross_border_business"],
        geographic_footprints=["uk_eu"],
        regulatory_source="AMF France guidance",
        risk_level="medium",
        category="layering",
        typology_family=["fraud_proceeds"],
        transaction_patterns=["rapid_fund_movement"],
        key_terms=["AMF"],
        regulator="AMF-France",
        regulator_jurisdiction="US",
        issued_date="2025",
    )

    def tagger(_source: RedFlagSource, _missing: list[str]) -> dict:
        raise AssertionError("jurisdiction derivation must not trigger tagger")

    records, enriched_count = build_records([source], embedding_model=FakeModel(), tagger=tagger)

    assert enriched_count == 0
    assert records[0].regulator_jurisdiction == "FR"


def test_ingest_logs_warning_for_unmapped_regulator_jurisdiction(caplog):
    source = RedFlagSource(
        id="unknown-reg-01",
        description="Unknown regulator record",
        regulator="SomeUnknownAgency",
    )

    with caplog.at_level(logging.WARNING):
        records, _ = build_records([source], embedding_model=FakeModel())

    assert records[0].regulator_jurisdiction is None
    assert "has no configured regulator_jurisdiction" in caplog.text


def test_tagger_enriches_missing_issued_date():
    source = RedFlagSource(
        id="date-enrich-01",
        description="FinCEN advisory on structuring",
        product_types=["depository"],
        industry_types=["retail"],
        customer_profiles=["cash_intensive_business"],
        geographic_footprints=["domestic_us"],
        regulatory_source="FinCEN Advisory FIN-2014-A005",
        risk_level="medium",
        category="structuring",
        typology_family=["fraud_proceeds"],
        transaction_patterns=["structuring"],
        key_terms=["CTR", "cash"],
        regulator="FinCEN",
    )

    def tagger(_source: RedFlagSource, missing: list[str]) -> dict:
        assert "issued_date" in missing
        return {"issued_date": "2014-08"}

    records, enriched_count = build_records([source], embedding_model=FakeModel(), tagger=tagger)

    assert enriched_count == 1
    assert records[0].issued_date == "2014-08"


def test_warn_free_form_values_logs_for_unknown_regulator(caplog):
    from redflag_mcp.config import REGULATORS

    with caplog.at_level(logging.WARNING):
        warn_free_form_values("test-01", "regulator", ["SomeUnknownAgency"], REGULATORS)

    assert "SomeUnknownAgency" in caplog.text
    assert "regulator" in caplog.text


def test_warn_free_form_values_silent_for_known_regulator(caplog):
    from redflag_mcp.config import REGULATORS

    with caplog.at_level(logging.WARNING):
        warn_free_form_values("test-02", "regulator", ["FinCEN"], REGULATORS)

    assert caplog.text == ""


def test_write_back_does_not_occur_without_flag(tmp_path, tmp_vectors_dir):
    source_file = tmp_path / "source.yaml"
    original_content = yaml.safe_dump([{"id": "no-writeback-01", "description": "Stable"}])
    source_file.write_text(original_content)

    ingest_sources([source_file], vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    assert source_file.read_text() == original_content


def write_temp_source(
    path: Path,
    *,
    record_id: str,
    description: str = "Customer activity is suspicious.",
    regulator: str | None = None,
    risk_level: str | None = "medium",
) -> None:
    payload = {
        "id": record_id,
        "description": description,
        "product_types": ["depository"],
        "industry_types": ["retail"],
        "customer_profiles": ["cash_intensive_business"],
        "geographic_footprints": ["domestic_us"],
        "regulatory_source": "FinCEN Alert",
        "risk_level": risk_level,
        "category": "structuring",
        "issued_date": "2025",
        "typology_family": ["fraud_proceeds"],
        "transaction_patterns": ["structuring"],
        "key_terms": ["cash"],
    }
    if regulator:
        payload["regulator"] = regulator
    path.write_text(yaml.safe_dump([payload], sort_keys=False))


def test_select_write_back_paths_defaults_to_visible_yaml_files(tmp_path):
    first = tmp_path / "001_first.yaml"
    second = tmp_path / "002_second.yaml"
    hidden = tmp_path / ".extracted_sources.yaml"
    first.write_text("[]")
    second.write_text("[]")
    hidden.write_text("[]")

    paths = select_write_back_paths(None, source_dir=tmp_path)

    assert paths == [first, second]


def test_select_write_back_paths_preserves_explicit_multiple_sources(tmp_path):
    first = tmp_path / "001_first.yaml"
    second = tmp_path / "002_second.yaml"
    first.write_text("[]")
    second.write_text("[]")

    paths = select_write_back_paths([second, first], source_dir=tmp_path)

    assert paths == [second, first]


def test_filter_source_paths_by_range_uses_leading_serial_prefix(tmp_path):
    paths = [
        tmp_path / "001_first.yaml",
        tmp_path / "002_second.yaml",
        tmp_path / "010_tenth.yaml",
        tmp_path / "no-prefix.yaml",
    ]

    filtered = filter_source_paths_by_range(paths, (1, 2))

    assert filtered == paths[:2]


def test_parse_serial_range_rejects_invalid_and_reversed_ranges():
    assert parse_serial_range("001-003") == (1, 3)

    for value in ("001", "abc-def"):
        with pytest.raises(ValueError, match="format NNN-NNN"):
            parse_serial_range(value)

    with pytest.raises(ValueError, match="start must be <= end"):
        parse_serial_range("005-001")


def test_run_write_back_yaml_enriches_multiple_explicit_sources(tmp_path):
    first = tmp_path / "001_first.yaml"
    second = tmp_path / "002_second.yaml"
    write_temp_source(first, record_id="first-01")
    write_temp_source(second, record_id="second-01", regulator="FinCEN")

    def tagger(_source: RedFlagSource, missing: list[str]) -> dict:
        assert "regulator_jurisdiction" not in missing
        if "regulator" in missing:
            return {"regulator": "FinCEN"}
        return {}

    summary = run_write_back_yaml([first, second], tagger=tagger)
    first_record = yaml.safe_load(first.read_text())[0]
    second_record = yaml.safe_load(second.read_text())[0]

    assert summary.source_files == 2
    assert summary.valid_records == 2
    assert summary.enriched_records == 1
    assert first_record["regulator"] == "FinCEN"
    assert first_record["regulator_jurisdiction"] == "US"
    assert second_record["regulator_jurisdiction"] == "US"


def test_run_write_back_yaml_parallel_processes_each_file_once(tmp_path):
    files = [tmp_path / f"{index:03d}_source.yaml" for index in range(1, 4)]
    for index, path in enumerate(files, start=1):
        write_temp_source(path, record_id=f"source-{index:02d}")

    def tagger(_source: RedFlagSource, missing: list[str]) -> dict:
        assert "regulator" in missing
        return {"regulator": "FinCEN"}

    summary = run_write_back_yaml(files, tagger=tagger, workers=2)

    assert summary.source_files == 3
    assert summary.valid_records == 3
    assert summary.enriched_records == 3
    for path in files:
        records = yaml.safe_load(path.read_text())
        assert len(records) == 1
        assert records[0]["regulator"] == "FinCEN"
        assert records[0]["regulator_jurisdiction"] == "US"


def test_run_write_back_yaml_preserves_existing_metadata(tmp_path):
    source_file = tmp_path / "001_existing.yaml"
    write_temp_source(source_file, record_id="existing-01", regulator="FinCEN")

    def tagger(_source: RedFlagSource, _missing: list[str]) -> dict:
        raise AssertionError("tagger should not be called for complete metadata")

    run_write_back_yaml([source_file], tagger=tagger)

    record = yaml.safe_load(source_file.read_text())[0]
    assert record["regulator"] == "FinCEN"
    assert record["regulator_jurisdiction"] == "US"
