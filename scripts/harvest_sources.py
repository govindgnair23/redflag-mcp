#!/usr/bin/env python3
"""Download PDFs and capture web pages from the Global AML/CFT/Sanctions Red Flag Catalog CSV.

Usage:
    uv run python scripts/harvest_sources.py <csv-path>

Reads the `Direct URL` column from each CSV row, classifies the URL as a PDF or web page,
downloads PDFs to red_flag_sources/pdf/, fetches web pages via Jina Reader API to
red_flag_sources/markdown/, and registers each new entry in sources.yaml.

Existing entries are skipped via URL-level deduplication. The script is idempotent:
re-running against the same CSV produces no new files or registry entries.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import urllib.parse
from pathlib import Path

import httpx
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SOURCES_YAML = PROJECT_ROOT / "red_flag_sources" / "sources.yaml"
PDFS_DIR = PROJECT_ROOT / "red_flag_sources" / "pdf"
MARKDOWN_DIR = PROJECT_ROOT / "red_flag_sources" / "markdown"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

LOGGER = logging.getLogger(__name__)


def load_registry(path: Path) -> tuple[dict[str, dict], set[str]]:
    """Load sources.yaml and return (registry_dict, existing_urls_set).

    Returns empty dict/set if the file is missing or empty.
    """
    if not path.exists():
        return {}, set()
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}, set()
    existing_urls = {
        entry["url"]
        for entry in data.values()
        if isinstance(entry, dict) and "url" in entry
    }
    return data, existing_urls


def write_registry(registry: dict[str, dict], path: Path) -> None:
    """Fully overwrite sources.yaml with the current registry."""
    with open(path, "w") as f:
        yaml.dump(registry, f, default_flow_style=False, sort_keys=True, allow_unicode=True)


def next_serial(registry: dict[str, dict]) -> int:
    """Return the next available serial number (1 if registry is empty)."""
    if not registry:
        return 1
    return max(int(k) for k in registry) + 1


def is_blank_or_invalid(url: str) -> bool:
    """Return True if the URL is blank or does not start with http:// or https://."""
    url = url.strip()
    return not url or not url.startswith(("http://", "https://"))


def heuristic_is_pdf(url: str) -> bool:
    """Return True if the URL is likely a PDF based on static heuristics.

    Checks in order:
    1. Path ends with .pdf (case-insensitive).
    2. Path contains /download (covers OFAC download variants).
    3. Path ends with /file (covers NCA direct downloads).
    """
    parsed_path = urllib.parse.urlparse(url).path.lower()
    if parsed_path.endswith(".pdf"):
        return True
    if "/download" in parsed_path:
        return True
    if parsed_path.endswith("/file"):
        return True
    return False


def head_is_pdf(url: str, client: httpx.Client) -> bool:
    """Return True if a HEAD request confirms Content-Type: application/pdf.

    Returns False on any HTTP or timeout error (classify as web instead of crashing).
    """
    try:
        response = client.head(url, follow_redirects=True, timeout=15.0)
        content_type = response.headers.get("content-type", "")
        return "application/pdf" in content_type
    except (httpx.HTTPError, httpx.TimeoutException):
        return False


def classify_url(url: str, client: httpx.Client) -> str:
    """Return 'pdf' or 'web'. Tries heuristics first, then HEAD fallback."""
    if heuristic_is_pdf(url):
        return "pdf"
    if head_is_pdf(url, client):
        return "pdf"
    return "web"


def fetch_pdf(url: str, dest_path: Path, client: httpx.Client) -> int:
    """Download a PDF to dest_path. Returns bytes written.

    Raises httpx.HTTPError, httpx.TimeoutException, or OSError on failure.
    """
    response = client.get(url, follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    dest_path.write_bytes(response.content)
    return len(response.content)


def fetch_web(url: str, dest_path: Path, client: httpx.Client) -> int:
    """Fetch a web page via Jina Reader and write markdown to dest_path.

    Returns character count written.
    Raises on HTTP error, timeout, or empty response body.
    """
    jina_url = f"https://r.jina.ai/{url}"
    response = client.get(jina_url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    text = response.text
    if not text.strip():
        raise ValueError(f"Jina Reader returned empty content for {url}")
    dest_path.write_text(text, encoding="utf-8")
    return len(text)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Download PDFs and web pages from an AML catalog CSV into the sources registry."
    )
    parser.add_argument(
        "csv_path",
        type=Path,
        help="Path to the CSV file containing a 'Direct URL' column.",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Re-download already-registered URLs, overwriting existing local files.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    csv_path: Path = args.csv_path
    if not csv_path.exists():
        parser.error(f"CSV file not found: {csv_path}")

    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)

    registry, existing_urls = load_registry(SOURCES_YAML)
    url_to_key: dict[str, str] = {v["url"]: k for k, v in registry.items() if "url" in v}
    serial = next_serial(registry)

    pdf_count = 0
    web_count = 0
    skipped_count = 0
    failed_count = 0

    try:
        with open(csv_path, newline="", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            if "Direct URL" not in (reader.fieldnames or []):
                LOGGER.error("CSV file is missing the 'Direct URL' column.")
                sys.exit(1)

            with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
                for row in reader:
                    url = row["Direct URL"].strip()

                    if is_blank_or_invalid(url):
                        LOGGER.warning("Skipping invalid URL: %r", url)
                        skipped_count += 1
                        continue

                    if url in existing_urls:
                        if not args.force:
                            LOGGER.info("Already registered, skipping: %s", url)
                            skipped_count += 1
                            continue
                        # Force mode: re-download using the existing key
                        key = url_to_key[url]
                        LOGGER.info("Force re-downloading %s (key %s)", url, key)
                    else:
                        key = f"{serial:03d}"

                    kind = classify_url(url, client)
                    dest_path = (
                        PDFS_DIR / f"{key}.pdf"
                        if kind == "pdf"
                        else MARKDOWN_DIR / f"{key}.md"
                    )

                    try:
                        if kind == "pdf":
                            size = fetch_pdf(url, dest_path, client)
                            LOGGER.info("PDF %s: %d bytes -> %s", key, size, dest_path.name)
                            pdf_count += 1
                        else:
                            size = fetch_web(url, dest_path, client)
                            LOGGER.info("Web %s: %d chars -> %s", key, size, dest_path.name)
                            web_count += 1

                        registry[key] = {"url": url}
                        existing_urls.add(url)
                        if url not in url_to_key:
                            serial += 1
                    except Exception as exc:
                        LOGGER.error("Failed %s: %s", url, exc)
                        failed_count += 1
    finally:
        write_registry(registry, SOURCES_YAML)

    LOGGER.info(
        "Harvest complete: %d PDFs, %d web pages, %d skipped, %d failed",
        pdf_count,
        web_count,
        skipped_count,
        failed_count,
    )


if __name__ == "__main__":
    main()
