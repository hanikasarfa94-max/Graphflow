"""Phase 13 — canonical event registration demo fixture (authoritative).

This test is the one-stop E2E that drives every LLM service the demo
touches: intake → clarification → planning → conflict recheck → decision
→ delivery. It is the fixture demo-day dry runs pin themselves against.

Success criteria (from PLAN.md Phase 13 AC):

  * Runs end-to-end with warm-cache (stub agents) in under 90 seconds.
  * Every stage asserts its own output, not just the terminal one — if
    any leg regresses, the test names the leg.
  * Final delivery covers both scope items produced by the stub
    requirement agent and records the approved decision.
  * A trace_id is produced per request (the middleware) and the final
    delivery row carries one.

The canonical walker lives in `workgraph_api.demo_seed` and is shared
with `POST /api/demo/seed`; tests assert on its return value plus the
same side-effects a demo-day operator would care about.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from workgraph_api.demo_seed import (
    CANONICAL_TEXT,
    run_canonical_demo,
)
from workgraph_api.main import app
from workgraph_persistence import (
    AgentRunLogRepository,
    ConflictRepository,
    DecisionRepository,
    DeliverySummaryRepository,
    EventRepository,
    session_scope,
)

# The 90s figure is the demo-day budget. With stub agents this comes in
# under a second; anything over a few seconds on stubs means something
# has regressed materially.
DEMO_BUDGET_SECONDS = 90.0


@pytest.mark.asyncio
async def test_canonical_event_registration_end_to_end(api_env):
    """The authoritative demo fixture.

    Walks the whole graph from raw text through a delivery summary and
    asserts at every leg. A single failing leg should name its own
    stage so the demo's failure mode is never "something broke".
    """
    client, maker, _, _, _, _ = api_env

    result = await run_canonical_demo(
        client,
        app_state=app.state,
        username="demo_owner_e2e",
        source_event_id="demo-canonical-e2e",
    )

    # --- shape assertions on the walker's return --------------------
    assert result.requirement_version == 2, (
        f"clarifications should have promoted to v2; got {result.requirement_version}"
    )
    assert 1 <= len(result.clarification_ids) <= 3, result.clarification_ids
    assert result.delivery_trace_id and len(result.delivery_trace_id) == 32
    # Stub requirement agent emits two scope items; stub planning covers
    # both 1-for-1, so both must land in the delivery summary.
    assert set(result.completed_scope_items) == {"stub item 1", "stub item 2"}, (
        f"delivery did not cover all scope items: {result.completed_scope_items}"
    )
    assert result.elapsed_seconds < DEMO_BUDGET_SECONDS, (
        f"canonical demo ran {result.elapsed_seconds:.1f}s, over the "
        f"{DEMO_BUDGET_SECONDS:.0f}s demo-day budget"
    )

    # --- cross-check persistence ------------------------------------
    async with session_scope(maker) as session:
        summary = await DeliverySummaryRepository(session).latest_for_project(
            result.project_id
        )
        assert summary is not None
        assert summary.id == result.delivery_id
        assert summary.trace_id == result.delivery_trace_id

        run_rows = await AgentRunLogRepository(session).list_since(limit=500)
        agents = {r.agent for r in run_rows}
        assert {"requirement", "clarification", "planning", "delivery"}.issubset(
            agents
        ), f"missing agent_run_log coverage; agents={agents}"
        for row in run_rows:
            if row.project_id == result.project_id:
                assert row.trace_id and len(row.trace_id) == 32, (
                    f"{row.agent} row missing trace_id: {row.trace_id!r}"
                )

        events = await EventRepository(session).list_for_trace(
            result.delivery_trace_id
        )
        event_names = {e.name for e in events}
        assert "delivery.generated" in event_names, (
            f"delivery.generated missing; got {event_names}"
        )

        dec_rows = await DecisionRepository(session).list_for_project(
            result.project_id, limit=10
        )
        assert any(d.id == result.decision_id for d in dec_rows), (
            "submitted decision not in history"
        )

        conflict_row = await ConflictRepository(session).get(result.conflict_id)
        assert conflict_row is not None
        assert conflict_row.status == "resolved", (
            f"conflict should be resolved after decision; got {conflict_row.status}"
        )


@pytest.mark.asyncio
async def test_stage_progression_during_canonical_walk(api_env):
    """The derived stage flips correctly at each leg.

    We walk a parallel canonical path here — not reusing the seed
    helper — so any regression in stage derivation surfaces as a
    separate test, not as a confusing secondary failure on the E2E.
    """
    client, _, _, _, _, _ = api_env

    r = await client.post(
        "/api/auth/register",
        json={"username": "demo_owner_stage", "password": "hunter22"},
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        "/api/intake/message",
        json={
            "text": CANONICAL_TEXT,
            "source_event_id": "demo-canonical-stage",
        },
    )
    assert r.status_code == 200
    project_id = r.json()["project"]["id"]

    # After intake with parse_outcome=ok and no questions yet → ready_for_planning.
    r = await client.get(f"/api/projects/{project_id}/stage")
    assert r.status_code == 200
    assert r.json()["stage"] == "ready_for_planning"

    # After /clarify → clarification_pending.
    r = await client.post(f"/api/projects/{project_id}/clarify")
    assert r.status_code == 200
    questions = r.json()["questions"]
    r = await client.get(f"/api/projects/{project_id}/stage")
    assert r.status_code == 200
    assert r.json()["stage"] == "clarification_pending"

    # Answering one → clarification_in_progress.
    first = await client.post(
        f"/api/projects/{project_id}/clarify-reply",
        json={"question_id": questions[0]["id"], "answer": "one"},
    )
    assert first.status_code == 200
    r = await client.get(f"/api/projects/{project_id}/stage")
    assert r.json()["stage"] == "clarification_in_progress"

    # Answering the rest → ready_for_planning again (v+1).
    for q in questions[1:]:
        r = await client.post(
            f"/api/projects/{project_id}/clarify-reply",
            json={"question_id": q["id"], "answer": "rest"},
        )
        assert r.status_code == 200
    r = await client.get(f"/api/projects/{project_id}/stage")
    assert r.json()["stage"] == "ready_for_planning"
    assert r.json()["requirement_version"] == 2


@pytest.mark.asyncio
async def test_demo_seed_endpoint_produces_same_final_state(api_env):
    """`POST /api/demo/seed` uses the same walker and returns the same shape.

    This proves the endpoint Playwright will hit pre-UI is a thin wrapper
    over the tested walker — no drift between the two surfaces.
    """
    client, maker, *_ = api_env

    r = await client.post("/api/demo/seed", json={"username": "demo_seed_user"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requirement_version"] == 2
    assert 1 <= len(body["clarification_ids"]) <= 3
    assert set(body["completed_scope_items"]) == {"stub item 1", "stub item 2"}
    assert body["elapsed_seconds"] >= 0

    # The referenced delivery row exists and cites the trace.
    async with session_scope(maker) as session:
        summary = await DeliverySummaryRepository(session).latest_for_project(
            body["project_id"]
        )
        assert summary is not None
        assert summary.id == body["delivery_id"]
        assert summary.trace_id == body["delivery_trace_id"]


@pytest.mark.asyncio
async def test_demo_seed_endpoint_is_disabled_in_prod(api_env, monkeypatch):
    """Guard: the seed walker must not be reachable from prod.

    The router calls `load_settings().env` on every request; patching
    the settings object at the source is enough to flip the gate
    without touching .env files.
    """
    from workgraph_api.routers import demo as demo_router
    from workgraph_api.settings import Settings

    def _prod_settings() -> Settings:
        return Settings(env="prod")

    monkeypatch.setattr(demo_router, "load_settings", _prod_settings)

    client, *_ = api_env
    r = await client.post("/api/demo/seed", json={"username": "prod_probe"})
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_demo_seed_endpoint_is_idempotent_on_repeat(api_env):
    """A second seed for the same user should succeed (login path).

    On demo-day we want to re-seed repeatedly without worrying about
    unique-username collisions. The second call logs in against the
    existing row and produces a fresh project.
    """
    client, *_ = api_env

    r1 = await client.post(
        "/api/demo/seed", json={"username": "demo_seed_user_repeat"}
    )
    assert r1.status_code == 200, r1.text

    r2 = await client.post(
        "/api/demo/seed", json={"username": "demo_seed_user_repeat"}
    )
    assert r2.status_code == 200, r2.text
    # Each seed call creates a new project — source_event_id dedup is
    # per-user, and the intake route mints a fresh project each call
    # when the default id is reused against a different (implicit)
    # actor cookie jar. If the dedup logic changes, this assertion
    # should change with it.
    assert r1.json()["project_id"] != r2.json()["project_id"] or (
        r1.json()["delivery_id"] != r2.json()["delivery_id"]
    )
