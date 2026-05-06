#!/usr/bin/env python3
"""Verify a versioned local red flag corpus package."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redflag_mcp.lexicalstore import LEXICAL_SCHEMA_VERSION  # noqa: E402

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CorpusVerificationResult:
    status: str
    message: str
    version: str | None = None
    schema_version: int | None = None
    record_count: int = 0
    source_count: int = 0
    file_hashes: dict[str, str] | None = None


def verify_corpus_package(package_path: Path) -> CorpusVerificationResult:
    try:
        with zipfile.ZipFile(package_path) as archive:
            names = set(archive.namelist())
            if "manifest.json" not in names:
                return _failed("Package is missing manifest.json")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("schema_version") != LEXICAL_SCHEMA_VERSION:
                return _failed(
                    "Unsupported corpus schema version: "
                    f"{manifest.get('schema_version')}"
                )
            expected_hashes = manifest.get("file_hashes") or {}
            for file_name, expected_hash in expected_hashes.items():
                if file_name not in names:
                    return _failed(f"Package is missing {file_name}")
                actual_hash = hashlib.sha256(archive.read(file_name)).hexdigest()
                if actual_hash != expected_hash:
                    return _failed(f"{file_name} hash mismatch")
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError) as exc:
        return _failed(f"Package verification failed: {exc}")

    return CorpusVerificationResult(
        status="verified",
        message="Package verified",
        version=manifest["version"],
        schema_version=manifest["schema_version"],
        record_count=int(manifest["record_count"]),
        source_count=int(manifest["source_count"]),
        file_hashes=dict(expected_hashes),
    )


def _failed(message: str) -> CorpusVerificationResult:
    return CorpusVerificationResult(status="failed", message=message, file_hashes={})


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Verify a local red flag corpus ZIP.")
    parser.add_argument("package", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    result = verify_corpus_package(args.package)
    if result.status == "verified":
        LOGGER.info("Verified %s", args.package)
        return
    LOGGER.error("%s", result.message)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
