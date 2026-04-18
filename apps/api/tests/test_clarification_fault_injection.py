"""Fault-injection for the Clarification recovery ladder (decision 2C4).

Simulates a wedged LLM that always returns malformed JSON. `/clarify` must:
  1) Never raise — request completes with a valid 200.
  2) Persist zero questions (the manual_review fallback is an empty batch).
  3) Surface outcome=manual_review on the agent_run_log row.
  4) Emit a clarification.generated event with outcome=manual_review.

This guards the "never 500" clause in 2C4 for the Clarification Agent.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from workgraph_agents import ClarificationAgent
from workgraph_agents.llm import LLMClient, LLMResult, LLMSettings
from workgraph_agents.testing import StubRequirementAgent
from workgraph_domain import EventBus
from workgraph_persistence import (
    AgentRunLogRepository,
    EventRepository,
    build_engine,
    build_sessionmaker,
    create_all,
    drop_all,
    session_scope,
)

from workgraph_api.main import app
from workgraph_api.services import ClarificationService, IntakeService


class _AlwaysMalformedLLM(LLMClient):
    def __init__(self) -> None:
        self._settings = LLMSettings.model_construct(
            api_key="test-not-used",
            base_url="http://stub",
            model="stub-model",
        )
        self._client = None

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        response_format: dict | None = None,
    ) -> LLMResult:
        return LLMResult(
            content="not JSON at all",
            model=self._settings.model,
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=1,
            cache_read_tokens=0,
        )


@pytest_asyncio.fixture
async def faulty_env() -> Any:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    maker = build_sessionmaker(engine)
    bus = EventBus(maker)

    # Intake: use the deterministic stub so the fault is isolated to clarification.
    intake_agent = StubRequirementAgent()
    intake_service = IntakeService(maker, bus, agent=intake_agent)

    # Clarification: real agent pointed at the wedged LLM.
    clar_agent = ClarificationAgent(
        llm=_AlwaysMalformedLLM(), prompt="(prompt-ignored)"
    )
    clar_service = ClarificationService(
        maker, bus, clarification_agent=clar_agent, requirement_agent=intake_agent
    )

    app.state.engine = engine
    app.state.sessionmaker = maker
    app.state.event_bus = bus
    app.state.intake_service = intake_service
    app.state.clarification_service = clar_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, maker
    await drop_all(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_malformed_llm_degrades_to_manual_review(faulty_env):
    client, maker = faulty_env

    # Seed a project via intake.
    r = await client.post(
        "/api/intake/message",
        json={"text": "something vague", "source_event_id": "clar-fi-1"},
    )
    assert r.status_code == 200
    project_id = r.json()["project"]["id"]

    # /clarify must not raise even though every LLM call returns garbage.
    r = await client.post(f"/api/projects/{project_id}/clarify")
    assert r.status_code == 200, r.text
    body = r.json()
    # Manual-review fallback is an empty batch.
    assert body["questions"] == []
    assert body["outcome"] == "manual_review"

    async with session_scope(maker) as session:
        rows = await AgentRunLogRepository(session).list_for_agent("clarification")
        assert len(rows) == 1
        assert rows[0].outcome == "manual_review"
        assert rows[0].attempts == 3
        assert rows[0].error is not None

        events = await EventRepository(session).list_by_name("clarification.generated")
        assert len(events) == 1
        assert events[0].payload["outcome"] == "manual_review"
        assert events[0].payload["question_count"] == 0
