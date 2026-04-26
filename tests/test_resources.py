from __future__ import annotations

import asyncio
import json

from redflag_mcp.config import EMBEDDING_DIM
from redflag_mcp.models import RedFlagRecord
from redflag_mcp.server import create_server
from redflag_mcp.vectorstore import get_or_create_table, open_store, upsert_records


class FakeModel:
    def encode(self, sentences: list[str], **kwargs: object) -> list[list[float]]:
        return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in sentences]


def vector(first_value: float) -> list[float]:
    return [first_value] + [0.0] * (EMBEDDING_DIM - 1)


async def read_resource_json(app, uri: str) -> dict:
    async with app._mcp_server.lifespan(app._mcp_server):
        contents = await app.read_resource(uri)
    return json.loads(contents[0].content)


def test_source_catalog_resource_matches_source_summaries(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            RedFlagRecord(
                id="one",
                description="A red flag.",
                regulatory_source="FinCEN Alert",
                source_url="https://example.com/source.pdf",
                vector=vector(1.0),
            )
        ],
    )
    app = create_server(vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    resources = asyncio.run(app.list_resources())
    payload = asyncio.run(read_resource_json(app, "redflag://sources"))

    assert [str(resource.uri) for resource in resources] == ["redflag://sources"]
    assert payload["source_count"] == 1
    assert payload["sources"][0]["source_id"].startswith("url-")
    assert "vector" not in json.dumps(payload)


def test_source_detail_resource_template_returns_bounded_detail(tmp_vectors_dir):
    table = get_or_create_table(open_store(tmp_vectors_dir))
    upsert_records(
        table,
        [
            RedFlagRecord(
                id="one",
                description="A red flag.",
                regulatory_source="FinCEN Alert",
                source_url="https://example.com/source.pdf",
                vector=vector(1.0),
            )
        ],
    )
    app = create_server(vector_dir=tmp_vectors_dir, embedding_model=FakeModel())
    catalog = asyncio.run(read_resource_json(app, "redflag://sources"))
    source_id = catalog["sources"][0]["source_id"]

    templates = asyncio.run(app.list_resource_templates())
    payload = asyncio.run(read_resource_json(app, f"redflag://sources/{source_id}"))

    assert [str(template.uriTemplate) for template in templates] == [
        "redflag://sources/{source_id}"
    ]
    assert payload["source"]["source_id"] == source_id
    assert payload["source"]["red_flags"][0]["id"] == "one"


def test_source_catalog_resource_empty_store_matches_tool_message(tmp_vectors_dir):
    app = create_server(vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    payload = asyncio.run(read_resource_json(app, "redflag://sources"))

    assert payload["sources"] == []
    assert "No red flags are available yet" in payload["message"]
