"""Fault-injection tests for the Phase 3 recovery ladder (decision 2C4).

Simulates a wedged LLM that always returns malformed JSON. The intake
path must:
  1) Never raise — request completes with a valid response.
  2) Surface a manual_review flag on the requirement row.
  3) Persist a structured parsed_json placeholder (not NULL).
  4) Emit a requirement.parsed event with outcome=manual_review.

This guards the "never 500" clause in 2C4.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from workgraph_agents import RequirementAgent
from workgraph_agents.llm import LLMClient, LLMResult, LLMSettings
from workgraph_domain import EventBus
from workgraph_persistence import (
    EventRepository,
    build_engine,
    build_sessionmaker,
    create_all,
    drop_all,
    session_scope,
)

from workgraph_api.main import app
from workgraph_api.services import IntakeService


class _AlwaysMalformedLLM(LLMClient):
    """LLMClient whose every chat completion returns non-JSON garbage.

    Exercises the full recovery ladder — JSON parse fails 3x → ParseFailure →
    agent returns manual_review outcome.
    """

    def __init__(self) -> None:
        # Bypass real LLMSettings validation (no API key needed in unit test).
        self._settings = LLMSettings.model_construct(
            api_key="test-not-used",
            base_url="http://stub",
            model="stub-model",
        )
        self._client = None  # never used — we override complete().
        self.calls = 0

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        response_format: dict | None = None,
    ) -> LLMResult:
        self.calls += 1
        return LLMResult(
            content="this is not JSON at all, sorry",
            model=self._settings.model,
            prompt_tokens=10,
            completion_tokens=8,
            latency_ms=1,
            cache_read_tokens=0,
        )


@pytest_asyncio.fixture
async def faulty_env() -> Any:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    maker = build_sessionmaker(engine)
    bus = EventBus(maker)
    # Inject a wedged LLM into the real RequirementAgent (not the stub).
    agent = RequirementAgent(llm=_AlwaysMalformedLLM(), prompt="(prompt-ignored)")
    service = IntakeService(maker, bus, agent=agent)

    app.state.engine = engine
    app.state.sessionmaker = maker
    app.state.event_bus = bus
    app.state.intake_service = service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, maker, agent
    await drop_all(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_malformed_llm_degrades_to_manual_review(faulty_env):
    """AC 2C4: fault injection asserts graceful degradation, never 500."""
    client, maker, _agent = faulty_env
    resp = await client.post(
        "/api/intake/message",
        json={"text": "whatever the LLM is broken today", "source_event_id": "fi-1"},
    )

    # 1) Never 500.
    assert resp.status_code == 200, resp.text
    body = resp.json()
    req = body["requirement"]

    # 2) manual_review surfaced on the requirement row.
    assert req["parse_outcome"] == "manual_review"
    assert req["parsed_at"] is not None

    # 3) parsed_json is the structured placeholder — not null.
    parsed = req["parsed_json"]
    assert parsed is not None
    assert parsed["confidence"] == 0.0
    assert "manual review" in parsed["goal"].lower()
    assert len(parsed["open_questions"]) >= 1

    # 4) requirement.parsed event with outcome=manual_review.
    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("requirement.parsed")
    assert len(events) == 1
    assert events[0].payload["outcome"] == "manual_review"
    assert events[0].payload["attempts"] == 3


@pytest.mark.asyncio
async def test_manual_review_writes_agent_run_log(faulty_env):
    """agent_run_log row exists with outcome=manual_review (2C2)."""
    from workgraph_persistence import AgentRunLogRepository

    client, maker, _agent = faulty_env
    resp = await client.post(
        "/api/intake/message",
        json={"text": "broken llm test", "source_event_id": "fi-log-1"},
    )
    assert resp.status_code == 200

    async with session_scope(maker) as session:
        rows = await AgentRunLogRepository(session).list_for_agent("requirement")
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == "manual_review"
    assert row.attempts == 3
    assert row.prompt_version  # bumped in Phase 3
    assert row.error is not None
