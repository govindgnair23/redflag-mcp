from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from redflag_mcp.config import VECTORS_DIR
from redflag_mcp.corpus import activate_corpus
from redflag_mcp.embeddings import EmbeddingModel
from redflag_mcp.prompts import register_prompts
from redflag_mcp.resources import register_resources
from redflag_mcp.tools import RedFlagService, register_tools


class ServerState:
    def __init__(self, service: RedFlagService) -> None:
        self.service = service


def create_server(
    *,
    vector_dir: Path = VECTORS_DIR,
    corpus_path: Path | None = None,
    corpus_cache_dir: Path | None = None,
    corpus_package_path: Path | None = None,
    corpus_release_index_path: Path | None = None,
    corpus_version: str | None = None,
    corpus_auto_update: bool = True,
    embedding_model: EmbeddingModel | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP[ServerState]:
    @asynccontextmanager
    async def lifespan(_app: FastMCP[ServerState]) -> AsyncIterator[ServerState]:
        if corpus_path is not None:
            service = RedFlagService.from_corpus_path(
                corpus_path,
                embedding_model=embedding_model,
            )
        elif corpus_package_path is not None or corpus_release_index_path is not None:
            activation = activate_corpus(
                cache_dir=corpus_cache_dir or Path.home() / ".redflag-mcp",
                corpus_package_path=corpus_package_path,
                corpus_version=corpus_version,
                release_index_path=corpus_release_index_path,
                auto_update=corpus_auto_update,
            )
            service = RedFlagService.from_corpus_path(
                activation.sqlite_path,
                embedding_model=embedding_model,
            )
        else:
            service = RedFlagService.from_vector_dir(
                vector_dir=vector_dir,
                embedding_model=embedding_model,
            )
        yield ServerState(service=service)

    mcp = FastMCP(
        "redflag-mcp",
        instructions=(
            "Use the tools to search a local AML red flag corpus. Results are "
            "read-only and include citation metadata from the source documents."
        ),
        host=host,
        port=port,
        lifespan=lifespan,
    )
    register_tools(mcp)
    register_resources(
        mcp,
        vector_dir=vector_dir,
        corpus_path=corpus_path,
        embedding_model=embedding_model,
    )
    register_prompts(mcp)
    return mcp


mcp = create_server()


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    corpus_path = _optional_path("REDFLAG_CORPUS_PATH")
    corpus_package_path = _optional_path("REDFLAG_CORPUS_PACKAGE")
    corpus_release_index_path = _optional_path("REDFLAG_CORPUS_RELEASE_INDEX")
    corpus_cache_dir = _optional_path("REDFLAG_CORPUS_CACHE_DIR")
    corpus_auto_update = os.environ.get("REDFLAG_CORPUS_AUTO_UPDATE", "1").lower() not in {
        "0",
        "false",
        "no",
    }
    app = create_server(
        host=host,
        port=port,
        corpus_path=corpus_path,
        corpus_cache_dir=corpus_cache_dir,
        corpus_package_path=corpus_package_path,
        corpus_release_index_path=corpus_release_index_path,
        corpus_version=os.environ.get("REDFLAG_CORPUS_VERSION"),
        corpus_auto_update=corpus_auto_update,
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


if __name__ == "__main__":
    main()
