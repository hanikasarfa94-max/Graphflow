"""Phase 10 — DeliveryService + API integration tests.

Covers:
  1. Happy path — generate after plan + decision; summary cites scope items
     and the approved decision; persists DeliverySummaryRow, emits
     delivery.generated event.
  2. QA coverage gap — a plan with a disjoint task (no overlap with scope
     items) yields `parse_outcome=manual_review` and delivery.qa_failed
     event; uncovered list reflects the gap.
  3. Non-member → 403 on POST, GET, and /history.
  4. History endpoint surfaces every regeneration.
  5. /state composite now includes `delivery` (latest or null).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from workgraph_agents import (
    CompletedScopeItem,
    DeferredScopeItem,
    DeliverySummaryDoc,
    KeyDecision,
    RemainingRisk,
    ParsedPlan,
    PlannedTask,
)
from workgraph_agents.testing import StubDeliveryAgent, StubPlanningAgent
from workgraph_api.main import app
from workgraph_persistence import (
    DeliverySummaryRepository,
    EventRepository,
    session_scope,
)

CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _register(client: AsyncClient, username: str, password: str = "hunter22"):
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _intake(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


def _alt_client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _setup(client: AsyncClient, event_id: str, owner: str) -> str:
    await _register(client, owner)
    project_id = await _intake(client, event_id)
    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200, r.text
    return project_id


# ---------- happy path -------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_happy_path(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _setup(client, "delivery-1", "owner_dl1")

    r = await client.post(f"/api/projects/{project_id}/delivery")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    delivery = body["delivery"]
    assert delivery["parse_outcome"] in ("ok", "retry")
    content = delivery["content"]
    # StubRequirementAgent parses two scope items ("stub item 1/2"); the
    # StubPlanningAgent covers each with a 1-for-1 task ("Build stub item 1"),
    # so both should land in completed_scope.
    covered_items = {c["scope_item"] for c in content["completed_scope"]}
    assert covered_items == {"stub item 1", "stub item 2"}
    # No scope item uncovered + no defer decision → no deferred entries.
    assert content["deferred_scope"] == []
    assert content["headline"]

    # Snapshot persisted with qa_report.
    async with session_scope(maker) as session:
        row = await DeliverySummaryRepository(session).latest_for_project(
            project_id
        )
        events = await EventRepository(session).list_by_name(
            "delivery.generated"
        )
    assert row is not None
    assert row.qa_report["uncovered"] == []
    assert events and events[0].payload["project_id"] == project_id


# ---------- QA pre-check fails ----------------------------------------


@pytest.mark.asyncio
async def test_delivery_manual_review_when_scope_uncovered(api_env):
    client, maker, _, _, _, _ = api_env
    # Swap in a planning agent that produces a plan with NO coverage for
    # the canonical scope items. A single cross-cutting "configure
    # infrastructure" task has zero shared tokens with "stub item 1/2".
    barren_plan = ParsedPlan(
        tasks=[
            PlannedTask(
                ref="T1",
                title="Configure infrastructure",
                description="Unrelated cross-cutting work.",
                deliverable_ref=None,
                assignee_role="backend",
                estimate_hours=4,
                acceptance_criteria=["pipeline green"],
            )
        ],
        dependencies=[],
        milestones=[],
        risks=[],
    )
    app.state.planning_agent = StubPlanningAgent(plan=barren_plan)
    app.state.planning_service._agent = app.state.planning_agent

    try:
        project_id = await _setup(client, "delivery-2", "owner_dl2")
        r = await client.post(f"/api/projects/{project_id}/delivery")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["delivery"]["parse_outcome"] == "manual_review"
        uncovered = body["delivery"]["qa_report"]["uncovered"]
        assert sorted(uncovered) == ["stub item 1", "stub item 2"]

        async with session_scope(maker) as session:
            qa_events = await EventRepository(session).list_by_name(
                "delivery.qa_failed"
            )
        assert qa_events
        assert sorted(qa_events[0].payload["uncovered"]) == [
            "stub item 1",
            "stub item 2",
        ]
    finally:
        # Restore default plan agent so other tests in this module aren't
        # affected by the session-scoped app.state mutation.
        app.state.planning_agent = StubPlanningAgent()
        app.state.planning_service._agent = app.state.planning_agent


# ---------- membership guard ------------------------------------------


@pytest.mark.asyncio
async def test_non_member_cannot_access_delivery(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _setup(client, "delivery-3", "owner_dl3")

    async with _alt_client() as outsider:
        await _register(outsider, "stranger_dl3")
        r = await outsider.post(f"/api/projects/{project_id}/delivery")
        assert r.status_code == 403
        r = await outsider.get(f"/api/projects/{project_id}/delivery")
        assert r.status_code == 403
        r = await outsider.get(f"/api/projects/{project_id}/delivery/history")
        assert r.status_code == 403


# ---------- history -----------------------------------------------------


@pytest.mark.asyncio
async def test_delivery_history_and_state_composite(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _setup(client, "delivery-4", "owner_dl4")

    for _ in range(3):
        r = await client.post(f"/api/projects/{project_id}/delivery")
        assert r.status_code == 200

    r = await client.get(f"/api/projects/{project_id}/delivery/history")
    assert r.status_code == 200
    rows = r.json()["deliveries"]
    assert len(rows) == 3
    # Ordered newest first.
    assert rows[0]["created_at"] >= rows[1]["created_at"] >= rows[2]["created_at"]

    # /state composite exposes only the latest.
    r = await client.get(f"/api/projects/{project_id}/state")
    assert r.status_code == 200
    body = r.json()
    assert "delivery" in body
    assert body["delivery"]["id"] == rows[0]["id"]

    # GET /delivery returns same latest.
    r = await client.get(f"/api/projects/{project_id}/delivery")
    assert r.status_code == 200
    assert r.json()["delivery"]["id"] == rows[0]["id"]


# ---------- custom LLM doc with deferred scope + key decisions --------


@pytest.mark.asyncio
async def test_delivery_cites_decisions_and_deferred_scope(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _setup(client, "delivery-5", "owner_dl5")

    # Pin the stub so the test asserts on an LLM-shape payload rather than
    # relying on keyword-token heuristics. The shape contract is what the
    # UI renders.
    pinned_doc = DeliverySummaryDoc(
        headline="Event signup ships; export deferred.",
        narrative="Two scope items landed. Admin export was deferred via decision.",
        completed_scope=[
            CompletedScopeItem(
                scope_item="stub item 1", evidence_task_ids=["t-1"]
            ),
        ],
        deferred_scope=[
            DeferredScopeItem(
                scope_item="stub item 2",
                reason="Deferred to post-launch per PM call.",
                decision_id=None,
            )
        ],
        key_decisions=[
            KeyDecision(
                decision_id="d-fake",
                headline="Cut admin export from v1",
                rationale="Unblocks FE + BE critical path.",
            )
        ],
        remaining_risks=[
            RemainingRisk(
                title="Export parity",
                content="Customers may expect export at launch.",
                severity="medium",
            )
        ],
    )
    app.state.delivery_agent = StubDeliveryAgent(doc=pinned_doc)
    app.state.delivery_service._agent = app.state.delivery_agent

    try:
        r = await client.post(f"/api/projects/{project_id}/delivery")
        assert r.status_code == 200, r.text
        body = r.json()
        content = body["delivery"]["content"]
        assert content["headline"].startswith("Event signup")
        assert any(
            kd["headline"].startswith("Cut admin export")
            for kd in content["key_decisions"]
        )
        assert any(
            ds["scope_item"] == "stub item 2"
            for ds in content["deferred_scope"]
        )
    finally:
        app.state.delivery_agent = StubDeliveryAgent()
        app.state.delivery_service._agent = app.state.delivery_agent
