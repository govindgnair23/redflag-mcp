"""Tests for scripts/pipeline.py."""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pipeline


REGISTRY_COLUMNS = [
    "status",
    "slug",
    "document_title",
    "regulator",
    "jurisdiction",
    "issued_date",
    "source_url",
    "primary_category",
    "red_flag_count",
    "output_file",
    "extracted_at",
]


def write_status_registry(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REGISTRY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_read_urls_file_skips_blank_and_non_http_lines(tmp_path):
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "\nhttps://example.gov/a.pdf\nnot-a-url\n http://example.gov/b \nftp://bad\n",
        encoding="utf-8",
    )

    assert pipeline.read_urls_file(urls_file) == [
        "https://example.gov/a.pdf",
        "http://example.gov/b",
    ]


def test_download_sources_downloads_urls_and_updates_sources_registry(tmp_path):
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.gov/a.pdf\nhttps://example.gov/page\n", encoding="utf-8")
    sources_yaml = tmp_path / "sources.yaml"
    registry_csv = tmp_path / "registry.csv"
    pdf_dir = tmp_path / "pdf"
    markdown_dir = tmp_path / "markdown"
    write_status_registry(registry_csv, [])
    client = MagicMock()

    with (
        patch("pipeline.SOURCES_YAML", sources_yaml),
        patch("pipeline.REGISTRY_CSV", registry_csv),
        patch("pipeline.PDFS_DIR", pdf_dir),
        patch("pipeline.MARKDOWN_DIR", markdown_dir),
        patch("pipeline.classify_url", side_effect=["pdf", "web"]),
        patch("pipeline.fetch_pdf", return_value=10) as mock_fetch_pdf,
        patch("pipeline.fetch_web", return_value=20) as mock_fetch_web,
        patch("pipeline.build_registry") as mock_build_registry,
    ):
        downloaded = pipeline.download_sources(urls_file, force=False, client=client)

    assert downloaded == [
        {"key": "001", "url": "https://example.gov/a.pdf", "kind": "pdf", "path": pdf_dir / "001.pdf"},
        {"key": "002", "url": "https://example.gov/page", "kind": "web", "path": markdown_dir / "002.md"},
    ]
    mock_fetch_pdf.assert_called_once_with("https://example.gov/a.pdf", pdf_dir / "001.pdf", client)
    mock_fetch_web.assert_called_once_with("https://example.gov/page", markdown_dir / "002.md", client)
    assert yaml.safe_load(sources_yaml.read_text(encoding="utf-8")) == {
        "001": {"url": "https://example.gov/a.pdf"},
        "002": {"url": "https://example.gov/page"},
    }
    assert mock_build_registry.call_count == 2


def test_download_sources_skips_registry_duplicates_unless_forced(tmp_path):
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.gov/a.pdf\n", encoding="utf-8")
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("'001':\n  url: https://example.gov/a.pdf\n", encoding="utf-8")
    registry_csv = tmp_path / "registry.csv"
    write_status_registry(registry_csv, [{"status": "downloaded", "source_url": "https://example.gov/a.pdf"}])
    client = MagicMock()

    with (
        patch("pipeline.SOURCES_YAML", sources_yaml),
        patch("pipeline.REGISTRY_CSV", registry_csv),
        patch("pipeline.PDFS_DIR", tmp_path / "pdf"),
        patch("pipeline.MARKDOWN_DIR", tmp_path / "markdown"),
        patch("pipeline.classify_url", return_value="pdf") as mock_classify_url,
        patch("pipeline.fetch_pdf", return_value=10) as mock_fetch_pdf,
        patch("pipeline.build_registry") as mock_build_registry,
    ):
        assert pipeline.download_sources(urls_file, force=False, client=client) == []
        forced = pipeline.download_sources(urls_file, force=True, client=client)

    assert forced[0]["key"] == "001"
    assert mock_classify_url.call_count == 1
    mock_fetch_pdf.assert_called_once()
    mock_build_registry.assert_called_once()


def test_download_sources_continues_after_download_failure(tmp_path):
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text("https://example.gov/fail.pdf\nhttps://example.gov/ok.pdf\n", encoding="utf-8")
    sources_yaml = tmp_path / "sources.yaml"
    registry_csv = tmp_path / "registry.csv"
    write_status_registry(registry_csv, [])
    client = MagicMock()

    with (
        patch("pipeline.SOURCES_YAML", sources_yaml),
        patch("pipeline.REGISTRY_CSV", registry_csv),
        patch("pipeline.PDFS_DIR", tmp_path / "pdf"),
        patch("pipeline.MARKDOWN_DIR", tmp_path / "markdown"),
        patch("pipeline.classify_url", return_value="pdf"),
        patch("pipeline.fetch_pdf", side_effect=[RuntimeError("boom"), 10]),
        patch("pipeline.build_registry") as mock_build_registry,
    ):
        downloaded = pipeline.download_sources(urls_file, force=False, client=client)

    assert [item["url"] for item in downloaded] == ["https://example.gov/ok.pdf"]
    assert yaml.safe_load(sources_yaml.read_text(encoding="utf-8")) == {
        "001": {"url": "https://example.gov/ok.pdf"}
    }
    mock_build_registry.assert_called_once()


def test_extract_downloaded_sources_processes_registry_rows(tmp_path):
    registry_csv = tmp_path / "registry.csv"
    sources_yaml = tmp_path / "sources.yaml"
    pdf_dir = tmp_path / "pdf"
    markdown_dir = tmp_path / "markdown"
    pdf_dir.mkdir()
    markdown_dir.mkdir()
    (pdf_dir / "001.pdf").write_bytes(b"pdf")
    (markdown_dir / "002.md").write_text("markdown", encoding="utf-8")
    sources_yaml.write_text(
        "'001':\n  url: https://example.gov/a.pdf\n'002':\n  url: https://example.gov/page\n",
        encoding="utf-8",
    )
    write_status_registry(
        registry_csv,
        [
            {"status": "downloaded", "source_url": "https://example.gov/a.pdf"},
            {"status": "downloaded", "source_url": "https://example.gov/page"},
        ],
    )
    manifest_entry_1 = {"source": str(pdf_dir / "001.pdf"), "output_file": "data/source/001.yaml"}
    manifest_entry_2 = {"source": str(markdown_dir / "002.md"), "output_file": "data/source/002.yaml"}

    with (
        patch("pipeline.REGISTRY_CSV", registry_csv),
        patch("pipeline.SOURCES_YAML", sources_yaml),
        patch("pipeline.PDFS_DIR", pdf_dir),
        patch("pipeline.MARKDOWN_DIR", markdown_dir),
        patch("pipeline.load_manifest", return_value=[]),
        patch("pipeline.process_one", side_effect=[manifest_entry_1, manifest_entry_2]) as mock_process_one,
        patch("pipeline.save_manifest") as mock_save_manifest,
        patch("pipeline.build_registry") as mock_build_registry,
    ):
        entries = pipeline.extract_downloaded_sources(force=False, workers=None)

    assert entries == [manifest_entry_1, manifest_entry_2]
    assert [call.args[0] for call in mock_process_one.call_args_list] == [
        str(pdf_dir / "001.pdf"),
        str(markdown_dir / "002.md"),
    ]
    mock_save_manifest.assert_called_once_with([manifest_entry_1, manifest_entry_2])
    mock_build_registry.assert_called_once_with()


def test_extract_downloaded_sources_handles_no_downloaded_rows(tmp_path):
    registry_csv = tmp_path / "registry.csv"
    sources_yaml = tmp_path / "sources.yaml"
    sources_yaml.write_text("{}\n", encoding="utf-8")
    write_status_registry(registry_csv, [{"status": "extracted", "source_url": "https://example.gov/a.pdf"}])

    with (
        patch("pipeline.REGISTRY_CSV", registry_csv),
        patch("pipeline.SOURCES_YAML", sources_yaml),
        patch("pipeline.load_manifest") as mock_load_manifest,
        patch("pipeline.build_registry") as mock_build_registry,
    ):
        assert pipeline.extract_downloaded_sources(force=False, workers=None) == []

    mock_load_manifest.assert_not_called()
    mock_build_registry.assert_not_called()


def test_extract_downloaded_sources_supports_parallel_workers(tmp_path):
    registry_csv = tmp_path / "registry.csv"
    sources_yaml = tmp_path / "sources.yaml"
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir()
    (pdf_dir / "001.pdf").write_bytes(b"pdf")
    sources_yaml.write_text("'001':\n  url: https://example.gov/a.pdf\n", encoding="utf-8")
    write_status_registry(registry_csv, [{"status": "downloaded", "source_url": "https://example.gov/a.pdf"}])
    manifest_entry = {"source": str(pdf_dir / "001.pdf"), "output_file": "data/source/001.yaml"}

    with (
        patch("pipeline.REGISTRY_CSV", registry_csv),
        patch("pipeline.SOURCES_YAML", sources_yaml),
        patch("pipeline.PDFS_DIR", pdf_dir),
        patch("pipeline.MARKDOWN_DIR", tmp_path / "markdown"),
        patch("pipeline.load_manifest", return_value=[]),
        patch("pipeline.process_one", return_value=manifest_entry),
        patch("pipeline.save_manifest"),
        patch("pipeline.build_registry"),
    ):
        assert pipeline.extract_downloaded_sources(force=False, workers=2) == [manifest_entry]


def test_extract_downloaded_sources_leaves_failed_extraction_downloaded(tmp_path):
    registry_csv = tmp_path / "registry.csv"
    sources_yaml = tmp_path / "sources.yaml"
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir()
    (pdf_dir / "001.pdf").write_bytes(b"pdf")
    sources_yaml.write_text("'001':\n  url: https://example.gov/a.pdf\n", encoding="utf-8")
    write_status_registry(registry_csv, [{"status": "downloaded", "source_url": "https://example.gov/a.pdf"}])

    with (
        patch("pipeline.REGISTRY_CSV", registry_csv),
        patch("pipeline.SOURCES_YAML", sources_yaml),
        patch("pipeline.PDFS_DIR", pdf_dir),
        patch("pipeline.MARKDOWN_DIR", tmp_path / "markdown"),
        patch("pipeline.load_manifest", return_value=[]),
        patch("pipeline.process_one", return_value=None),
        patch("pipeline.save_manifest") as mock_save_manifest,
        patch("pipeline.build_registry") as mock_build_registry,
    ):
        assert pipeline.extract_downloaded_sources(force=False, workers=None) == []

    mock_save_manifest.assert_not_called()
    mock_build_registry.assert_not_called()


def test_run_pipeline_downloads_then_extracts(tmp_path):
    urls_file = tmp_path / "urls.txt"

    with (
        patch("pipeline.download_sources", return_value=[{"url": "https://example.gov/a.pdf"}]) as mock_download,
        patch("pipeline.extract_downloaded_sources", return_value=[{"source": "001.pdf"}]) as mock_extract,
    ):
        downloaded, extracted = pipeline.run_pipeline(urls_file, force=True, workers=2)

    assert downloaded == [{"url": "https://example.gov/a.pdf"}]
    assert extracted == [{"source": "001.pdf"}]
    mock_download.assert_called_once_with(urls_file, force=True)
    mock_extract.assert_called_once_with(force=True, workers=2)


def test_main_dispatches_subcommands_and_parallel_defaults(tmp_path):
    urls_file = tmp_path / "urls.txt"

    with patch("pipeline.download_sources") as mock_download:
        pipeline.main(["download", str(urls_file)])
    mock_download.assert_called_once_with(urls_file, force=False)

    with patch("pipeline.extract_downloaded_sources") as mock_extract:
        pipeline.main(["extract"])
    mock_extract.assert_called_once_with(force=False, workers=None)

    with patch("pipeline.extract_downloaded_sources") as mock_extract:
        pipeline.main(["extract", "--parallel"])
    mock_extract.assert_called_once_with(force=False, workers=4)

    with patch("pipeline.run_pipeline") as mock_run:
        pipeline.main(["run", str(urls_file), "--force", "--parallel", "2"])
    mock_run.assert_called_once_with(urls_file, force=True, workers=2)
