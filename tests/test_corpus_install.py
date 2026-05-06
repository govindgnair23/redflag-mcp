from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from redflag_mcp.corpus_install import (
    CorpusInstallConfig,
    CorpusInstallError,
    CorpusInstaller,
)

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_corpus import build_corpus_package, build_release_index  # noqa: E402


def write_source(path: Path, record_id: str = "001-test-01") -> None:
    path.write_text(
        yaml.safe_dump(
            [
                {
                    "id": record_id,
                    "description": "Trade-based money laundering through invoices.",
                    "product_types": ["trade_finance"],
                    "regulatory_source": "FinCEN Alert",
                    "risk_level": "high",
                    "category": "trade_based_money_laundering",
                    "source_url": "https://example.com/source.pdf",
                }
            ]
        )
    )


def build_package(tmp_path: Path, version: str) -> Path:
    source = tmp_path / f"source-{version}.yaml"
    write_source(source)
    return build_corpus_package(
        [source],
        output_dir=tmp_path / f"dist-{version}",
        version=version,
        build_timestamp=f"{version}T00:00:00Z",
    ).package_path


def write_index(path: Path, packages: list[Path]) -> None:
    index = build_release_index(packages)
    for release in index["releases"]:
        release["artifact"] = str(packages_by_name(packages)[release["artifact"]])
    path.write_text(json.dumps(index, sort_keys=True))


def packages_by_name(packages: list[Path]) -> dict[str, Path]:
    return {package.name: package for package in packages}


def test_no_installed_corpus_installs_latest_from_release_index(tmp_path):
    old_package = build_package(tmp_path, "2026.04.28")
    new_package = build_package(tmp_path, "2026.04.29")
    release_index = tmp_path / "release-index.json"
    write_index(release_index, [old_package, new_package])

    activation = CorpusInstaller(
        CorpusInstallConfig(cache_dir=tmp_path / "cache", release_index_path=release_index)
    ).activate()

    assert activation.version == "2026.04.29"
    assert activation.sqlite_path.exists()
    assert (tmp_path / "cache/active.json").exists()


def test_corrupt_package_fails_closed_without_activation(tmp_path):
    package = build_package(tmp_path, "2026.04.29")
    package.write_bytes(b"not a zip")

    with pytest.raises(CorpusInstallError, match="verification failed"):
        CorpusInstaller(
            CorpusInstallConfig(cache_dir=tmp_path / "cache", corpus_package_path=package)
        ).activate()

    assert not (tmp_path / "cache/active.json").exists()


def test_pinned_version_selects_requested_release(tmp_path):
    old_package = build_package(tmp_path, "2026.04.28")
    new_package = build_package(tmp_path, "2026.04.29")
    release_index = tmp_path / "release-index.json"
    write_index(release_index, [old_package, new_package])

    activation = CorpusInstaller(
        CorpusInstallConfig(
            cache_dir=tmp_path / "cache",
            release_index_path=release_index,
            corpus_version="2026.04.28",
        )
    ).activate()

    assert activation.version == "2026.04.28"


def test_auto_update_disabled_uses_active_corpus(tmp_path):
    old_package = build_package(tmp_path, "2026.04.28")
    new_package = build_package(tmp_path, "2026.04.29")
    release_index = tmp_path / "release-index.json"
    write_index(release_index, [old_package, new_package])
    installer = CorpusInstaller(
        CorpusInstallConfig(
            cache_dir=tmp_path / "cache",
            release_index_path=release_index,
            corpus_version="2026.04.28",
        )
    )
    installer.activate()

    activation = CorpusInstaller(
        CorpusInstallConfig(
            cache_dir=tmp_path / "cache",
            release_index_path=release_index,
            auto_update=False,
        )
    ).activate()

    assert activation.version == "2026.04.28"
