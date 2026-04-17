"""DeepSeek smoke test. Skipped automatically if no API key is configured —
keeps the main suite green in CI environments without secrets."""

from __future__ import annotations

import os

import pytest

from workgraph_agents import LLMClient, load_llm_settings

skip_if_no_key = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set",
)


@skip_if_no_key
@pytest.mark.asyncio
async def test_deepseek_hello_world():
    client = LLMClient(load_llm_settings())
    result = await client.complete(
        [
            {"role": "system", "content": "Respond with one word only."},
            {"role": "user", "content": "Say: ok"},
        ],
        temperature=0.0,
    )
    assert result.content.strip()
    assert result.model
    assert result.latency_ms > 0


@skip_if_no_key
@pytest.mark.asyncio
async def test_deepseek_json_mode():
    client = LLMClient(load_llm_settings())
    data, result = await client.complete_json(
        [
            {"role": "system", "content": "Respond with JSON only."},
            {"role": "user", "content": 'Return {"status": "ok"}'},
        ],
    )
    assert data.get("status") == "ok"
    assert result.prompt_tokens >= 0
