from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from redflag_mcp.config import VECTORS_DIR
from redflag_mcp.embeddings import EmbeddingModel
from redflag_mcp.tools import RedFlagService, register_tools


class ServerState:
    def __init__(self, service: RedFlagService) -> None:
        self.service = service


def create_server(
    *,
    vector_dir: Path = VECTORS_DIR,
    embedding_model: EmbeddingModel | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP[ServerState]:
    @asynccontextmanager
    async def lifespan(_app: FastMCP[ServerState]) -> AsyncIterator[ServerState]:
        yield ServerState(
            service=RedFlagService.from_vector_dir(
                vector_dir=vector_dir,
                embedding_model=embedding_model,
            )
        )

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
    return mcp


mcp = create_server()


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8000"))
    app = create_server(host=host, port=port)

    if transport in {"http", "streamable-http"}:
        app.run(transport="streamable-http")
    elif transport == "sse":
        app.run(transport="sse")
    else:
        app.run(transport="stdio")


if __name__ == "__main__":
    main()
