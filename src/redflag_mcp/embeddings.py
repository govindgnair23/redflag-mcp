from __future__ import annotations

import sys
from contextlib import redirect_stdout
from functools import lru_cache
from typing import Protocol, cast

from redflag_mcp.config import EMBEDDING_DIM

MODEL_NAME = "nomic-ai/nomic-embed-text-v1.5"
DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "


class EmbeddingModel(Protocol):
    def encode(self, sentences: list[str], **kwargs: object) -> object:
        """Encode text into embedding vectors."""


@lru_cache(maxsize=1)
def load_model() -> EmbeddingModel:
    from sentence_transformers import SentenceTransformer

    with redirect_stdout(sys.stderr):
        return cast(
            EmbeddingModel,
            SentenceTransformer(MODEL_NAME, trust_remote_code=True),
        )


def encode_documents(texts: list[str], model: EmbeddingModel | None = None) -> list[list[float]]:
    return _encode([f"{DOCUMENT_PREFIX}{text}" for text in texts], model=model)


def encode_query(text: str, model: EmbeddingModel | None = None) -> list[float]:
    return _encode([f"{QUERY_PREFIX}{text}"], model=model)[0]


def _encode(texts: list[str], model: EmbeddingModel | None = None) -> list[list[float]]:
    encoder = model or load_model()
    with redirect_stdout(sys.stderr):
        raw_vectors = encoder.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
    vectors = _to_vector_lists(raw_vectors)
    for vector in vectors:
        if len(vector) != EMBEDDING_DIM:
            raise ValueError(
                f"embedding vector must contain {EMBEDDING_DIM} values, got {len(vector)}"
            )
    return vectors


def _to_vector_lists(raw_vectors: object) -> list[list[float]]:
    if hasattr(raw_vectors, "tolist"):
        raw_vectors = raw_vectors.tolist()

    if not isinstance(raw_vectors, list):
        raise TypeError("embedding model returned an unsupported vector type")

    vectors: list[list[float]] = []
    for raw_vector in raw_vectors:
        if hasattr(raw_vector, "tolist"):
            raw_vector = raw_vector.tolist()
        if not isinstance(raw_vector, list):
            raise TypeError("embedding model returned an unsupported vector row type")
        vectors.append([float(value) for value in raw_vector])
    return vectors
