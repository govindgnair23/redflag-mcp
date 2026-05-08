from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from redflag_mcp.config import VECTORS_DIR
from redflag_mcp.corpus import activate_corpus
from redflag_mcp.corpus_install import CorpusInstallError
from redflag_mcp.embeddings import EmbeddingModel
from redflag_mcp.prompts import register_prompts
from redflag_mcp.resources import register_resources
from redflag_mcp.tools import RedFlagService, register_tools

LOGGER = logging.getLogger(__name__)


class RuntimeMode(str, Enum):
    HOSTED_CORPUS = "hosted-corpus"
    LOCAL_CORPUS = "local-corpus"
    VECTOR_DEV = "vector-dev"


class RuntimeConfig:
    def __init__(
        self,
        *,
        mode: RuntimeMode = RuntimeMode.VECTOR_DEV,
        corpus_path: Path | None = None,
        corpus_cache_dir: Path | None = None,
        corpus_package_path: Path | None = None,
        corpus_package_sha256: str | None = None,
        corpus_release_index_path: Path | None = None,
        corpus_version: str | None = None,
        corpus_auto_update: bool = True,
    ) -> None:
        self.mode = mode
        self.corpus_path = corpus_path
        self.corpus_cache_dir = corpus_cache_dir
        self.corpus_package_path = corpus_package_path
        self.corpus_package_sha256 = corpus_package_sha256
        self.corpus_release_index_path = corpus_release_index_path
        self.corpus_version = corpus_version
        self.corpus_auto_update = corpus_auto_update


class ReadinessState:
    def __init__(
        self,
        *,
        ready: bool,
        message: str,
        corpus: dict[str, object] | None = None,
    ) -> None:
        self.ready = ready
        self.message = message
        self.corpus = corpus or {}

    @classmethod
    def ready_with_corpus(cls, corpus: dict[str, object]) -> ReadinessState:
        return cls(ready=True, message="ready", corpus=corpus)

    @classmethod
    def not_ready(cls, message: str) -> ReadinessState:
        return cls(ready=False, message=message)


class ServerState:
    def __init__(
        self,
        service: RedFlagService | None,
        readiness: ReadinessState | None = None,
    ) -> None:
        self.service = service
        self.readiness = readiness or ReadinessState.ready_with_corpus({})


def load_runtime_config(env: Mapping[str, str] | None = None) -> RuntimeConfig:
    env = env or os.environ
    mode_value = env.get("REDFLAG_RUNTIME_MODE")
    mode = RuntimeMode(mode_value) if mode_value else _infer_runtime_mode(env)
    return RuntimeConfig(
        mode=mode,
        corpus_path=_optional_path_from(env, "REDFLAG_CORPUS_PATH"),
        corpus_cache_dir=_optional_path_from(env, "REDFLAG_CORPUS_CACHE_DIR"),
        corpus_package_path=_optional_path_from(env, "REDFLAG_CORPUS_PACKAGE"),
        corpus_package_sha256=env.get("REDFLAG_CORPUS_PACKAGE_SHA256"),
        corpus_release_index_path=_optional_path_from(
            env,
            "REDFLAG_CORPUS_RELEASE_INDEX",
        ),
        corpus_version=env.get("REDFLAG_CORPUS_VERSION"),
        corpus_auto_update=env.get("REDFLAG_CORPUS_AUTO_UPDATE", "1").lower()
        not in {"0", "false", "no"},
    )


def build_server_state(
    config: RuntimeConfig,
    *,
    vector_dir: Path = VECTORS_DIR,
    embedding_model: EmbeddingModel | None = None,
) -> ServerState:
    if config.mode == RuntimeMode.VECTOR_DEV:
        return ServerState(
            service=RedFlagService.from_vector_dir(
                vector_dir=vector_dir,
                embedding_model=embedding_model,
            ),
            readiness=ReadinessState.ready_with_corpus({}),
        )

    if config.mode == RuntimeMode.LOCAL_CORPUS and config.corpus_path is not None:
        service = RedFlagService.from_corpus_path(
            config.corpus_path,
            embedding_model=embedding_model,
        )
        return ServerState(
            service=service,
            readiness=ReadinessState.ready_with_corpus(
                service.table.corpus.model_dump(exclude_none=True)
            ),
        )

    if config.mode == RuntimeMode.HOSTED_CORPUS:
        validation_error = _hosted_config_error(config)
        if validation_error is not None:
            return ServerState(
                service=None,
                readiness=ReadinessState.not_ready(validation_error),
            )

    try:
        activation = activate_corpus(
            cache_dir=config.corpus_cache_dir or Path.home() / ".redflag-mcp",
            corpus_package_path=config.corpus_package_path,
            expected_package_sha256=config.corpus_package_sha256,
            corpus_version=config.corpus_version,
            release_index_path=config.corpus_release_index_path,
            auto_update=config.corpus_auto_update,
        )
        service = RedFlagService.from_corpus_path(
            activation.sqlite_path,
            embedding_model=embedding_model,
        )
        return ServerState(
            service=service,
            readiness=ReadinessState.ready_with_corpus(
                _safe_manifest_metadata(activation.manifest_path)
            ),
        )
    except (CorpusInstallError, OSError, ValueError, json.JSONDecodeError) as exc:
        if config.mode == RuntimeMode.HOSTED_CORPUS:
            LOGGER.error("Hosted corpus activation failed: %s", exc)
            return ServerState(
                service=None,
                readiness=ReadinessState.not_ready(
                    f"Corpus verification failed: {exc}"
                ),
            )
        raise


def create_server(
    *,
    vector_dir: Path = VECTORS_DIR,
    corpus_path: Path | None = None,
    corpus_cache_dir: Path | None = None,
    corpus_package_path: Path | None = None,
    corpus_package_sha256: str | None = None,
    corpus_release_index_path: Path | None = None,
    corpus_version: str | None = None,
    corpus_auto_update: bool = True,
    runtime_config: RuntimeConfig | None = None,
    embedding_model: EmbeddingModel | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    json_response: bool = False,
    stateless_http: bool = False,
    state_factory: Callable[[], ServerState] | None = None,
) -> FastMCP[ServerState]:
    config = runtime_config or RuntimeConfig(
        mode=(
            RuntimeMode.LOCAL_CORPUS
            if corpus_path is not None
            or corpus_package_path is not None
            or corpus_release_index_path is not None
            else RuntimeMode.VECTOR_DEV
        ),
        corpus_path=corpus_path,
        corpus_cache_dir=corpus_cache_dir,
        corpus_package_path=corpus_package_path,
        corpus_package_sha256=corpus_package_sha256,
        corpus_release_index_path=corpus_release_index_path,
        corpus_version=corpus_version,
        corpus_auto_update=corpus_auto_update,
    )

    @asynccontextmanager
    async def lifespan(_app: FastMCP[ServerState]) -> AsyncIterator[ServerState]:
        if state_factory is not None:
            yield state_factory()
        else:
            yield build_server_state(
                config,
                vector_dir=vector_dir,
                embedding_model=embedding_model,
            )

    mcp = FastMCP(
        "redflag-mcp",
        instructions=(
            "Use the tools to search a local AML red flag corpus. Results are "
            "read-only and include citation metadata from the source documents."
        ),
        host=host,
        port=port,
        json_response=json_response,
        stateless_http=stateless_http,
        lifespan=lifespan,
    )
    register_tools(mcp)
    register_resources(
        mcp,
        vector_dir=vector_dir,
        corpus_path=config.corpus_path,
        embedding_model=embedding_model,
        disable_fallback=config.mode == RuntimeMode.HOSTED_CORPUS,
    )
    register_prompts(mcp)
    return mcp


mcp = create_server()


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    runtime_config = load_runtime_config()
    app = create_server(
        host=host,
        port=port,
        runtime_config=runtime_config,
    )

    if transport in {"http", "streamable-http"}:
        app.run(transport="streamable-http")
    elif transport == "sse":
        app.run(transport="sse")
    else:
        app.run(transport="stdio")


def _optional_path(env_name: str) -> Path | None:
    value = os.environ.get(env_name)
    return Path(value).expanduser() if value else None


def _optional_path_from(env: Mapping[str, str], env_name: str) -> Path | None:
    value = env.get(env_name)
    return Path(value).expanduser() if value else None


def _infer_runtime_mode(env: Mapping[str, str]) -> RuntimeMode:
    if env.get("REDFLAG_CORPUS_PATH"):
        return RuntimeMode.LOCAL_CORPUS
    if env.get("REDFLAG_CORPUS_PACKAGE") or env.get("REDFLAG_CORPUS_RELEASE_INDEX"):
        return RuntimeMode.LOCAL_CORPUS
    return RuntimeMode.VECTOR_DEV


def _hosted_config_error(config: RuntimeConfig) -> str | None:
    if config.corpus_path is not None:
        return "Hosted corpus mode requires a verified package or release index."
    if config.corpus_package_path is not None:
        if not config.corpus_package_sha256:
            return (
                "Hosted corpus mode requires REDFLAG_CORPUS_PACKAGE_SHA256 "
                "with REDFLAG_CORPUS_PACKAGE."
            )
        return None
    if config.corpus_release_index_path is not None:
        if not config.corpus_version:
            return (
                "Hosted corpus mode requires REDFLAG_CORPUS_VERSION with "
                "REDFLAG_CORPUS_RELEASE_INDEX."
            )
        return None
    return "Hosted corpus mode requires a verified corpus package or release index."


def _safe_manifest_metadata(manifest_path: Path) -> dict[str, object]:
    manifest = json.loads(manifest_path.read_text())
    keys = (
        "version",
        "schema_version",
        "package_id",
        "build_timestamp",
        "integrity_status",
        "record_count",
        "source_count",
        "file_hashes",
        "build_inputs",
        "enrichment_provenance",
    )
    return {key: manifest[key] for key in keys if key in manifest}


if __name__ == "__main__":
    main()
