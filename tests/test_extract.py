"""Tests for scripts/extract.py"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Add scripts and src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

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
    CUSTOMER_PROFILES,
    GEOGRAPHIC_FOOTPRINTS,
    INDUSTRY_TYPES,
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

        assert "oil_and_gas" in INDUSTRY_TYPES
        assert "oil_and_gas" in system_prompt
        assert "shell_or_front_company" in CUSTOMER_PROFILES
        assert "shell_or_front_company" in system_prompt
        assert "southwest_border" in GEOGRAPHIC_FOOTPRINTS
        assert "southwest_border" in system_prompt


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
