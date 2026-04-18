"""Fault-injection for the Planning recovery ladder (decision 2C4).

Simulates a wedged LLM that always returns malformed JSON. `/plan` must:
  1) Never raise — request completes with 200.
  2) Persist zero tasks/dependencies/milestones (empty fallback).
  3) Surface outcome=manual_review on the agent_run_log row with attempts=3.
  4) Emit a planning.produced event with outcome=manual_review + zero counts.

This guards the "never 500" clause in 2C4 for the Planning Agent.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from workgraph_agents import PlanningAgent
from workgraph_agents.llm import LLMClient, LLMResult, LLMSettings
from workgraph_agents.testing import StubClarificationAgent, StubRequirementAgent
from workgraph_domain import EventBus
from workgraph_persistence import (
    AgentRunLogRepository,
    EventRepository,
    PlanRepository,
    RequirementRepository,
    build_engine,
    build_sessionmaker,
    create_all,
    drop_all,
    session_scope,
)

from workgraph_api.main import app
from workgraph_api.services import (
    ClarificationService,
    IntakeService,
    PlanningService,
)


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
            content="this is not JSON at all, it's prose",
            model=self._settings.model,
            prompt_tokens=12,
            completion_tokens=6,
            latency_ms=2,
            cache_read_tokens=0,
        )


@pytest_asyncio.fixture
async def faulty_env() -> Any:
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    maker = build_sessionmaker(engine)
    bus = EventBus(maker)

    # Intake + clarification stay deterministic — only planning sees the wedge.
    intake_agent = StubRequirementAgent()
    clar_agent = StubClarificationAgent()
    intake_service = IntakeService(maker, bus, agent=intake_agent)
    clar_service = ClarificationService(
        maker, bus,
        clarification_agent=clar_agent,
        requirement_agent=intake_agent,
    )

    # Planning: real agent pointed at the wedged LLM.
    plan_agent = PlanningAgent(
        llm=_AlwaysMalformedLLM(), prompt="(prompt-ignored)"
    )
    plan_service = PlanningService(maker, bus, agent=plan_agent)

    app.state.engine = engine
    app.state.sessionmaker = maker
    app.state.event_bus = bus
    app.state.intake_service = intake_service
    app.state.clarification_service = clar_service
    app.state.planning_service = plan_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, maker
    await drop_all(engine)
    await engine.dispose()


@pytest.mark.asyncio
async def test_malformed_llm_degrades_to_manual_review(faulty_env):
    client, maker = faulty_env

    r = await client.post(
        "/api/intake/message",
        json={
            "text": (
                "We need to launch an event registration page next week. "
                "It needs invitation code validation, phone number validation, "
                "admin export, and conversion tracking."
            ),
            "source_event_id": "plan-fi-1",
        },
    )
    assert r.status_code == 200
    project_id = r.json()["project"]["id"]

    # /plan must not raise even though every LLM call returns garbage.
    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "manual_review"
    assert body["tasks"] == []
    assert body["dependencies"] == []
    assert body["milestones"] == []

    async with session_scope(maker) as session:
        rows = await AgentRunLogRepository(session).list_for_agent("planning")
        assert len(rows) == 1
        assert rows[0].outcome == "manual_review"
        assert rows[0].attempts == 3
        assert rows[0].error is not None

        events = await EventRepository(session).list_by_name("planning.produced")
        assert len(events) == 1
        p = events[0].payload
        assert p["outcome"] == "manual_review"
        assert p["task_count"] == 0
        assert p["dependency_count"] == 0
        assert p["milestone_count"] == 0
        assert p["attempts"] == 3

        # Nothing persisted.
        latest = await RequirementRepository(session).latest_for_project(project_id)
        plan_rows = await PlanRepository(session).list_all(latest.id)
        assert plan_rows["tasks"] == []
        assert plan_rows["dependencies"] == []
        assert plan_rows["milestones"] == []
