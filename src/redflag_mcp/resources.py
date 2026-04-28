from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from redflag_mcp.config import VECTORS_DIR
from redflag_mcp.embeddings import EmbeddingModel
from redflag_mcp.tools import RedFlagService, _service_from_context


def register_resources(
    mcp: FastMCP,
    *,
    vector_dir: Path = VECTORS_DIR,
    embedding_model: EmbeddingModel | None = None,
) -> None:
    @mcp.resource(
        "redflag://sources",
        name="source_catalog",
        description="Ingested AML red flag source coverage and citation summaries.",
        mime_type="application/json",
    )
    def source_catalog() -> str:
        """Return source coverage summaries as JSON."""
        return _json(_service(None, vector_dir, embedding_model).list_sources())

    @mcp.resource(
        "redflag://sources/{source_id}",
        name="source_detail",
        description="Bounded AML red flag source detail by source identifier.",
        mime_type="application/json",
    )
    def source_detail(source_id: str, ctx: Context | None = None) -> str:
        """Return one source detail as JSON."""
        return _json(_service(ctx, vector_dir, embedding_model).get_source(source_id))


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _service(
    ctx: Context | None,
    vector_dir: Path,
    embedding_model: EmbeddingModel | None,
) -> RedFlagService:
    if ctx is None:
        return RedFlagService.from_vector_dir(
            vector_dir=vector_dir,
            embedding_model=embedding_model,
        )
    try:
        return _service_from_context(ctx)
    except ValueError:
        return RedFlagService.from_vector_dir(
            vector_dir=vector_dir,
            embedding_model=embedding_model,
        )
