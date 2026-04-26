from __future__ import annotations

import asyncio

from redflag_mcp.config import EMBEDDING_DIM
from redflag_mcp.server import create_server


class FakeModel:
    def encode(self, sentences: list[str], **kwargs: object) -> list[list[float]]:
        return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in sentences]


def test_consultation_prompt_is_discoverable(tmp_vectors_dir):
    app = create_server(vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    prompts = asyncio.run(app.list_prompts())
    by_name = {prompt.name: prompt for prompt in prompts}

    assert sorted(by_name) == ["consult_aml_red_flags"]
    assert "follow-up" in by_name["consult_aml_red_flags"].description


def test_consultation_prompt_guides_followup_and_tool_routing(tmp_vectors_dir):
    app = create_server(vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    prompt = asyncio.run(app.get_prompt("consult_aml_red_flags"))
    text = prompt.messages[0].content.text

    assert "product/channel" in text
    assert "customer profile" in text
    assert "transaction channel or volume" in text
    assert "list_filters" in text
    assert "filter_red_flags" in text
    assert "search_red_flags" in text
    assert "list_sources" in text
    assert "get_source" in text


def test_prompt_registration_does_not_remove_existing_tools(tmp_vectors_dir):
    app = create_server(vector_dir=tmp_vectors_dir, embedding_model=FakeModel())

    tools = asyncio.run(app.list_tools())
    tool_names = {tool.name for tool in tools}

    assert {"search_red_flags", "filter_red_flags", "list_sources"}.issubset(
        tool_names
    )
