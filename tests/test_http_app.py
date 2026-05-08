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


def hosted_app(tmp_path: Path, env: dict[str, str] | None = None):
    package = build_package(tmp_path)
    values = {
        "REDFLAG_RUNTIME_MODE": "hosted-corpus",
        "REDFLAG_CORPUS_PACKAGE": str(package),
        "REDFLAG_CORPUS_PACKAGE_SHA256": sha256_file(package),
        "REDFLAG_CORPUS_CACHE_DIR": str(tmp_path / "cache"),
    }
    values.update(env or {})
    return create_http_app(env=values)


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


def test_mcp_accepts_public_host_when_allowed_hosts_are_not_configured(tmp_path):
    app = hosted_app(tmp_path)

    with TestClient(app, base_url="https://redflag-mcp.up.railway.app") as client:
        response = client.post(
            "/mcp",
            json={},
            headers={"accept": "application/json, text/event-stream"},
        )

    assert response.status_code != 421


def test_mcp_uses_configured_allowed_host_for_transport_security(tmp_path):
    app = hosted_app(
        tmp_path,
        {"REDFLAG_ALLOWED_HOSTS": "redflag-mcp.up.railway.app"},
    )

    with TestClient(app, base_url="https://redflag-mcp.up.railway.app") as client:
        response = client.post(
            "/mcp",
            json={},
            headers={"accept": "application/json, text/event-stream"},
        )

    assert response.status_code != 421


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


def test_oversized_mcp_request_is_rejected_before_mcp_handling(tmp_path):
    app = hosted_app(tmp_path, {"REDFLAG_MAX_REQUEST_BYTES": "8"})

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            content=b"x" * 9,
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
            },
        )

    assert response.status_code == 413
    assert response.json()["error"] == "request_too_large"


def test_invalid_origin_is_rejected(tmp_path):
    app = hosted_app(
        tmp_path,
        {
            "REDFLAG_ALLOWED_ORIGINS": "https://allowed.example",
            "REDFLAG_ALLOWED_HOSTS": "testserver",
        },
    )

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            json={},
            headers={
                "origin": "https://evil.example",
                "accept": "application/json, text/event-stream",
            },
        )

    assert response.status_code == 403
    assert response.json()["error"] == "origin_not_allowed"


def test_invalid_host_is_rejected(tmp_path):
    app = hosted_app(tmp_path, {"REDFLAG_ALLOWED_HOSTS": "allowed.example"})

    with TestClient(app) as client:
        response = client.get("/ready", headers={"host": "evil.example"})

    assert response.status_code == 403
    assert response.json()["error"] == "host_not_allowed"


def test_rate_limit_exceeded_returns_bounded_failure(tmp_path):
    app = hosted_app(tmp_path, {"REDFLAG_RATE_LIMIT_PER_MINUTE": "1"})

    with TestClient(app) as client:
        first = client.get("/health")
        second = client.get("/health")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"] == "rate_limit_exceeded"


def test_concurrency_limit_exceeded_returns_bounded_failure(tmp_path):
    app = hosted_app(tmp_path, {"REDFLAG_MAX_CONCURRENT_REQUESTS": "1"})
    app.state.guardrails.active_requests = 1

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["error"] == "too_many_concurrent_requests"


def test_create_http_app_defaults_to_hosted_runtime_mode() -> None:
    app = create_http_app()

    assert app.state.runtime_config.mode == RuntimeMode.HOSTED_CORPUS
    assert app.state.runtime_config.corpus_release_index_path == Path(
        "dist/corpus/releases.json"
    )
