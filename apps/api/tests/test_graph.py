"""Phase 5 WorkGraph Initialization — unit + integration tests.

Covers the AC set from PLAN.md Phase 5:
  - Goal / Deliverable / Constraint / Risk rows on latest requirement.
  - Deterministic mapping from ParsedRequirement → entities (no LLM).
  - Idempotent rebuild: second intake with same text doesn't double-write.
  - v+1 promotion creates v+1's own entities alongside v1's (history kept).
  - `ready_for_planning` stage requires graph entities, not just parse.
  - GET /api/projects/{id}/graph endpoint shape.
  - graph.built event with counts.
  - manual_review outcome skips graph build, surfaces graph_building stage
    only when parse is ok but entities are absent.
  - Regression: no `current_stage` column (grep guard stays in sync).
"""

from __future__ import annotations

import pytest

from workgraph_agents import ParsedRequirement
from workgraph_agents.testing import StubClarificationAgent, StubRequirementAgent
from workgraph_persistence import (
    ConstraintRow,
    DeliverableRow,
    EventRepository,
    GoalRow,
    ProjectGraphRepository,
    RequirementRepository,
    RiskRow,
    project_stage,
    session_scope,
)

from workgraph_api.services import ClarificationService, IntakeService


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _intake_once(client, *, source_event_id: str = "graph-setup") -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": source_event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


# ---------- deterministic projection --------------------------------------


@pytest.mark.asyncio
async def test_intake_projects_parsed_requirement_to_graph(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    async with session_scope(maker) as session:
        latest = await RequirementRepository(session).latest_for_project(project_id)
        rows = await ProjectGraphRepository(session).list_all(latest.id)

    # StubRequirementAgent default: goal + 2 scope_items + no deadline.
    assert len(rows["goals"]) == 1
    assert rows["goals"][0].title == "stub goal"
    assert rows["goals"][0].sort_order == 0
    assert rows["goals"][0].status == "open"

    assert len(rows["deliverables"]) == 2
    titles = [d.title for d in rows["deliverables"]]
    assert titles == ["stub item 1", "stub item 2"]
    assert all(d.kind == "feature" for d in rows["deliverables"])
    assert [d.sort_order for d in rows["deliverables"]] == [0, 1]

    # No deadline in stub → no deadline constraint.
    assert rows["constraints"] == []
    # Risks are left empty at Phase 5.
    assert rows["risks"] == []


@pytest.mark.asyncio
async def test_intake_with_deadline_writes_deadline_constraint(api_env):
    client, maker, _, _, _, _ = api_env

    # Override the stub to include a deadline.
    parsed = ParsedRequirement(
        goal="Launch event registration",
        scope_items=["invitation code", "phone validation"],
        deadline="2026-04-24",
        open_questions=[],
        confidence=0.9,
    )
    req_agent = StubRequirementAgent(parsed=parsed)
    # Rewire the clarification service with the same stub so v+1 flows stay consistent.
    client._transport.app.state.intake_service = IntakeService(
        maker, client._transport.app.state.event_bus, agent=req_agent
    )

    r = await client.post(
        "/api/intake/message",
        json={"text": "x", "source_event_id": "graph-deadline"},
    )
    assert r.status_code == 200
    project_id = r.json()["project"]["id"]

    async with session_scope(maker) as session:
        latest = await RequirementRepository(session).latest_for_project(project_id)
        constraints = await ProjectGraphRepository(session).list_constraints(latest.id)

    assert len(constraints) == 1
    c = constraints[0]
    assert c.kind == "deadline"
    assert c.severity == "high"
    assert "2026-04-24" in c.content


@pytest.mark.asyncio
async def test_manual_review_skips_graph_build(api_env):
    client, maker, _, _, _, _ = api_env

    req_agent = StubRequirementAgent(outcome="manual_review", attempts=3)
    client._transport.app.state.intake_service = IntakeService(
        maker, client._transport.app.state.event_bus, agent=req_agent
    )

    r = await client.post(
        "/api/intake/message",
        json={"text": "garbled", "source_event_id": "graph-manual-review"},
    )
    assert r.status_code == 200
    project_id = r.json()["project"]["id"]

    async with session_scope(maker) as session:
        latest = await RequirementRepository(session).latest_for_project(project_id)
        rows = await ProjectGraphRepository(session).list_all(latest.id)
        events = await EventRepository(session).list_by_name("graph.built")

    assert rows["goals"] == []
    assert rows["deliverables"] == []
    assert rows["constraints"] == []
    assert len(events) == 1
    assert events[0].payload["outcome"] == "skipped"
    assert events[0].payload["reason"] == "no-parse"


@pytest.mark.asyncio
async def test_graph_built_event_carries_counts(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("graph.built")

    assert len(events) == 1
    payload = events[0].payload
    assert payload["project_id"] == project_id
    assert payload["outcome"] == "ok"
    assert payload["source"] == "intake"
    assert payload["goal_count"] == 1
    assert payload["deliverable_count"] == 2
    assert payload["constraint_count"] == 0
    assert payload["risk_count"] == 0
    assert payload["requirement_version"] == 1


# ---------- idempotence ----------------------------------------------------


@pytest.mark.asyncio
async def test_graph_build_is_idempotent_per_requirement(api_env):
    client, maker, bus, _, _, _ = api_env
    project_id = await _intake_once(client)

    async with session_scope(maker) as session:
        latest = await RequirementRepository(session).latest_for_project(project_id)
        repo = ProjectGraphRepository(session)
        before = await repo.list_all(latest.id)
        # Call append_for_requirement again with the same data — should be no-op.
        result = await repo.append_for_requirement(
            project_id=project_id,
            requirement_id=latest.id,
            goals=[{"title": "should be ignored"}],
            deliverables=[{"title": "also ignored"}],
            constraints=[],
            risks=[],
        )
        after = await repo.list_all(latest.id)

    # The repo returns the existing rows, not the new ones.
    assert [g.id for g in result["goals"]] == [g.id for g in before["goals"]]
    assert [g.title for g in result["goals"]] == [g.title for g in before["goals"]]
    assert len(after["goals"]) == 1
    assert len(after["deliverables"]) == 2


# ---------- v+1 history preserved -----------------------------------------


@pytest.mark.asyncio
async def test_clarify_reply_builds_v2_graph_and_keeps_v1(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client, source_event_id="graph-v2-setup")

    # Generate + answer all clarifications to promote to v2.
    clar = await client.post(f"/api/projects/{project_id}/clarify")
    questions = clar.json()["questions"]
    assert len(questions) > 0
    for q in questions:
        r = await client.post(
            f"/api/projects/{project_id}/clarify-reply",
            json={"question_id": q["id"], "answer": "answer-for-v2"},
        )
        assert r.status_code == 200
    assert r.json()["promoted"] is True
    assert r.json()["requirement_version"] == 2

    async with session_scope(maker) as session:
        # Two versions of the requirement now exist.
        from sqlalchemy import select
        from workgraph_persistence import RequirementRow
        versions = (
            await session.execute(
                select(RequirementRow)
                .where(RequirementRow.project_id == project_id)
                .order_by(RequirementRow.version)
            )
        ).scalars().all()
        assert [v.version for v in versions] == [1, 2]

        repo = ProjectGraphRepository(session)
        v1_rows = await repo.list_all(versions[0].id)
        v2_rows = await repo.list_all(versions[1].id)

    # v1 graph still intact.
    assert len(v1_rows["goals"]) == 1
    assert len(v1_rows["deliverables"]) == 2

    # v2 graph is separately present — same stub parsed output, so same counts.
    assert len(v2_rows["goals"]) == 1
    assert len(v2_rows["deliverables"]) == 2
    # Different row IDs between versions (new entities, not shared).
    assert v1_rows["goals"][0].id != v2_rows["goals"][0].id


@pytest.mark.asyncio
async def test_graph_built_event_fires_on_v2_promotion(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client, source_event_id="graph-v2-event")
    clar = await client.post(f"/api/projects/{project_id}/clarify")
    for q in clar.json()["questions"]:
        await client.post(
            f"/api/projects/{project_id}/clarify-reply",
            json={"question_id": q["id"], "answer": "yes"},
        )

    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("graph.built")

    # 1 build for intake + 1 build for v2.
    assert len(events) == 2
    assert events[0].payload["source"] == "intake"
    assert events[0].payload["requirement_version"] == 1
    assert events[1].payload["source"] == "clarification-reply"
    assert events[1].payload["requirement_version"] == 2


# ---------- stage derivation ----------------------------------------------


@pytest.mark.asyncio
async def test_stage_ready_for_planning_requires_graph_entities(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client, source_event_id="graph-stage-ok")

    async with session_scope(maker) as session:
        info = await project_stage(session, project_id)

    assert info.stage == "ready_for_planning"
    assert info.graph_counts == {
        "goals": 1,
        "deliverables": 2,
        "constraints": 0,
        "risks": 0,
    }


@pytest.mark.asyncio
async def test_stage_graph_building_when_parse_ok_but_graph_empty(api_env):
    """If we disabled the builder, parse=ok alone should NOT be ready_for_planning."""
    client, maker, _, _, _, _ = api_env

    # Build an intake path that bypasses the graph builder entirely.
    bus = client._transport.app.state.event_bus
    req_agent = StubRequirementAgent()

    from workgraph_persistence import DuplicateIntakeError, IntakeRepository
    from datetime import datetime, timezone

    # Manually write an ok-parsed requirement but no graph rows.
    async with session_scope(maker) as session:
        project, requirement, _ = await IntakeRepository(session).create(
            source="test",
            source_event_id="stage-graph-building",
            title="title",
            raw_text="raw",
            payload={},
        )
        requirement.parsed_json = {
            "goal": "g",
            "scope_items": ["a"],
            "deadline": None,
            "open_questions": [],
            "confidence": 0.9,
        }
        requirement.parse_outcome = "ok"
        requirement.parsed_at = datetime.now(timezone.utc)
        pid = project.id

    async with session_scope(maker) as session:
        info = await project_stage(session, pid)

    assert info.stage == "graph_building"
    assert info.parse_outcome == "ok"
    assert info.graph_counts["goals"] == 0
    assert info.graph_counts["deliverables"] == 0


# ---------- graph endpoint ------------------------------------------------


@pytest.mark.asyncio
async def test_get_graph_endpoint_returns_full_shape(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client, source_event_id="graph-endpoint")

    r = await client.get(f"/api/projects/{project_id}/graph")
    assert r.status_code == 200
    body = r.json()

    assert body["project_id"] == project_id
    assert body["requirement_version"] == 1
    assert len(body["goals"]) == 1
    assert body["goals"][0]["title"] == "stub goal"
    assert body["goals"][0]["status"] == "open"
    assert len(body["deliverables"]) == 2
    assert body["deliverables"][0]["kind"] == "feature"
    assert body["constraints"] == []
    assert body["risks"] == []


@pytest.mark.asyncio
async def test_get_graph_unknown_project_returns_404(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.get("/api/projects/does-not-exist/graph")
    assert r.status_code == 404


# Regression guard for decision 1E lives in test_clarification.py
# (test_no_current_stage_column_is_written). One grep is enough —
# duplicating it here would just mean two files to keep in sync.
