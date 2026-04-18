"""Phase 12 — observability aggregation + agent_run_log wiring.

These tests drive the happy-path system (intake → plan → delivery) and
then assert:

1. Every LLM agent invocation produced a row in `agent_run_logs`.
2. Every row carries the request's trace_id (populated by the
   trace_id_middleware in main.py).
3. `GET /api/observability/health` surfaces per-agent counts and
   latency percentiles with the right shape.
4. `GET /api/observability/agents` returns the most recent rows
   and respects the `agent` filter.
5. `GET /api/observability/trace/{trace_id}` pulls both the
   agent_run_logs and the events rows for one trace.

We reuse the `api_env` fixture from conftest.py so the wiring is
identical to the other integration tests.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from workgraph_persistence import (
    AgentRunLogRepository,
    EventRepository,
    session_scope,
)

CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _register(client: AsyncClient, username: str) -> None:
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


async def _drive_happy_path(client: AsyncClient, event_id: str) -> tuple[str, str]:
    """Run intake → plan → delivery so logs from 3+ agents exist.

    Returns (project_id, delivery_trace_id) — the delivery POST's
    trace_id comes back via the `x-trace-id` response header, which
    the middleware echoes.
    """
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    project_id = r.json()["project"]["id"]

    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200, r.text

    r = await client.post(f"/api/projects/{project_id}/delivery")
    assert r.status_code == 200, r.text
    delivery_trace_id = r.headers["x-trace-id"]
    return project_id, delivery_trace_id


# ---------- wiring ----------------------------------------------------


@pytest.mark.asyncio
async def test_agent_run_log_captures_all_services(api_env):
    client, maker, *_ = api_env
    await _register(client, "obs_wire_1")
    project_id, _ = await _drive_happy_path(client, "obs-wire-1")

    async with session_scope(maker) as session:
        repo = AgentRunLogRepository(session)
        rows = await repo.list_since(limit=500)

    # Every request should log; we expect at least requirement + planning + delivery.
    agents = {r.agent for r in rows}
    assert {"requirement", "planning", "delivery"}.issubset(agents), (
        f"agent_run_logs missing agents: {agents}"
    )
    # Every row's trace_id should be a 32-char hex id (populated by middleware).
    for r in rows:
        if r.agent in {"requirement", "planning", "delivery"}:
            assert r.trace_id and len(r.trace_id) == 32, (
                f"{r.agent} row missing trace_id: {r.trace_id}"
            )
            assert r.project_id == project_id, (
                f"{r.agent} row should carry the project_id"
            )


# ---------- /observability/health -------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint_summarizes_agents(api_env):
    client, _, *_ = api_env
    await _register(client, "obs_health_1")
    await _drive_happy_path(client, "obs-health-1")

    r = await client.get("/api/observability/health?window_minutes=60")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["window_minutes"] == 60
    assert "totals" in body and "agents" in body
    totals = body["totals"]
    assert totals["count"] >= 3  # at least requirement + planning + delivery
    # Latency histogram keys exist and are ints.
    assert set(totals["latency_ms"]) == {"p50", "p95", "max"}
    assert all(isinstance(v, int) for v in totals["latency_ms"].values())
    # Agent breakdown contains the three headline agents.
    assert {"requirement", "planning", "delivery"}.issubset(body["agents"].keys())
    for name in ("requirement", "planning", "delivery"):
        sub = body["agents"][name]
        assert sub["count"] >= 1
        assert sub["outcomes"], f"{name} has no outcome buckets"


@pytest.mark.asyncio
async def test_health_requires_auth(api_env):
    client, *_ = api_env
    r = await client.get("/api/observability/health")
    assert r.status_code == 401, r.text


# ---------- /observability/agents -------------------------------------


@pytest.mark.asyncio
async def test_agents_endpoint_filters_by_agent(api_env):
    client, _, *_ = api_env
    await _register(client, "obs_agents_1")
    await _drive_happy_path(client, "obs-agents-1")

    # No filter: mixed result.
    r = await client.get("/api/observability/agents?limit=50")
    assert r.status_code == 200, r.text
    mixed = r.json()
    agents = {row["agent"] for row in mixed["runs"]}
    assert {"requirement", "planning", "delivery"}.issubset(agents)

    # Filter: planning only.
    r = await client.get("/api/observability/agents?agent=planning&limit=50")
    assert r.status_code == 200, r.text
    filtered = r.json()
    assert filtered["agent"] == "planning"
    assert filtered["runs"], "expected planning rows"
    assert all(row["agent"] == "planning" for row in filtered["runs"])


# ---------- /observability/trace/{trace_id} ---------------------------


@pytest.mark.asyncio
async def test_trace_endpoint_returns_runs_and_events(api_env):
    client, maker, *_ = api_env
    await _register(client, "obs_trace_1")
    project_id, delivery_trace_id = await _drive_happy_path(client, "obs-trace-1")

    r = await client.get(f"/api/observability/trace/{delivery_trace_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trace_id"] == delivery_trace_id

    # The delivery POST's trace_id should hit the delivery agent run log
    # (the other agents ran during earlier requests with different trace_ids).
    run_agents = {run["agent"] for run in body["runs"]}
    assert "delivery" in run_agents, (
        f"expected delivery run for trace; got {run_agents}"
    )

    # Cross-check with the DB: every returned run has the requested trace_id.
    async with session_scope(maker) as session:
        events = await EventRepository(session).list_for_trace(delivery_trace_id)
    event_names = {e.name for e in events}
    # delivery.generated should be in there (the trace_id middleware binds
    # the trace before the service emits).
    assert "delivery.generated" in event_names, (
        f"expected delivery.generated event; got {event_names}"
    )
    assert {e["name"] for e in body["events"]} == event_names
    # Sanity: all rows reference the right project.
    for run in body["runs"]:
        if run["agent"] == "delivery":
            assert run["project_id"] == project_id
