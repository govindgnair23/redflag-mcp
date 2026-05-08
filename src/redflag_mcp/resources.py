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
    corpus_path: Path | None = None,
    embedding_model: EmbeddingModel | None = None,
    disable_fallback: bool = False,
) -> None:
    @mcp.resource(
        "redflag://sources",
        name="source_catalog",
        description="Ingested AML red flag source coverage and citation summaries.",
        mime_type="application/json",
    )
    def source_catalog() -> str:
        """Return source coverage summaries as JSON."""
        return _json(
            _service(
                None,
                vector_dir,
                corpus_path,
                embedding_model,
                disable_fallback,
            ).list_sources()
        )

    @mcp.resource(
        "redflag://sources/{source_id}",
        name="source_detail",
        description="Bounded AML red flag source detail by source identifier.",
        mime_type="application/json",
    )
    def source_detail(source_id: str, ctx: Context | None = None) -> str:
        """Return one source detail as JSON."""
        return _json(
            _service(
                ctx,
                vector_dir,
                corpus_path,
                embedding_model,
                disable_fallback,
            ).get_source(source_id)
        )


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _service(
    ctx: Context | None,
    vector_dir: Path,
    corpus_path: Path | None,
    embedding_model: EmbeddingModel | None,
    disable_fallback: bool,
) -> RedFlagService:
    if disable_fallback:
        if ctx is None:
            raise RuntimeError("Hosted resources require activated corpus state")
        return _service_from_context(ctx)
    if ctx is None:
        if corpus_path is not None:
            return RedFlagService.from_corpus_path(
                corpus_path,
                embedding_model=embedding_model,
            )
        return RedFlagService.from_vector_dir(
            vector_dir=vector_dir,
            embedding_model=embedding_model,
        )
    try:
        return _service_from_context(ctx)
    except ValueError:
        if corpus_path is not None:
            return RedFlagService.from_corpus_path(
                corpus_path,
                embedding_model=embedding_model,
            )
        return RedFlagService.from_vector_dir(
            vector_dir=vector_dir,
            embedding_model=embedding_model,
        )
