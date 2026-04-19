"""DriftService + API integration tests — vision.md §5.8.

Covers:
  * DriftService.check_project produces drift-alert messages in each
    affected user's personal stream, with kind=drift-alert and a
    JSON-encoded body round-trippable to the DriftItem shape.
  * low-severity items are NOT fanned out as cards (the service filters).
  * has_drift=false → no alerts posted.
  * recent_for_project returns the last N alerts with decoded bodies.
  * POST endpoint requires membership; non-members get 403.
  * GET endpoint requires membership; non-members get 403.
  * Rate-limit: second check inside the 60s window returns 429.

Uses a custom stub DriftAgent installed on app.state.drift_service so no
LLM is called.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from workgraph_agents.drift import (
    DriftCheckOutcome,
    DriftCheckResult,
    DriftItem,
)
from workgraph_agents.llm import LLMResult
from workgraph_api.main import app
from workgraph_api.services import DriftService
from workgraph_persistence import (
    MessageRow,
    StreamRow,
    backfill_streams_from_projects,
    session_scope,
)


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


# ---------------------------------------------------------------------------
# Scriptable drift-agent stub.
# ---------------------------------------------------------------------------


class _ScriptedDriftAgent:
    """Returns a scripted DriftCheckResult per call.

    Tests populate the queue with the results they want; extra calls
    raise so bugs that accidentally re-trigger the check are caught.
    """

    prompt_version = "stub.drift.scripted.v1"

    def __init__(self) -> None:
        self.queue: list[DriftCheckResult] = []
        self.calls: list[dict] = []

    async def check(self, context):
        self.calls.append(context)
        if not self.queue:
            raise AssertionError("scripted drift agent: queue exhausted")
        result_payload = self.queue.pop(0)
        return DriftCheckOutcome(
            result_payload=result_payload,
            result=LLMResult(
                content="",
                model="stub",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
            ),
            outcome="ok",
            attempts=1,
        )


def _install_drift_stub(api_env_tuple) -> _ScriptedDriftAgent:
    """Replace app.state.drift_service with one backed by the scripted stub."""
    _client, maker, bus, *_ = api_env_tuple
    stub = _ScriptedDriftAgent()
    service = DriftService(
        maker, bus, stub, app.state.stream_service, rate_limit_seconds=60
    )
    app.state.drift_service = service
    app.state.drift_agent = stub
    return stub


def _alt_client() -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Helpers — same shape as other test modules.
# ---------------------------------------------------------------------------


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


async def _me_id(client: AsyncClient) -> str:
    r = await client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# happy path — medium-severity drift → alerts posted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_project_posts_drift_alert_to_affected_users(api_env):
    client, maker, *_ = api_env
    stub = _install_drift_stub(api_env)

    await _register(client, "maya_d1")
    project_id = await _intake(client, "drift-e1")
    maya_id = await _me_id(client)
    await backfill_streams_from_projects(maker)

    stub.queue.append(
        DriftCheckResult(
            has_drift=True,
            drift_items=[
                DriftItem(
                    headline="Memento revive weakens committed permadeath",
                    severity="medium",
                    what_drifted="T-7 adds per-run revive tokens.",
                    vs_thesis_or_decision="D-12 committed to keeping permadeath.",
                    suggested_next_step="Raise with Maya this week.",
                    affected_user_ids=[maya_id],
                )
            ],
            reasoning="Active task contradicts decision.",
        )
    )

    r = await client.post(f"/api/projects/{project_id}/drift/check")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["alerts_posted"] == 1
    assert body["has_drift"] is True
    assert body["drift_items"][0]["severity"] == "medium"

    # The alert must be in Maya's personal stream as a drift-alert message.
    async with session_scope(maker) as session:
        stream = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == maya_id,
                )
            )
        ).scalar_one()
        rows = list(
            (
                await session.execute(
                    select(MessageRow)
                    .where(MessageRow.stream_id == stream.id)
                    .where(MessageRow.kind == "drift-alert")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].linked_id == project_id
    # Body is JSON-encoded drift item.
    import json as _json
    decoded = _json.loads(rows[0].body)
    assert decoded["severity"] == "medium"
    assert decoded["project_id"] == project_id
    assert "memento" in decoded["headline"].lower() or "permadeath" in decoded["headline"].lower()


# ---------------------------------------------------------------------------
# low-severity items are suppressed (no in-stream card)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_low_severity_items_not_fanned_out(api_env):
    client, maker, *_ = api_env
    stub = _install_drift_stub(api_env)

    await _register(client, "maya_d2")
    project_id = await _intake(client, "drift-e2")
    maya_id = await _me_id(client)
    await backfill_streams_from_projects(maker)

    stub.queue.append(
        DriftCheckResult(
            has_drift=True,
            drift_items=[
                DriftItem(
                    headline="Minor style wobble",
                    severity="low",
                    what_drifted="Small divergence in task naming.",
                    vs_thesis_or_decision="Loose vs thesis fragment.",
                    suggested_next_step="Note it; no action now.",
                    affected_user_ids=[maya_id],
                )
            ],
            reasoning="low-severity observation",
        )
    )

    r = await client.post(f"/api/projects/{project_id}/drift/check")
    assert r.status_code == 200, r.text
    body = r.json()
    # Logged but suppressed — 0 alerts even though has_drift=true.
    assert body["alerts_posted"] == 0
    assert body["has_drift"] is True

    async with session_scope(maker) as session:
        rows = list(
            (
                await session.execute(
                    select(MessageRow).where(MessageRow.kind == "drift-alert")
                )
            )
            .scalars()
            .all()
        )
    assert rows == []


# ---------------------------------------------------------------------------
# clean — no drift → no alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_drift_posts_zero_alerts(api_env):
    client, maker, *_ = api_env
    stub = _install_drift_stub(api_env)

    await _register(client, "maya_d3")
    project_id = await _intake(client, "drift-e3")
    await backfill_streams_from_projects(maker)

    stub.queue.append(
        DriftCheckResult(
            has_drift=False, drift_items=[], reasoning="clean"
        )
    )

    r = await client.post(f"/api/projects/{project_id}/drift/check")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["alerts_posted"] == 0
    assert body["has_drift"] is False

    async with session_scope(maker) as session:
        rows = list(
            (
                await session.execute(
                    select(MessageRow).where(MessageRow.kind == "drift-alert")
                )
            )
            .scalars()
            .all()
        )
    assert rows == []


# ---------------------------------------------------------------------------
# recent endpoint — latest N decoded alerts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_endpoint_returns_decoded_alerts(api_env):
    client, maker, *_ = api_env
    stub = _install_drift_stub(api_env)

    await _register(client, "maya_d4")
    project_id = await _intake(client, "drift-e4")
    maya_id = await _me_id(client)
    await backfill_streams_from_projects(maker)

    stub.queue.append(
        DriftCheckResult(
            has_drift=True,
            drift_items=[
                DriftItem(
                    headline="Test alert",
                    severity="high",
                    what_drifted="diverged",
                    vs_thesis_or_decision="thesis X",
                    suggested_next_step="next step",
                    affected_user_ids=[maya_id],
                )
            ],
            reasoning="test",
        )
    )
    r = await client.post(f"/api/projects/{project_id}/drift/check")
    assert r.status_code == 200

    r = await client.get(f"/api/projects/{project_id}/drift/recent")
    assert r.status_code == 200
    body = r.json()
    assert "alerts" in body
    assert len(body["alerts"]) == 1
    alert = body["alerts"][0]
    assert alert["recipient_user_id"] == maya_id
    assert alert["drift_item"]["severity"] == "high"
    assert alert["drift_item"]["headline"] == "Test alert"


# ---------------------------------------------------------------------------
# membership guard — non-member gets 403 on both endpoints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_member_cannot_trigger_drift_check(api_env):
    client, _, *_ = api_env
    _install_drift_stub(api_env)

    await _register(client, "maya_d5")
    project_id = await _intake(client, "drift-e5")

    async with _alt_client() as outsider:
        await _register(outsider, "stranger_d5")
        r = await outsider.post(f"/api/projects/{project_id}/drift/check")
        assert r.status_code == 403
        r = await outsider.get(f"/api/projects/{project_id}/drift/recent")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# rate-limit — second check inside the lockout window → 429
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limited_within_lockout_window(api_env):
    client, maker, bus, *_ = api_env
    stub = _ScriptedDriftAgent()
    # Keep the default 60s lockout — two checks in quick succession.
    service = DriftService(
        maker, bus, stub, app.state.stream_service, rate_limit_seconds=60
    )
    app.state.drift_service = service
    app.state.drift_agent = stub

    await _register(client, "maya_d6")
    project_id = await _intake(client, "drift-e6")
    await backfill_streams_from_projects(maker)

    stub.queue.append(
        DriftCheckResult(has_drift=False, drift_items=[], reasoning="clean")
    )

    r1 = await client.post(f"/api/projects/{project_id}/drift/check")
    assert r1.status_code == 200, r1.text

    # Second call within the window → 429 with retry_after_s hint.
    r2 = await client.post(f"/api/projects/{project_id}/drift/check")
    assert r2.status_code == 429, r2.text
    body = r2.json()
    assert body.get("detail") == "rate_limited"
    assert body.get("retry_after_s", 0) > 0
    # Agent should only have been called once despite two POSTs.
    assert len(stub.calls) == 1


# ---------------------------------------------------------------------------
# ignores affected_user_ids that aren't project members
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_naming_outsider_user_ids_is_ignored(api_env):
    client, maker, *_ = api_env
    stub = _install_drift_stub(api_env)

    await _register(client, "maya_d7")
    project_id = await _intake(client, "drift-e7")
    await backfill_streams_from_projects(maker)

    stub.queue.append(
        DriftCheckResult(
            has_drift=True,
            drift_items=[
                DriftItem(
                    headline="Drift with non-member reference",
                    severity="high",
                    what_drifted="x",
                    vs_thesis_or_decision="y",
                    suggested_next_step="z",
                    affected_user_ids=["u-not-a-member", "u-also-bogus"],
                )
            ],
            reasoning="tests id filtering",
        )
    )

    r = await client.post(f"/api/projects/{project_id}/drift/check")
    assert r.status_code == 200, r.text
    body = r.json()
    # The agent flagged drift but every listed id is outside the member
    # pool — service filters them out and posts zero alerts. Refusing to
    # broadcast is the designed behavior.
    assert body["alerts_posted"] == 0
