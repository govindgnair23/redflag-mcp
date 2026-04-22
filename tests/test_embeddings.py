from __future__ import annotations

import pytest

from redflag_mcp.config import EMBEDDING_DIM
from redflag_mcp.embeddings import DOCUMENT_PREFIX, QUERY_PREFIX, encode_documents, encode_query


class FakeModel:
    def __init__(self, dimension: int = EMBEDDING_DIM):
        self.dimension = dimension
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def encode(self, sentences: list[str], **kwargs: object) -> list[list[float]]:
        self.calls.append((sentences, kwargs))
        return [[float(index)] * self.dimension for index, _ in enumerate(sentences)]


def test_encode_documents_adds_document_prefix():
    model = FakeModel()

    vectors = encode_documents(["first", "second"], model=model)

    assert model.calls[0][0] == [
        f"{DOCUMENT_PREFIX}first",
        f"{DOCUMENT_PREFIX}second",
    ]
    assert model.calls[0][1]["normalize_embeddings"] is True
    assert model.calls[0][1]["show_progress_bar"] is False
    assert len(vectors) == 2
    assert len(vectors[0]) == EMBEDDING_DIM


def test_encode_query_adds_query_prefix():
    model = FakeModel()

    vector = encode_query("cash deposits", model=model)

    assert model.calls[0][0] == [f"{QUERY_PREFIX}cash deposits"]
    assert len(vector) == EMBEDDING_DIM


def test_encode_rejects_wrong_dimension():
    model = FakeModel(dimension=3)

    with pytest.raises(ValueError):
        encode_query("cash deposits", model=model)
