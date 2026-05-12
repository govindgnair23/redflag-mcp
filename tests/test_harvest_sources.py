"""Tests for scripts/harvest_sources.py"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from harvest_sources import (
    classify_url,
    fetch_pdf,
    fetch_web,
    head_is_pdf,
    heuristic_is_pdf,
    is_blank_or_invalid,
    load_registry,
    main,
    next_serial,
    write_registry,
)


# ---------------------------------------------------------------------------
# load_registry / write_registry / next_serial
# ---------------------------------------------------------------------------


class TestLoadRegistry:
    def test_loads_existing_registry(self, tmp_path):
        sources_yaml = tmp_path / "sources.yaml"
        sources_yaml.write_text(
            "'001':\n  url: https://example.com/a.pdf\n"
            "'002':\n  url: https://example.com/b.pdf\n"
        )
        registry, urls = load_registry(sources_yaml)
        assert registry == {
            "001": {"url": "https://example.com/a.pdf"},
            "002": {"url": "https://example.com/b.pdf"},
        }
        assert urls == {"https://example.com/a.pdf", "https://example.com/b.pdf"}

    def test_missing_file_returns_empty(self, tmp_path):
        registry, urls = load_registry(tmp_path / "nonexistent.yaml")
        assert registry == {}
        assert urls == set()

    def test_empty_file_returns_empty(self, tmp_path):
        sources_yaml = tmp_path / "sources.yaml"
        sources_yaml.write_text("")
        registry, urls = load_registry(sources_yaml)
        assert registry == {}
        assert urls == set()


class TestWriteRegistry:
    def test_round_trip(self, tmp_path):
        sources_yaml = tmp_path / "sources.yaml"
        original = {
            "001": {"url": "https://example.com/a.pdf"},
            "038": {"url": "https://example.com/z.pdf"},
        }
        write_registry(original, sources_yaml)
        registry, urls = load_registry(sources_yaml)
        assert registry == original
        assert "https://example.com/a.pdf" in urls
        assert "https://example.com/z.pdf" in urls

    def test_keys_are_sorted(self, tmp_path):
        sources_yaml = tmp_path / "sources.yaml"
        write_registry(
            {"038": {"url": "https://z.com"}, "001": {"url": "https://a.com"}},
            sources_yaml,
        )
        content = sources_yaml.read_text()
        assert content.index("001") < content.index("038")


class TestNextSerial:
    def test_non_empty_registry(self):
        assert next_serial({"038": {"url": "x"}, "001": {"url": "y"}}) == 39

    def test_empty_registry(self):
        assert next_serial({}) == 1

    def test_single_entry(self):
        assert next_serial({"005": {"url": "x"}}) == 6


# ---------------------------------------------------------------------------
# is_blank_or_invalid
# ---------------------------------------------------------------------------


class TestIsBlankOrInvalid:
    def test_blank_string(self):
        assert is_blank_or_invalid("") is True

    def test_whitespace_only(self):
        assert is_blank_or_invalid("   ") is True

    def test_relative_path(self):
        assert is_blank_or_invalid("not-a-url") is True

    def test_ftp_url(self):
        assert is_blank_or_invalid("ftp://example.com/file.pdf") is True

    def test_http_url(self):
        assert is_blank_or_invalid("http://example.com") is False

    def test_https_url(self):
        assert is_blank_or_invalid("https://example.com/page") is False


# ---------------------------------------------------------------------------
# heuristic_is_pdf
# ---------------------------------------------------------------------------


class TestHeuristicIsPdf:
    def test_pdf_extension(self):
        assert heuristic_is_pdf("https://example.com/doc.pdf") is True

    def test_pdf_extension_uppercase(self):
        assert heuristic_is_pdf("https://example.com/doc.PDF") is True

    def test_pdf_extension_with_query(self):
        # Query string doesn't affect path check
        assert heuristic_is_pdf("https://example.com/doc.pdf?v=1") is True

    def test_ofac_download_with_inline_param(self):
        assert (
            heuristic_is_pdf("https://ofac.treasury.gov/media/934236/download?inline=")
            is True
        )

    def test_ofac_download_bare(self):
        assert (
            heuristic_is_pdf("https://ofac.treasury.gov/media/912981/download?inline")
            is True
        )

    def test_ofac_download_no_params(self):
        assert (
            heuristic_is_pdf("https://ofac.treasury.gov/media/123/download")
            is True
        )

    def test_nca_file_path(self):
        assert heuristic_is_pdf("https://nationalcrimeagency.gov.uk/alerts/123/file") is True

    def test_plain_web_page(self):
        assert heuristic_is_pdf("https://example.com/page/report") is False

    def test_recent_actions_url(self):
        assert heuristic_is_pdf("https://ofac.treasury.gov/recent-actions/20250320") is False


# ---------------------------------------------------------------------------
# head_is_pdf
# ---------------------------------------------------------------------------


class TestHeadIsPdf:
    def _make_client(self, content_type: str) -> httpx.Client:
        mock_client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.headers = {"content-type": content_type}
        mock_client.head.return_value = mock_response
        return mock_client

    def test_application_pdf(self):
        client = self._make_client("application/pdf")
        assert head_is_pdf("https://example.com/doc", client) is True

    def test_application_pdf_with_charset(self):
        client = self._make_client("application/pdf; charset=binary")
        assert head_is_pdf("https://example.com/doc", client) is True

    def test_text_html(self):
        client = self._make_client("text/html; charset=utf-8")
        assert head_is_pdf("https://example.com/page", client) is False

    def test_timeout_returns_false(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.head.side_effect = httpx.TimeoutException("timed out")
        assert head_is_pdf("https://example.com/doc", mock_client) is False

    def test_http_error_returns_false(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.head.side_effect = httpx.HTTPError("connection error")
        assert head_is_pdf("https://example.com/doc", mock_client) is False


# ---------------------------------------------------------------------------
# classify_url
# ---------------------------------------------------------------------------


class TestClassifyUrl:
    def test_heuristic_pdf_no_head_needed(self):
        mock_client = MagicMock(spec=httpx.Client)
        assert classify_url("https://example.com/report.pdf", mock_client) == "pdf"
        mock_client.head.assert_not_called()

    def test_head_fallback_pdf(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/pdf"}
        mock_client.head.return_value = mock_response
        assert classify_url("https://example.com/report", mock_client) == "pdf"

    def test_head_fallback_web(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "text/html"}
        mock_client.head.return_value = mock_response
        assert classify_url("https://example.com/page", mock_client) == "web"

    def test_head_timeout_classifies_as_web(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.head.side_effect = httpx.TimeoutException("timed out")
        assert classify_url("https://example.com/unknown", mock_client) == "web"


# ---------------------------------------------------------------------------
# fetch_pdf
# ---------------------------------------------------------------------------


class TestFetchPdf:
    def test_success_writes_bytes(self, tmp_path):
        mock_client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.content = b"%PDF-1.4 binary content"
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        dest = tmp_path / "001.pdf"
        result = fetch_pdf("https://example.com/report.pdf", dest, mock_client)

        assert result == len(b"%PDF-1.4 binary content")
        assert dest.read_bytes() == b"%PDF-1.4 binary content"
        mock_client.get.assert_called_once_with(
            "https://example.com/report.pdf", follow_redirects=True, timeout=60.0
        )

    def test_http_error_propagates(self, tmp_path):
        mock_client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock()
        )
        mock_client.get.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            fetch_pdf("https://example.com/doc.pdf", tmp_path / "001.pdf", mock_client)

    def test_timeout_propagates(self, tmp_path):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.side_effect = httpx.TimeoutException("timed out")

        with pytest.raises(httpx.TimeoutException):
            fetch_pdf("https://example.com/doc.pdf", tmp_path / "001.pdf", mock_client)


# ---------------------------------------------------------------------------
# fetch_web
# ---------------------------------------------------------------------------


class TestFetchWeb:
    def test_success_writes_markdown(self, tmp_path):
        mock_client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.text = "# Report\n\nSome content here."
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        dest = tmp_path / "001.md"
        result = fetch_web("https://example.com/page", dest, mock_client)

        assert result == len("# Report\n\nSome content here.")
        assert dest.read_text(encoding="utf-8") == "# Report\n\nSome content here."
        # Verify Jina Reader URL construction
        mock_client.get.assert_called_once_with(
            "https://r.jina.ai/https://example.com/page",
            follow_redirects=True,
            timeout=30.0,
        )

    def test_empty_response_raises(self, tmp_path):
        mock_client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.text = "   "
        mock_response.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_response

        with pytest.raises(ValueError, match="empty content"):
            fetch_web("https://example.com/page", tmp_path / "001.md", mock_client)

    def test_http_error_propagates(self, tmp_path):
        mock_client = MagicMock(spec=httpx.Client)
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=MagicMock()
        )
        mock_client.get.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            fetch_web("https://example.com/page", tmp_path / "001.md", mock_client)


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------


def _make_csv(tmp_path: Path, rows: list[dict]) -> Path:
    csv_path = tmp_path / "catalog.csv"
    fieldnames = ["Region", "Direct URL", "Document Title"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def _make_registry(tmp_path: Path, entries: dict) -> Path:
    registry_path = tmp_path / "sources.yaml"
    if entries:
        with open(registry_path, "w") as f:
            yaml.dump(entries, f, default_flow_style=False, sort_keys=True)
    return registry_path


class TestMainIntegration:
    def test_happy_path(self, tmp_path, monkeypatch):
        """1 PDF, 1 web URL, 1 already-registered → 2 new entries, 1 skipped."""
        pdf_url = "https://example.com/report.pdf"
        web_url = "https://example.com/page"
        existing_url = "https://example.com/existing"

        registry_path = _make_registry(
            tmp_path, {"001": {"url": existing_url}}
        )
        csv_path = _make_csv(
            tmp_path,
            [
                {"Region": "US", "Direct URL": pdf_url, "Document Title": "PDF"},
                {"Region": "US", "Direct URL": web_url, "Document Title": "Web"},
                {"Region": "US", "Direct URL": existing_url, "Document Title": "Existing"},
            ],
        )
        pdfs_dir = tmp_path / "pdf"
        markdown_dir = tmp_path / "markdown"

        monkeypatch.setattr("harvest_sources.SOURCES_YAML", registry_path)
        monkeypatch.setattr("harvest_sources.PDFS_DIR", pdfs_dir)
        monkeypatch.setattr("harvest_sources.MARKDOWN_DIR", markdown_dir)

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "r.jina.ai" in url:
                resp.text = "# Markdown content"
                resp.content = b""
            else:
                resp.content = b"%PDF-binary"
                resp.text = ""
            return resp

        with patch("harvest_sources.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = mock_get
            mock_client.head.return_value = MagicMock(
                headers={"content-type": "text/html"}
            )
            mock_client_cls.return_value = mock_client

            main([str(csv_path)])

        # Verify files created
        assert (pdfs_dir / "002.pdf").exists()
        assert (markdown_dir / "003.md").exists()

        # Verify registry updated
        registry, urls = load_registry(registry_path)
        assert len(registry) == 3
        assert registry["002"] == {"url": pdf_url}
        assert registry["003"] == {"url": web_url}
        assert existing_url in urls

    def test_idempotent_second_run(self, tmp_path, monkeypatch):
        """Re-running the same CSV produces zero new entries."""
        url1 = "https://example.com/report.pdf"
        url2 = "https://example.com/page"

        registry_path = _make_registry(
            tmp_path,
            {"001": {"url": url1}, "002": {"url": url2}},
        )
        csv_path = _make_csv(
            tmp_path,
            [
                {"Region": "US", "Direct URL": url1, "Document Title": "PDF"},
                {"Region": "US", "Direct URL": url2, "Document Title": "Web"},
            ],
        )

        monkeypatch.setattr("harvest_sources.SOURCES_YAML", registry_path)
        monkeypatch.setattr("harvest_sources.PDFS_DIR", tmp_path / "pdf")
        monkeypatch.setattr("harvest_sources.MARKDOWN_DIR", tmp_path / "markdown")

        with patch("harvest_sources.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            main([str(csv_path)])

            # No GET/HEAD calls should have been made (all skipped)
            mock_client.get.assert_not_called()
            mock_client.head.assert_not_called()

        registry, _ = load_registry(registry_path)
        assert len(registry) == 2

    def test_missing_direct_url_column(self, tmp_path, monkeypatch, capsys):
        """CSV without 'Direct URL' column exits with code 1."""
        csv_path = tmp_path / "bad.csv"
        csv_path.write_text("Region,Document Title\nUS,Report\n")

        monkeypatch.setattr("harvest_sources.SOURCES_YAML", tmp_path / "sources.yaml")
        monkeypatch.setattr("harvest_sources.PDFS_DIR", tmp_path / "pdf")
        monkeypatch.setattr("harvest_sources.MARKDOWN_DIR", tmp_path / "markdown")

        with patch("harvest_sources.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(SystemExit) as exc_info:
                main([str(csv_path)])

        assert exc_info.value.code == 1

    def test_failed_url_does_not_increment_serial(self, tmp_path, monkeypatch):
        """A 404 URL is logged, not registered; subsequent URLs use the same serial slot."""
        fail_url = "https://example.com/bad.pdf"
        good_url = "https://example.com/good.pdf"

        registry_path = _make_registry(tmp_path, {"001": {"url": "https://existing.com"}})
        csv_path = _make_csv(
            tmp_path,
            [
                {"Region": "US", "Direct URL": fail_url, "Document Title": "Bad"},
                {"Region": "US", "Direct URL": good_url, "Document Title": "Good"},
            ],
        )

        monkeypatch.setattr("harvest_sources.SOURCES_YAML", registry_path)
        monkeypatch.setattr("harvest_sources.PDFS_DIR", tmp_path / "pdf")
        monkeypatch.setattr("harvest_sources.MARKDOWN_DIR", tmp_path / "markdown")

        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if call_count == 1:
                # First call fails
                resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                    "404", request=MagicMock(), response=MagicMock()
                )
            else:
                resp.content = b"%PDF-binary"
            return resp

        with patch("harvest_sources.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = mock_get
            mock_client_cls.return_value = mock_client

            main([str(csv_path)])

        registry, _ = load_registry(registry_path)
        # Only one new entry (the good URL), key 002
        assert "002" in registry
        assert registry["002"] == {"url": good_url}
        assert fail_url not in {e["url"] for e in registry.values()}

    def test_blank_url_is_skipped(self, tmp_path, monkeypatch):
        """A blank Direct URL field is skipped with a warning."""
        registry_path = _make_registry(tmp_path, {})
        csv_path = _make_csv(
            tmp_path,
            [{"Region": "US", "Direct URL": "   ", "Document Title": "Blank"}],
        )

        monkeypatch.setattr("harvest_sources.SOURCES_YAML", registry_path)
        monkeypatch.setattr("harvest_sources.PDFS_DIR", tmp_path / "pdf")
        monkeypatch.setattr("harvest_sources.MARKDOWN_DIR", tmp_path / "markdown")

        with patch("harvest_sources.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client

            main([str(csv_path)])
            mock_client.get.assert_not_called()

        registry, _ = load_registry(registry_path)
        assert len(registry) == 0

    def test_jina_empty_response_is_failed(self, tmp_path, monkeypatch):
        """Jina returning empty text logs a failure; no markdown file written."""
        web_url = "https://example.com/blocked-page"

        registry_path = _make_registry(tmp_path, {})
        csv_path = _make_csv(
            tmp_path,
            [{"Region": "US", "Direct URL": web_url, "Document Title": "Blocked"}],
        )

        monkeypatch.setattr("harvest_sources.SOURCES_YAML", registry_path)
        monkeypatch.setattr("harvest_sources.PDFS_DIR", tmp_path / "pdf")
        monkeypatch.setattr("harvest_sources.MARKDOWN_DIR", tmp_path / "markdown")

        def mock_get(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.text = "   "  # empty
            resp.content = b""
            return resp

        with patch("harvest_sources.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = mock_get
            mock_client.head.return_value = MagicMock(
                headers={"content-type": "text/html"}
            )
            mock_client_cls.return_value = mock_client

            main([str(csv_path)])

        registry, _ = load_registry(registry_path)
        assert len(registry) == 0
        assert not (tmp_path / "markdown" / "001.md").exists()
