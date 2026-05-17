#!/usr/bin/env python3
"""Run a URL-to-red-flag source workflow."""

from __future__ import annotations

import argparse
import csv
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from build_registry import DEFAULT_REGISTRY_PATH, build_registry, normalize_url
from extract import load_manifest, process_one, save_manifest
from harvest_sources import (
    MARKDOWN_DIR,
    PDFS_DIR,
    SOURCES_YAML,
    USER_AGENT,
    classify_url,
    fetch_pdf,
    fetch_web,
    is_blank_or_invalid,
    load_registry,
    next_serial,
    write_registry,
)

REGISTRY_CSV = DEFAULT_REGISTRY_PATH
LOGGER = logging.getLogger(__name__)


def read_urls_file(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        url = line.strip()
        if is_blank_or_invalid(url):
            if url:
                LOGGER.warning("Skipping invalid URL: %r", url)
            continue
        urls.append(url)
    return urls


def load_registry_source_urls(path: Path = REGISTRY_CSV) -> set[str]:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {
            normalize_url(row.get("source_url", ""))
            for row in csv.DictReader(f)
            if row.get("source_url")
        }


def update_status_registry() -> None:
    try:
        build_registry()
    except Exception as exc:
        LOGGER.warning("Failed to update registry.csv: %s", exc)


def download_sources(
    urls_file: Path,
    force: bool = False,
    client: httpx.Client | None = None,
) -> list[dict[str, object]]:
    urls = read_urls_file(urls_file)
    registry_urls = load_registry_source_urls(REGISTRY_CSV)
    sources_registry, _existing_urls = load_registry(SOURCES_YAML)
    url_to_key = {
        normalize_url(entry["url"]): key
        for key, entry in sources_registry.items()
        if isinstance(entry, dict) and entry.get("url")
    }
    serial = next_serial(sources_registry)
    downloaded: list[dict[str, object]] = []

    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)

    owns_client = client is None
    active_client = client or httpx.Client(headers={"User-Agent": USER_AGENT})
    try:
        for url in urls:
            normalized_url = normalize_url(url)
            if normalized_url in registry_urls and not force:
                LOGGER.info("Already in registry, skipping: %s", url)
                continue

            if normalized_url in url_to_key:
                key = url_to_key[normalized_url]
                is_new_key = False
            else:
                key = f"{serial:03d}"
                is_new_key = True

            try:
                kind = classify_url(url, active_client)
                dest_path = PDFS_DIR / f"{key}.pdf" if kind == "pdf" else MARKDOWN_DIR / f"{key}.md"
                if kind == "pdf":
                    fetch_pdf(url, dest_path, active_client)
                else:
                    fetch_web(url, dest_path, active_client)
            except Exception as exc:
                LOGGER.error("Failed to download %s: %s", url, exc)
                continue

            sources_registry[key] = {"url": url}
            write_registry(sources_registry, SOURCES_YAML)
            registry_urls.add(normalized_url)
            url_to_key[normalized_url] = key
            if is_new_key:
                serial += 1
            downloaded.append({"key": key, "url": url, "kind": kind, "path": dest_path})
            update_status_registry()
    finally:
        if owns_client:
            active_client.close()

    return downloaded


def load_downloaded_registry_rows(path: Path = REGISTRY_CSV) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f) if row.get("status") == "downloaded"]


def resolve_downloaded_source(row: dict[str, str], sources_registry: dict[str, dict]) -> str | None:
    source_url = normalize_url(row.get("source_url", ""))
    for key, entry in sources_registry.items():
        if not isinstance(entry, dict) or normalize_url(entry.get("url", "")) != source_url:
            continue
        pdf_path = PDFS_DIR / f"{key}.pdf"
        if pdf_path.exists():
            return str(pdf_path)
        markdown_path = MARKDOWN_DIR / f"{key}.md"
        if markdown_path.exists():
            return str(markdown_path)
    return None


def extract_downloaded_sources(force: bool = False, workers: int | None = None) -> list[dict]:
    rows = load_downloaded_registry_rows(REGISTRY_CSV)
    if not rows:
        LOGGER.info("No downloaded sources to extract.")
        return []

    sources_registry, _existing_urls = load_registry(SOURCES_YAML)
    manifest = load_manifest()
    work_items: list[tuple[str, str]] = []
    for row in rows:
        source = resolve_downloaded_source(row, sources_registry)
        if source is None:
            LOGGER.warning("No local file found for downloaded URL: %s", row.get("source_url", ""))
            continue
        work_items.append((source, row.get("source_url", "")))

    if not work_items:
        return []

    entries: list[dict] = []
    if workers is None:
        for source, source_url in work_items:
            entry = process_one(source, force=force, manifest=manifest, source_url=source_url)
            if entry:
                entries.append(entry)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(process_one, source, force, manifest, source_url): source
                for source, source_url in work_items
            }
            for future in as_completed(futures):
                source = futures[future]
                try:
                    entry = future.result()
                except Exception as exc:
                    LOGGER.error("Failed to extract %s: %s", source, exc)
                    continue
                if entry:
                    entries.append(entry)

    if entries:
        new_sources = {entry["source"] for entry in entries}
        updated = [entry for entry in load_manifest() if entry.get("source") not in new_sources]
        updated.extend(entries)
        save_manifest(updated)
        update_status_registry()

    return entries


def run_pipeline(
    urls_file: Path,
    force: bool = False,
    workers: int | None = None,
) -> tuple[list[dict[str, object]], list[dict]]:
    downloaded = download_sources(urls_file, force=force)
    extracted = extract_downloaded_sources(force=force, workers=workers)
    return downloaded, extracted


def parse_parallel(value: str | None) -> int | None:
    return int(value) if value is not None else None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Download and extract AML red-flag sources from URLs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="Download URLs into local sources.")
    download_parser.add_argument("urls_file", type=Path)
    download_parser.add_argument("--force", action="store_true")

    extract_parser = subparsers.add_parser("extract", help="Extract all downloaded registry sources.")
    extract_parser.add_argument("--force", action="store_true")
    extract_parser.add_argument("--parallel", nargs="?", const="4")

    run_parser = subparsers.add_parser("run", help="Download URLs, then extract downloaded sources.")
    run_parser.add_argument("urls_file", type=Path)
    run_parser.add_argument("--force", action="store_true")
    run_parser.add_argument("--parallel", nargs="?", const="4")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.command == "download":
        download_sources(args.urls_file, force=args.force)
    elif args.command == "extract":
        extract_downloaded_sources(force=args.force, workers=parse_parallel(args.parallel))
    elif args.command == "run":
        run_pipeline(args.urls_file, force=args.force, workers=parse_parallel(args.parallel))


if __name__ == "__main__":
    main()
