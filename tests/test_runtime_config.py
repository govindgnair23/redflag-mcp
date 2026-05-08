from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_corpus import build_corpus_package, build_release_index, sha256_file  # noqa: E402

from redflag_mcp.server import (  # noqa: E402
    RuntimeMode,
    build_server_state,
    load_runtime_config,
)


class FailingModel:
    def encode(self, sentences: list[str], **kwargs: object) -> list[list[float]]:
        raise AssertionError("hosted corpus mode should not encode queries")


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
                    "key_terms": ["TBML"],
                }
            ]
        )
    )


def build_package(tmp_path: Path, version: str = "2026.04.29") -> Path:
    source = tmp_path / "source.yaml"
    write_source(source)
    return build_corpus_package(
        [source],
        output_dir=tmp_path / "dist",
        version=version,
        build_timestamp="2026-04-29T12:00:00Z",
    ).package_path


def test_load_runtime_config_defaults_to_local_vector_development() -> None:
    config = load_runtime_config({})

    assert config.mode == RuntimeMode.VECTOR_DEV
    assert config.corpus_package_path is None
    assert config.corpus_release_index_path is None


def test_load_runtime_config_selects_hosted_corpus_mode() -> None:
    config = load_runtime_config(
        {
            "REDFLAG_RUNTIME_MODE": "hosted-corpus",
            "REDFLAG_CORPUS_RELEASE_INDEX": "/tmp/releases.json",
            "REDFLAG_CORPUS_VERSION": "2026.04.29",
        }
    )

    assert config.mode == RuntimeMode.HOSTED_CORPUS
    assert config.corpus_release_index_path == Path("/tmp/releases.json")
    assert config.corpus_version == "2026.04.29"


def test_hosted_corpus_mode_activates_verified_package_without_embeddings(tmp_path):
    package = build_package(tmp_path)
    state = build_server_state(
        load_runtime_config(
            {
                "REDFLAG_RUNTIME_MODE": "hosted-corpus",
                "REDFLAG_CORPUS_PACKAGE": str(package),
                "REDFLAG_CORPUS_PACKAGE_SHA256": sha256_file(package),
                "REDFLAG_CORPUS_CACHE_DIR": str(tmp_path / "cache"),
            }
        ),
        embedding_model=FailingModel(),
    )

    assert state.readiness.ready is True
    assert state.service is not None
    response = state.service.search_red_flags(query="TBML invoices")
    assert response["results"][0]["id"] == "001-test-01"


def test_hosted_corpus_mode_requires_verified_corpus_configuration(tmp_path):
    state = build_server_state(
        load_runtime_config(
            {
                "REDFLAG_RUNTIME_MODE": "hosted-corpus",
                "REDFLAG_CORPUS_CACHE_DIR": str(tmp_path / "cache"),
            }
        ),
        embedding_model=FailingModel(),
    )

    assert state.service is None
    assert state.readiness.ready is False
    assert "requires" in state.readiness.message
    assert not (tmp_path / "cache/active.json").exists()


def test_hosted_corpus_mode_fails_closed_on_corrupt_package(tmp_path):
    package = build_package(tmp_path)
    package.write_bytes(b"not a zip")

    state = build_server_state(
        load_runtime_config(
            {
                "REDFLAG_RUNTIME_MODE": "hosted-corpus",
                "REDFLAG_CORPUS_PACKAGE": str(package),
                "REDFLAG_CORPUS_PACKAGE_SHA256": "0" * 64,
                "REDFLAG_CORPUS_CACHE_DIR": str(tmp_path / "cache"),
            }
        ),
        embedding_model=FailingModel(),
    )

    assert state.service is None
    assert state.readiness.ready is False
    assert "verification failed" in state.readiness.message


def test_hosted_corpus_mode_activates_pinned_release_index(tmp_path):
    package = build_package(tmp_path, "2026.04.29")
    index = build_release_index([package])
    index["releases"][0]["artifact"] = str(package)
    release_index = tmp_path / "release-index.json"
    release_index.write_text(json.dumps(index, sort_keys=True))

    state = build_server_state(
        load_runtime_config(
            {
                "REDFLAG_RUNTIME_MODE": "hosted-corpus",
                "REDFLAG_CORPUS_RELEASE_INDEX": str(release_index),
                "REDFLAG_CORPUS_VERSION": "2026.04.29",
                "REDFLAG_CORPUS_CACHE_DIR": str(tmp_path / "cache"),
            }
        ),
        embedding_model=FailingModel(),
    )

    assert state.readiness.ready is True
    assert state.readiness.corpus["version"] == "2026.04.29"
