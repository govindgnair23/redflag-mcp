#!/usr/bin/env python3
"""Build a versioned local red flag corpus package."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redflag_mcp.config import PROJECT_ROOT, SOURCE_DIR  # noqa: E402
from redflag_mcp.lexicalstore import LEXICAL_SCHEMA_VERSION, create_lexical_store  # noqa: E402
from redflag_mcp.models import (  # noqa: E402
    CorpusMetadata,
    RedFlagRecord,
    RedFlagSource,
    SourceReleaseMetadata,
    build_source_manifest,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_ALIASES_PATH = PROJECT_ROOT / "data/lexicon/aliases.yaml"
DEFAULT_SOURCE_METADATA_PATH = PROJECT_ROOT / "data/lexicon/source_metadata.yaml"
DEFAULT_SOURCE_REGISTRY_PATH = PROJECT_ROOT / "red_flag_sources/sources.yaml"
DEFAULT_DEPENDENCY_LOCK_PATH = PROJECT_ROOT / "uv.lock"
FIXED_ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class CorpusBuildResult:
    package_path: Path
    manifest: dict[str, Any]


def discover_source_files(source_dir: Path = SOURCE_DIR) -> list[Path]:
    return sorted(
        path for path in source_dir.glob("*.yaml") if not path.name.startswith(".")
    )


def select_corpus_source_paths(
    source_paths: Sequence[Path],
    *,
    all_sources: bool,
    source_dir: Path = SOURCE_DIR,
) -> list[Path]:
    if all_sources and source_paths:
        raise ValueError("--all-sources cannot be used with explicit source paths")
    if all_sources:
        return discover_source_files(source_dir)
    if not source_paths:
        raise ValueError("Provide source paths or pass --all-sources")
    return list(source_paths)


def build_corpus_package(
    source_paths: Sequence[Path],
    *,
    output_dir: Path,
    version: str,
    build_timestamp: str | None = None,
    aliases_path: Path = DEFAULT_ALIASES_PATH,
    source_metadata_path: Path = DEFAULT_SOURCE_METADATA_PATH,
    source_registry_path: Path = DEFAULT_SOURCE_REGISTRY_PATH,
    dependency_lock_path: Path = DEFAULT_DEPENDENCY_LOCK_PATH,
) -> CorpusBuildResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    build_timestamp = build_timestamp or datetime.now(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    sources = load_source_records(source_paths)
    if not sources:
        raise ValueError("No valid source records found; refusing to build empty corpus")

    records = [RedFlagRecord.from_source(source, []) for source in sources]
    aliases = load_aliases(aliases_path)
    source_registry = load_source_registry(source_registry_path)
    source_metadata = load_source_metadata(source_metadata_path)
    source_manifest = build_source_manifest(source_metadata, source_registry)
    source_record_hashes = {
        source.id: sha256_json(source.model_dump(mode="json", exclude_none=True))
        for source in sorted(sources, key=lambda item: item.id)
    }
    build_inputs = {
        "aliases_sha256": sha256_file(aliases_path) if aliases_path.exists() else None,
        "source_metadata_sha256": (
            sha256_file(source_metadata_path)
            if source_metadata_path.exists()
            else None
        ),
        "source_registry_sha256": (
            sha256_file(source_registry_path)
            if source_registry_path.exists()
            else None
        ),
        "dependency_lock_sha256": (
            sha256_file(dependency_lock_path)
            if dependency_lock_path.exists()
            else None
        ),
    }
    enrichment_provenance = _build_enrichment_provenance(source_manifest)
    package_id = f"redflag-corpus-{version}"
    sqlite_path = output_dir / "redflags.sqlite"
    corpus = CorpusMetadata(
        version=version,
        schema_version=LEXICAL_SCHEMA_VERSION,
        build_timestamp=build_timestamp,
        package_id=package_id,
        file_hashes={"redflags.sqlite": "0" * 64},
        integrity_status="verified",
        record_count=len(records),
        source_count=len(source_manifest),
        source_record_hashes=source_record_hashes,
        build_inputs=build_inputs,
        enrichment_provenance=enrichment_provenance,
    )
    extra_search_text = {
        source.id: _enriched_search_terms(source)
        for source in sources
        if _enriched_search_terms(source)
    }
    create_lexical_store(
        sqlite_path,
        records,
        corpus=corpus,
        aliases=aliases,
        extra_search_text=extra_search_text,
    )
    sqlite_hash = sha256_file(sqlite_path)
    manifest = {
        "version": version,
        "schema_version": LEXICAL_SCHEMA_VERSION,
        "build_timestamp": build_timestamp,
        "package_id": package_id,
        "integrity_status": "verified",
        "record_count": len(records),
        "source_count": len(source_manifest),
        "file_hashes": {"redflags.sqlite": sqlite_hash},
        "source_record_hashes": source_record_hashes,
        "build_inputs": build_inputs,
        "enrichment_provenance": enrichment_provenance,
        "sources": {
            key: entry.model_dump(exclude_none=True)
            for key, entry in source_manifest.items()
        },
    }
    package_path = output_dir / f"{package_id}.zip"
    write_package(package_path, {"manifest.json": manifest, "redflags.sqlite": sqlite_path})
    return CorpusBuildResult(package_path=package_path, manifest=manifest)


def build_release_index(package_paths: Sequence[Path]) -> dict[str, Any]:
    releases: list[dict[str, Any]] = []
    for package_path in package_paths:
        with zipfile.ZipFile(package_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        releases.append(
            {
                "version": manifest["version"],
                "schema_version": manifest["schema_version"],
                "package_id": manifest["package_id"],
                "artifact": package_path.name,
                "sha256": sha256_file(package_path),
                "record_count": manifest["record_count"],
                "source_count": manifest["source_count"],
            }
        )
    releases.sort(key=lambda release: release["version"], reverse=True)
    return {
        "schema_version": 1,
        "latest_compatible_version": releases[0]["version"] if releases else None,
        "releases": releases,
    }


def load_source_records(source_paths: Sequence[Path]) -> list[RedFlagSource]:
    sources: list[RedFlagSource] = []
    for source_path in source_paths:
        data = yaml.safe_load(source_path.read_text()) or []
        if not isinstance(data, list):
            raise ValueError(f"{source_path} must contain a top-level YAML list")
        for index, raw_entry in enumerate(data, start=1):
            if not isinstance(raw_entry, dict):
                raise ValueError(f"{source_path} entry {index} must be a mapping")
            try:
                sources.append(RedFlagSource(**raw_entry))
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid source record in {source_path} entry {index}: {exc}"
                ) from exc
    return sorted(sources, key=lambda source: source.id)


def load_aliases(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    aliases: dict[str, list[str]] = {}
    for alias, expansions in data.items():
        if isinstance(expansions, str):
            aliases[str(alias)] = [expansions]
        elif isinstance(expansions, list):
            aliases[str(alias)] = [str(expansion) for expansion in expansions]
        else:
            raise ValueError(f"Alias {alias} must map to a string or list")
    return aliases


def load_source_metadata(path: Path) -> dict[str, SourceReleaseMetadata]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return {
        _source_key(key): SourceReleaseMetadata(**(value or {}))
        for key, value in data.items()
    }


def load_source_registry(path: Path) -> dict[str, dict[str, str | None]]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return {
        _source_key(key): {"url": (value or {}).get("url")}
        for key, value in data.items()
    }


def write_package(package_path: Path, files: dict[str, Any]) -> None:
    with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for archive_name in sorted(files):
            value = files[archive_name]
            if isinstance(value, Path):
                data = value.read_bytes()
            else:
                data = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
            info = zipfile.ZipInfo(archive_name, date_time=FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _enriched_search_terms(source: RedFlagSource) -> list[str]:
    terms: list[str] = []
    for field in ("typology_family", "transaction_patterns", "key_terms"):
        value = getattr(source, field)
        if isinstance(value, list):
            terms.extend(str(item) for item in value)
        elif value:
            terms.append(str(value))
    return terms


def _source_key(value: object) -> str:
    return str(value).zfill(3)


def _build_enrichment_provenance(
    source_manifest: dict[str, SourceReleaseMetadata],
) -> dict[str, str]:
    statuses = {entry.enrichment_status for entry in source_manifest.values()}
    if "manual_review" in statuses:
        status = "manual_review"
    elif statuses == {"approved"}:
        status = "approved"
    elif "generated" in statuses:
        status = "generated"
    else:
        status = "unknown"
    return {"status": status}


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build a local red flag corpus ZIP.")
    parser.add_argument("sources", nargs="*", type=Path)
    parser.add_argument(
        "--all-sources",
        action="store_true",
        help="Build from all visible YAML files in data/source/.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--build-timestamp",
        help="Deterministic UTC build timestamp to store in manifest metadata.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        source_paths = select_corpus_source_paths(
            args.sources,
            all_sources=args.all_sources,
        )
    except ValueError as exc:
        parser.error(str(exc))
    result = build_corpus_package(
        source_paths,
        output_dir=args.output_dir,
        version=args.version,
        build_timestamp=args.build_timestamp,
    )
    LOGGER.info("Built corpus package %s", result.package_path)


if __name__ == "__main__":
    main()
