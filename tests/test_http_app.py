from __future__ import annotations

import sys
from pathlib import Path

import yaml
from starlette.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_corpus import build_corpus_package, sha256_file  # noqa: E402

from redflag_mcp.http_app import create_http_app  # noqa: E402
from redflag_mcp.server import RuntimeMode, load_runtime_config  # noqa: E402


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


def build_package(tmp_path: Path) -> Path:
    source = tmp_path / "source.yaml"
    write_source(source)
    return build_corpus_package(
        [source],
        output_dir=tmp_path / "dist",
        version="2026.04.29",
        build_timestamp="2026-04-29T12:00:00Z",
    ).package_path


def hosted_config(tmp_path: Path, package: Path):
    return load_runtime_config(
        {
            "REDFLAG_RUNTIME_MODE": "hosted-corpus",
            "REDFLAG_CORPUS_PACKAGE": str(package),
            "REDFLAG_CORPUS_PACKAGE_SHA256": sha256_file(package),
            "REDFLAG_CORPUS_CACHE_DIR": str(tmp_path / "cache"),
        }
    )


def test_health_returns_process_liveness_without_tool_call(tmp_path):
    package = build_package(tmp_path)
    app = create_http_app(runtime_config=hosted_config(tmp_path, package))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_returns_safe_corpus_metadata_after_activation(tmp_path):
    package = build_package(tmp_path)
    app = create_http_app(runtime_config=hosted_config(tmp_path, package))

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["corpus"]["version"] == "2026.04.29"
    assert payload["corpus"]["package_id"] == "redflag-corpus-2026.04.29"
    assert "sources" not in payload["corpus"]


def test_ready_reports_not_ready_when_hosted_activation_fails(tmp_path):
    app = create_http_app(
        runtime_config=load_runtime_config(
            {
                "REDFLAG_RUNTIME_MODE": "hosted-corpus",
                "REDFLAG_CORPUS_CACHE_DIR": str(tmp_path / "cache"),
            }
        )
    )

    with TestClient(app) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_mcp_is_mounted_at_single_connector_path(tmp_path):
    package = build_package(tmp_path)
    app = create_http_app(runtime_config=hosted_config(tmp_path, package))

    with TestClient(app) as client:
        mcp_response = client.post(
            "/mcp",
            json={},
            headers={"accept": "application/json, text/event-stream"},
        )
        nested_response = client.post(
            "/mcp/mcp",
            json={},
            headers={"accept": "application/json, text/event-stream"},
        )

    assert mcp_response.status_code != 404
    assert nested_response.status_code == 404


def test_mcp_requests_are_rejected_when_hosted_runtime_not_ready(tmp_path):
    app = create_http_app(
        runtime_config=load_runtime_config(
            {
                "REDFLAG_RUNTIME_MODE": "hosted-corpus",
                "REDFLAG_CORPUS_CACHE_DIR": str(tmp_path / "cache"),
            }
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={},
            headers={"accept": "application/json, text/event-stream"},
        )

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_create_http_app_defaults_to_hosted_runtime_mode() -> None:
    app = create_http_app()

    assert app.state.runtime_config.mode == RuntimeMode.HOSTED_CORPUS
