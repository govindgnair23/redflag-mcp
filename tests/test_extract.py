"""Tests for scripts/extract.py"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Add scripts and src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import extract
from extract import (
    build_extraction_prompt,
    extract_text_from_pdf,
    extract_text_from_url,
    is_already_processed,
    load_manifest,
    save_manifest,
    slugify,
    source_slug,
    validate_and_build_entries,
    write_yaml,
)
from redflag_mcp.config import (
    CATEGORIES,
    CUSTOMER_PROFILES,
    GEOGRAPHIC_FOOTPRINTS,
    INDUSTRY_TYPES,
    PRODUCT_TYPES,
    REGULATOR_JURISDICTIONS,
    REGULATORS,
    jurisdiction_for_regulator,
)
from redflag_mcp.models import RedFlagSource


class TestBuildExtractionPrompt:
    def test_prompt_contains_rich_metadata_fields(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "industry_types" in system_prompt
        assert "customer_profiles" in system_prompt
        assert "geographic_footprints" in system_prompt

    def test_prompt_contains_representative_rich_metadata_values(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "depository" in PRODUCT_TYPES
        assert "depository" in system_prompt
        assert "trade_based_money_laundering" in CATEGORIES
        assert "trade_based_money_laundering" in system_prompt
        assert "trade_based_ml" not in system_prompt
        assert "oil_and_gas" in INDUSTRY_TYPES
        assert "oil_and_gas" in system_prompt
        assert "shell_or_front_company" in CUSTOMER_PROFILES
        assert "shell_or_front_company" in system_prompt
        assert "southwest_border" in GEOGRAPHIC_FOOTPRINTS
        assert "southwest_border" in system_prompt
        for regulator in ("AMLA", "ESMA", "MAS", "HKMA", "ASIC", "APRA"):
            assert regulator in REGULATORS
            assert regulator in system_prompt

    def test_regulator_jurisdiction_is_not_llm_extracted(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "regulator_jurisdiction" in system_prompt
        assert "Do not emit regulator_jurisdiction" in system_prompt

    def test_prompt_extracts_implicit_red_flags_from_case_narratives(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "Implicit red flags in case narratives" in system_prompt
        assert "discrepancy in Customer G's business activity between the FI's records and corporate registry" in system_prompt
        assert "Enforcement actions and historical cases are excluded only when" in system_prompt

    def test_prompt_prioritizes_explicit_red_flag_sections(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "Explicit section precedence" in system_prompt
        assert "extract only from those explicit sections" in system_prompt
        assert "Indicia of Sham Transactions" in system_prompt

    def test_prompt_scopes_implicit_extraction_to_docs_without_explicit_sections(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "Use implicit red flag extraction only when the document has no explicit red-flag, risk-factor, or indicator section" in system_prompt
        assert "When an explicit section exists, ignore narrative examples, typology examples, enforcement narratives, and case studies outside that section" in system_prompt

    def test_prompt_rejects_person_specific_examples_as_red_flags(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "A blocked oligarch transferred ownership of his private jet to a trust" in system_prompt
        assert "Kerimov used a series of legal structures" in system_prompt
        assert "Do not extract named persons, named companies, enforcement targets, or one-off factual examples as red flags" in system_prompt

    def test_prompt_rejects_dependent_explanatory_sentences_as_standalone_flags(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "Such family members or close associates may be acting as a proxy, facilitator, money manager, or agent for the blocked person" in system_prompt
        assert "Do not extract dependent explanatory sentences as standalone red flags" in system_prompt

    def test_prompt_preserves_one_explicit_bullet_as_one_risk_factor(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "One explicit bullet or risk-factor heading equals one red flag" in system_prompt
        assert "Do not split later sentences under the same bullet into separate red flags" in system_prompt
        assert "Formal or informal agreements, agent-principal or other close relationships" in system_prompt

    def test_prompt_requires_descriptions_to_begin_with_noun_subject(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "Description subject grammar" in system_prompt
        assert "Descriptions must begin with a noun subject" in system_prompt
        assert '"Transactions"' in system_prompt
        assert "Entities or individuals are non-responsive or refuse to provide additional transaction information" in system_prompt

    def test_prompt_excludes_compliance_control_guidance(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "Compliance guidance exclusion" in system_prompt
        assert "Do not extract institutional compliance obligations, program components, control expectations, risk assessment processes, policies, procedures, training, governance, audit/testing, remediation, recordkeeping, escalation, reporting, or sanctions compliance framework elements" in system_prompt
        assert "A compliance framework document can validly produce zero red flags" in system_prompt

    def test_prompt_rejects_ofac_framework_control_examples(self):
        messages = build_extraction_prompt("Document text")
        system_prompt = messages[0]["content"]

        assert "The organization conducts, or will conduct, an OFAC risk assessment" in system_prompt
        assert "The organization develops a sanctions risk rating" in system_prompt
        assert "The organization has implemented internal controls" in system_prompt
        assert "The organization commits to providing OFAC-related training" in system_prompt
        assert "The organization ensures that its OFAC-related recordkeeping policies" in system_prompt

    def test_representative_regulator_jurisdiction_mappings(self):
        expected = {
            "FinCEN": "US",
            "AMF-France": "FR",
            "ACPR": "FR",
            "MAS": "SG",
            "AUSTRAC": "AU",
            "ASIC": "AU",
            "APRA": "AU",
            "FCA": "GB",
            "AMLA": "EU",
            "ESMA": "EU",
        }

        for regulator, jurisdiction in expected.items():
            assert REGULATOR_JURISDICTIONS[regulator] == jurisdiction
            assert jurisdiction_for_regulator(regulator) == jurisdiction


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World") == "hello-world"

    def test_special_characters(self):
        assert slugify("FinCEN Alert (2022)") == "fincen-alert-2022"

    def test_multiple_spaces_and_hyphens(self):
        assert slugify("foo  --  bar") == "foo-bar"

    def test_preserves_numbers(self):
        assert slugify("Section 508") == "section-508"


class TestSourceSlug:
    def test_pdf_filename(self):
        slug = source_slug("FinCEN Alert Russian Sanctions Evasion FINAL 508.pdf")
        assert slug == "fincen-alert-russian-sanctions-evasion-final-508"

    def test_pdf_path(self):
        slug = source_slug("/some/path/document.pdf")
        assert slug == "document"

    def test_url_with_path(self):
        slug = source_slug("https://bsaaml.ffiec.gov/manual/Appendices/07")
        assert slug == "bsaaml-manual-appendices-07"

    def test_url_domain_only(self):
        slug = source_slug("https://example.com/")
        assert slug == "example"


class TestExtractTextFromPdf:
    def test_extracts_text_from_fincen_pdf(self):
        pdf_path = Path(__file__).resolve().parent.parent / "red_flag_sources" / "pdf" / "FinCEN Alert Russian Sanctions Evasion FINAL 508.pdf"
        if not pdf_path.exists():
            pytest.skip("FinCEN PDF not available")
        text = extract_text_from_pdf(str(pdf_path))
        assert len(text) > 1000
        assert "FinCEN" in text
        assert "red flag" in text.lower() or "Red Flag" in text


class TestExtractTextFromUrl:
    def test_strips_html_tags(self):
        html = "<html><body><h1>Title</h1><p>Content here</p><script>var x=1;</script></body></html>"
        with patch("extract.httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = html
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            text = extract_text_from_url("https://example.com")
            assert "Title" in text
            assert "Content here" in text
            assert "var x=1" not in text


class TestValidateAndBuildEntries:
    def test_valid_entries(self):
        raw = [
            {
                "description": "Multiple cash deposits under $10,000",
                "product_types": ["depository"],
                "risk_level": "high",
                "category": "structuring",
                "regulatory_source": "FinCEN Alert",
            },
            {
                "description": "Wire transfers with missing originator info",
                "product_types": ["correspondent_banking"],
                "risk_level": "medium",
                "category": "sanctions_evasion",
                "regulatory_source": "FinCEN Alert",
            },
        ]
        entries, skipped = validate_and_build_entries(raw, "test-source")
        assert len(entries) == 2
        assert skipped == 0
        assert entries[0]["id"] == "test-source-01"
        assert entries[1]["id"] == "test-source-02"

    def test_valid_entries_with_rich_metadata(self):
        raw = [
            {
                "description": "A small oil company sends wires for hazardous materials.",
                "product_types": ["depository", "trade_finance"],
                "industry_types": ["oil_and_gas"],
                "customer_profiles": ["small_business"],
                "geographic_footprints": ["southwest_border", "mexico"],
                "risk_level": "medium",
                "category": "fraud_nexus",
                "regulatory_source": "FinCEN Alert",
            }
        ]

        entries, skipped = validate_and_build_entries(raw, "rich")

        assert skipped == 0
        assert entries[0]["industry_types"] == ["oil_and_gas"]
        assert entries[0]["customer_profiles"] == ["small_business"]
        assert entries[0]["geographic_footprints"] == ["southwest_border", "mexico"]

    def test_invalid_risk_level_skipped(self):
        raw = [
            {
                "description": "Valid entry",
                "risk_level": "high",
            },
            {
                "description": "Invalid entry",
                "risk_level": "critical",  # not a valid risk level
            },
        ]
        entries, skipped = validate_and_build_entries(raw, "test")
        assert len(entries) == 1
        assert skipped == 1
        assert entries[0]["id"] == "test-01"

    def test_minimal_entry(self):
        raw = [{"description": "A red flag with no metadata"}]
        entries, skipped = validate_and_build_entries(raw, "minimal")
        assert len(entries) == 1
        assert skipped == 0
        assert entries[0]["id"] == "minimal-01"
        assert entries[0]["description"] == "A red flag with no metadata"

    def test_id_sequence_numbering(self):
        raw = [{"description": f"Flag {i}"} for i in range(15)]
        entries, _ = validate_and_build_entries(raw, "seq")
        assert entries[0]["id"] == "seq-01"
        assert entries[9]["id"] == "seq-10"
        assert entries[14]["id"] == "seq-15"

    def test_regulator_jurisdiction_is_derived_from_regulator(self):
        raw = [
            {
                "description": "French regulator identifies suspicious securities activity.",
                "regulator": "AMF-France",
                "regulator_jurisdiction": "US",
                "risk_level": "medium",
            }
        ]

        entries, skipped = validate_and_build_entries(raw, "france")

        assert skipped == 0
        assert entries[0]["regulator"] == "AMF-France"
        assert entries[0]["regulator_jurisdiction"] == "FR"


class TestWriteYaml:
    def test_writes_valid_yaml(self, tmp_path):
        entries = [
            {
                "id": "test-01",
                "description": "Test red flag",
                "product_types": ["depository"],
                "risk_level": "high",
            }
        ]
        output = tmp_path / "test.yaml"
        write_yaml(entries, output)

        assert output.exists()
        loaded = yaml.safe_load(output.read_text())
        assert len(loaded) == 1
        assert loaded[0]["id"] == "test-01"

    def test_output_validates_against_schema(self, tmp_path):
        entries = [
            {
                "id": "test-01",
                "description": "Structuring deposits",
                "product_types": ["depository", "credit_union"],
                "regulatory_source": "FinCEN Alert",
                "risk_level": "high",
                "category": "structuring",
            }
        ]
        output = tmp_path / "test.yaml"
        write_yaml(entries, output)

        loaded = yaml.safe_load(output.read_text())
        for entry in loaded:
            RedFlagSource(**entry)  # Should not raise

    def test_creates_parent_directory(self, tmp_path):
        output = tmp_path / "nested" / "dir" / "test.yaml"
        write_yaml([{"id": "t-01", "description": "test"}], output)
        assert output.exists()


class TestManifest:
    def test_load_manifest_missing_file(self, tmp_path):
        with patch("extract.MANIFEST_PATH", tmp_path / "nonexistent.yaml"):
            result = load_manifest()
        assert result == []

    def test_save_and_load_roundtrip(self, tmp_path):
        manifest_path = tmp_path / ".extracted_sources.yaml"
        manifest = [
            {
                "source": "test.pdf",
                "slug": "test",
                "output_file": "data/source/test.yaml",
                "extracted_at": "2026-03-26T12:00:00+00:00",
            }
        ]
        with patch("extract.MANIFEST_PATH", manifest_path):
            save_manifest(manifest)
            loaded = load_manifest()
        assert len(loaded) == 1
        assert loaded[0]["source"] == "test.pdf"
        assert loaded[0]["slug"] == "test"

    def test_is_already_processed_true(self):
        manifest = [{"source": "test.pdf"}, {"source": "https://example.com"}]
        assert is_already_processed("test.pdf", manifest) is True
        assert is_already_processed("https://example.com", manifest) is True

    def test_is_already_processed_false(self):
        manifest = [{"source": "test.pdf"}]
        assert is_already_processed("other.pdf", manifest) is False

    def test_is_already_processed_empty_manifest(self):
        assert is_already_processed("test.pdf", []) is False


class TestRegistryUpdate:
    def test_run_batch_updates_registry_once_after_new_entries(self):
        with (
            patch("extract.discover_sources", return_value=["/tmp/001.pdf"]),
            patch("extract.load_manifest", side_effect=[[], []]),
            patch("extract.load_sources_registry", return_value={}),
            patch("extract.get_source_url", return_value="https://example.gov/001.pdf"),
            patch(
                "extract.process_one",
                return_value={
                    "source": "/tmp/001.pdf",
                    "slug": "001",
                    "output_file": "data/source/001.yaml",
                    "extracted_at": "2026-05-17T12:00:00+00:00",
                },
            ),
            patch("extract.save_manifest") as mock_save_manifest,
            patch("extract.build_registry") as mock_build_registry,
        ):
            extract.run_batch(force=False, workers=None)

        mock_save_manifest.assert_called_once()
        mock_build_registry.assert_called_once_with()

    def test_run_batch_does_not_update_registry_when_nothing_changed(self):
        with (
            patch("extract.discover_sources", return_value=["/tmp/001.pdf"]),
            patch("extract.load_manifest", return_value=[{"source": "/tmp/001.pdf"}]),
            patch("extract.load_sources_registry", return_value={}),
            patch("extract.build_registry") as mock_build_registry,
        ):
            extract.run_batch(force=False, workers=None)

        mock_build_registry.assert_not_called()

    def test_run_batch_logs_registry_update_failure_without_failing_extraction(self, caplog):
        with (
            patch("extract.discover_sources", return_value=["/tmp/001.pdf"]),
            patch("extract.load_manifest", side_effect=[[], []]),
            patch("extract.load_sources_registry", return_value={}),
            patch("extract.get_source_url", return_value="https://example.gov/001.pdf"),
            patch(
                "extract.process_one",
                return_value={
                    "source": "/tmp/001.pdf",
                    "slug": "001",
                    "output_file": "data/source/001.yaml",
                    "extracted_at": "2026-05-17T12:00:00+00:00",
                },
            ),
            patch("extract.save_manifest"),
            patch("extract.build_registry", side_effect=RuntimeError("registry failed")),
        ):
            extract.run_batch(force=False, workers=None)

        assert "Failed to update registry.csv" in caplog.text

    def test_main_single_source_updates_registry_after_manifest_save(self):
        with (
            patch("extract.sys.argv", ["extract.py", "/tmp/001.pdf"]),
            patch("extract.load_manifest", return_value=[]),
            patch("extract.is_already_processed", return_value=False),
            patch("extract.load_sources_registry", return_value={}),
            patch("extract.get_source_url", return_value="https://example.gov/001.pdf"),
            patch(
                "extract.process_one",
                return_value={
                    "source": "/tmp/001.pdf",
                    "slug": "001",
                    "output_file": "data/source/001.yaml",
                    "extracted_at": "2026-05-17T12:00:00+00:00",
                },
            ),
            patch("extract.save_manifest") as mock_save_manifest,
            patch("extract.build_registry") as mock_build_registry,
        ):
            extract.main()

        mock_save_manifest.assert_called_once()
        mock_build_registry.assert_called_once_with()
