"""Signal-chain tests (vision §6).

Covers the extensions to IMService made for the canonical signal chain:

  * counter — original flips 'countered'; new message persists; new
    suggestion.counter_of_id points back; rejecting on already-resolved.
  * escalate — status→escalated, escalation_state='requested'.
  * accept crystallizes a DecisionRow when kind=='decision' and
    confidence>=0.6. Below threshold, or wrong kind → no DecisionRow
    (but the existing graph mutation still runs).

All paths go through the HTTP surface with a real session cookie so the
auth + membership guards are exercised alongside the service logic.
Stubs: `StubIMAssistAgent` + friends via `api_env` conftest — no DeepSeek.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from workgraph_agents.im_assist import IMProposal, IMSuggestion
from workgraph_api.main import app
from workgraph_persistence import (
    DecisionRow,
    IMSuggestionRow,
    StreamRepository,
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


async def _login(client: AsyncClient, username: str, password: str = "hunter22"):
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text


async def _intake_canonical(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


async def _invite(client: AsyncClient, project_id: str, username: str) -> None:
    r = await client.post(
        f"/api/projects/{project_id}/invite", json={"username": username}
    )
    assert r.status_code == 200, r.text


async def _post_message_awaited(
    client: AsyncClient, project_id: str, body: str
) -> dict:
    r = await client.post(
        f"/api/projects/{project_id}/messages", json={"body": body}
    )
    assert r.status_code == 200, r.text
    await app.state.im_service.drain()
    messages = (
        await client.get(f"/api/projects/{project_id}/messages")
    ).json()["messages"]
    # newest message last
    return messages[-1]


# ---------- counter ------------------------------------------------------


@pytest.mark.asyncio
async def test_counter_happy_path_flips_status_and_links_new_suggestion(api_env):
    """A posts a decision-like message → suggestion auto-created. B counters
    → original.status=countered, new message + new suggestion exist, new
    suggestion.counter_of_id points at the original.
    """
    client, maker, _, _, _, _ = api_env
    await _register(client, "sc_alice")
    project_id = await _intake_canonical(client, "sc-counter-1")
    await _register(client, "sc_bob")
    await _login(client, "sc_alice")
    await _invite(client, project_id, "sc_bob")

    # Alice posts a decision-kind message. Stub keyword-classifier matches
    # "drop " → kind=decision, confidence=0.8.
    msg = await _post_message_awaited(
        client,
        project_id,
        "we should drop the export feature, it's too much scope for v1",
    )
    suggestion = msg["suggestion"]
    assert suggestion is not None, "stub should have classified a long message"
    assert suggestion["kind"] == "decision"
    original_id = suggestion["id"]

    # Bob counters.
    await _login(client, "sc_bob")
    r = await client.post(
        f"/api/im_suggestions/{original_id}/counter",
        json={"text": "actually export is already 80% done — we should keep it"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["original_suggestion"]["status"] == "countered"
    assert body["original_suggestion"]["id"] == original_id

    new_message = body["new_message"]
    assert new_message["body"].startswith("actually export is already 80%")
    assert new_message["author_username"] == "sc_bob"

    new_suggestion = body["new_suggestion"]
    assert new_suggestion is not None
    assert new_suggestion["counter_of_id"] == original_id
    assert new_suggestion["status"] == "pending"

    # Verify at the DB layer that the link survived the round-trip.
    async with session_scope(maker) as session:
        orig = (
            await session.execute(
                select(IMSuggestionRow).where(IMSuggestionRow.id == original_id)
            )
        ).scalar_one()
        fresh = (
            await session.execute(
                select(IMSuggestionRow).where(
                    IMSuggestionRow.id == new_suggestion["id"]
                )
            )
        ).scalar_one()
    assert orig.status == "countered"
    assert fresh.counter_of_id == original_id


@pytest.mark.asyncio
async def test_counter_on_already_resolved_returns_409(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "sc_owner_cr")
    project_id = await _intake_canonical(client, "sc-counter-2")
    await _register(client, "sc_peer_cr")
    await _login(client, "sc_owner_cr")
    await _invite(client, project_id, "sc_peer_cr")

    msg = await _post_message_awaited(
        client,
        project_id,
        "let's drop the reporting feature entirely for launch day",
    )
    suggestion_id = msg["suggestion"]["id"]
    # Owner accepts first. Stub decision has confidence=0.8 → crystallizes.
    accept = await client.post(f"/api/im_suggestions/{suggestion_id}/accept")
    assert accept.status_code == 200, accept.text

    await _login(client, "sc_peer_cr")
    r = await client.post(
        f"/api/im_suggestions/{suggestion_id}/counter",
        json={"text": "actually we should keep reporting in — here is why"},
    )
    assert r.status_code == 409, r.text


# ---------- escalate -----------------------------------------------------


@pytest.mark.asyncio
async def test_escalate_happy_path_sets_status_and_state(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "sc_owner_esc")
    project_id = await _intake_canonical(client, "sc-escalate-1")

    msg = await _post_message_awaited(
        client,
        project_id,
        "we should drop the export tab before launch tomorrow",
    )
    suggestion_id = msg["suggestion"]["id"]

    r = await client.post(f"/api/im_suggestions/{suggestion_id}/escalate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "escalated"
    assert body["escalation_state"] == "requested"

    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(IMSuggestionRow).where(IMSuggestionRow.id == suggestion_id)
            )
        ).scalar_one()
    assert row.status == "escalated"
    assert row.escalation_state == "requested"


@pytest.mark.asyncio
async def test_escalate_on_already_resolved_returns_409(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "sc_owner_eres")
    project_id = await _intake_canonical(client, "sc-escalate-2")

    msg = await _post_message_awaited(
        client,
        project_id,
        "we should drop the audit log for v1 to cut scope",
    )
    suggestion_id = msg["suggestion"]["id"]
    # Dismiss first.
    dismiss = await client.post(f"/api/im_suggestions/{suggestion_id}/dismiss")
    assert dismiss.status_code == 200

    r = await client.post(f"/api/im_suggestions/{suggestion_id}/escalate")
    assert r.status_code == 409, r.text


# ---------- accept crystallization --------------------------------------


@pytest.mark.asyncio
async def test_accept_decision_high_confidence_creates_decision_row(api_env):
    """kind='decision', confidence>=0.6 → DecisionRow is created with
    source_suggestion_id set + conflict_id=None. Suggestion.decision_id
    populated. apply_outcome reflects whether graph mutation ran.
    """
    client, maker, _, _, _, _ = api_env
    im_agent = app.state.im_agent
    # Pin a high-confidence decision with a real deliverable target so the
    # graph mutation actually runs and apply_outcome == 'ok'.
    im_agent._suggestion = IMSuggestion(
        kind="decision",
        confidence=0.8,
        targets=[],
        proposal=IMProposal(
            action="drop_deliverable",
            summary="High-confidence crystallization",
            detail={"deliverable_id": None},  # filled after fetch below
        ),
        reasoning="deliberate cut for signal-chain test",
    )

    await _register(client, "sc_owner_hc")
    project_id = await _intake_canonical(client, "sc-accept-hc")
    # Grab the project's first deliverable id so the proposal mutation lands.
    state = (await client.get(f"/api/projects/{project_id}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]
    im_agent._suggestion.proposal.detail = {"deliverable_id": deliverable_id}

    msg = await _post_message_awaited(
        client, project_id, "let's drop this deliverable for the v1 launch"
    )
    suggestion_id = msg["suggestion"]["id"]
    assert msg["suggestion"]["kind"] == "decision"
    assert msg["suggestion"]["confidence"] >= 0.6

    accept = await client.post(f"/api/im_suggestions/{suggestion_id}/accept")
    assert accept.status_code == 200, accept.text
    body = accept.json()
    assert body["ok"] is True
    assert body["suggestion"]["status"] == "accepted"
    assert body["decision"] is not None
    assert body["decision"]["source_suggestion_id"] == suggestion_id
    assert body["decision"]["conflict_id"] is None
    # graph touched → apply_outcome=ok (not advisory).
    assert body["decision"]["apply_outcome"] == "ok"
    assert body["suggestion"]["decision_id"] == body["decision"]["id"]

    # DB inspection: DecisionRow exists with the link; suggestion points back.
    async with session_scope(maker) as session:
        decisions = list(
            (
                await session.execute(
                    select(DecisionRow).where(
                        DecisionRow.source_suggestion_id == suggestion_id
                    )
                )
            )
            .scalars()
            .all()
        )
        suggestion_row = (
            await session.execute(
                select(IMSuggestionRow).where(IMSuggestionRow.id == suggestion_id)
            )
        ).scalar_one()
    assert len(decisions) == 1
    assert decisions[0].conflict_id is None
    assert suggestion_row.decision_id == decisions[0].id

    # Restore for other tests that reuse the agent.
    im_agent._suggestion = None


@pytest.mark.asyncio
async def test_accept_decision_low_confidence_skips_decision_row(api_env):
    """kind='decision', confidence<0.6 → NO DecisionRow. Graph mutation still
    runs (same as before the signal-chain feature).
    """
    client, maker, _, _, _, _ = api_env
    im_agent = app.state.im_agent
    await _register(client, "sc_owner_lc")
    project_id = await _intake_canonical(client, "sc-accept-lc")
    state = (await client.get(f"/api/projects/{project_id}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]

    im_agent._suggestion = IMSuggestion(
        kind="decision",
        confidence=0.3,
        targets=[],
        proposal=IMProposal(
            action="drop_deliverable",
            summary="low confidence drop",
            detail={"deliverable_id": deliverable_id},
        ),
        reasoning="not sure but drop",
    )

    msg = await _post_message_awaited(
        client, project_id, "maybe we should drop this deliverable, not sure"
    )
    suggestion_id = msg["suggestion"]["id"]
    assert msg["suggestion"]["confidence"] < 0.6

    accept = await client.post(f"/api/im_suggestions/{suggestion_id}/accept")
    assert accept.status_code == 200, accept.text
    body = accept.json()
    assert body["ok"] is True
    # No crystallization.
    assert body["decision"] is None
    assert body["suggestion"]["decision_id"] is None
    # Graph mutation still ran.
    assert body["applied"]["graph_touched"] is True

    async with session_scope(maker) as session:
        decisions = list(
            (
                await session.execute(
                    select(DecisionRow).where(
                        DecisionRow.source_suggestion_id == suggestion_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert decisions == []

    im_agent._suggestion = None


@pytest.mark.asyncio
async def test_accept_tag_kind_does_not_create_decision_row(api_env):
    """kind='tag' (even at high confidence) → NO DecisionRow."""
    client, maker, _, _, _, _ = api_env
    im_agent = app.state.im_agent
    await _register(client, "sc_owner_tag")
    project_id = await _intake_canonical(client, "sc-accept-tag")

    im_agent._suggestion = IMSuggestion(
        kind="tag",
        confidence=0.95,
        targets=[],
        proposal=None,
        reasoning="tag-like observation",
    )

    msg = await _post_message_awaited(
        client, project_id, "this observation should be tagged to tracking"
    )
    suggestion_id = msg["suggestion"]["id"]
    assert msg["suggestion"]["kind"] == "tag"

    accept = await client.post(f"/api/im_suggestions/{suggestion_id}/accept")
    assert accept.status_code == 200, accept.text
    body = accept.json()
    assert body["decision"] is None
    assert body["suggestion"]["decision_id"] is None

    async with session_scope(maker) as session:
        decisions = list(
            (
                await session.execute(
                    select(DecisionRow).where(
                        DecisionRow.source_suggestion_id == suggestion_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert decisions == []

    im_agent._suggestion = None


# ---------- B3: scope_stream_id stamping --------------------------------


@pytest.mark.asyncio
async def test_accept_decision_stamps_scope_stream_id_from_source_message(api_env):
    """N-Next §6.11 + Correction R.2: a crystallized DecisionRow inherits
    `scope_stream_id` from the source message's stream. IM messages today
    land in the project's team-room stream, so the stamp equals that
    stream's id — proving the smallest-relevant-vote rule has its scope
    column populated end-to-end (column → repo → service call site).
    """
    client, maker, _, _, _, _ = api_env
    im_agent = app.state.im_agent
    im_agent._suggestion = IMSuggestion(
        kind="decision",
        confidence=0.8,
        targets=[],
        proposal=IMProposal(
            action="drop_deliverable",
            summary="Stamp the scope stream",
            detail={"deliverable_id": None},  # filled after fetch below
        ),
        reasoning="B3 wiring regression",
    )

    await _register(client, "sc_owner_b3")
    project_id = await _intake_canonical(client, "sc-accept-b3-stamp")
    state = (await client.get(f"/api/projects/{project_id}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]
    im_agent._suggestion.proposal.detail = {"deliverable_id": deliverable_id}

    msg = await _post_message_awaited(
        client, project_id, "we should drop this deliverable for the v1 launch"
    )
    suggestion_id = msg["suggestion"]["id"]

    accept = await client.post(f"/api/im_suggestions/{suggestion_id}/accept")
    assert accept.status_code == 200, accept.text

    async with session_scope(maker) as session:
        team_stream = await StreamRepository(session).get_for_project(project_id)
        decision = (
            await session.execute(
                select(DecisionRow).where(
                    DecisionRow.source_suggestion_id == suggestion_id
                )
            )
        ).scalar_one()
    assert team_stream is not None
    assert decision.scope_stream_id == team_stream.id

    im_agent._suggestion = None
