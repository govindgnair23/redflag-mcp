from __future__ import annotations

import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_railway_config_launches_hosted_asgi_app() -> None:
    config = tomllib.loads((PROJECT_ROOT / "railway.toml").read_text())

    build = config["build"]
    deploy = config["deploy"]
    variables = config["variables"]
    start_command = deploy["startCommand"]

    assert build["builder"] == "DOCKERFILE"
    assert build["dockerfilePath"] == "Dockerfile"
    assert "buildCommand" not in build
    assert deploy["healthcheckPath"] == "/ready"
    assert "uvicorn" in start_command
    assert "redflag_mcp.http_app:app" in start_command
    assert "--host 0.0.0.0" in start_command
    assert "--port $PORT" in start_command
    assert variables["REDFLAG_RUNTIME_MODE"] == "hosted-corpus"
    assert variables["REDFLAG_ALLOWED_HOSTS"]
    assert "healthcheck.railway.app" in variables["REDFLAG_ALLOWED_HOSTS"]
    assert "REDFLAG_CORPUS_RELEASE_INDEX" in variables
    assert "REDFLAG_CORPUS_VERSION" in variables


def test_hosted_docs_capture_public_privacy_and_rollback() -> None:
    docs = (PROJECT_ROOT / "docs/hosted-deployment.md").read_text()

    assert "public hosted mode is not for confidential" in docs.lower()
    assert "rollback" in docs.lower()
    assert "REDFLAG_CORPUS_RELEASE_INDEX" in docs
    assert "/ready" in docs
    assert "/mcp" in docs
    assert "healthcheck.railway.app" in docs
    assert "single instance" in docs.lower()


def test_readme_leads_with_hosted_connector_setup() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()

    hosted_index = readme.index("## Hosted Connector")
    extraction_index = readme.index("## Extraction Pipeline")

    assert hosted_index < extraction_index
    hosted_section = readme[hosted_index:extraction_index]
    assert "/mcp" in hosted_section
    assert "public hosted mode is not for confidential" in hosted_section.lower()
    assert "scripts/ingest.py" not in hosted_section
    assert "scripts/build_corpus.py" not in hosted_section
