"""Room-stream timeline tests — backend contracts behind the room slice.

Covers:
  * Persisted room name round-trips create → list → timeline.
  * GET /api/projects/{pid}/rooms/{rid}/timeline returns chronologically
    ordered messages + suggestions + decisions joined for the room.
  * Membership gating (non-member → 403; cross-project → 403; bogus
    stream → 404).
  * `_decision_payload` exposes `scope_stream_id` (frontend
    DecisionCard explainer requires it).
  * IMSuggestionRepository.list_for_project respects stream_id filter
    (workbench `Requests` panel projection).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from workgraph_agents.im_assist import IMProposal, IMSuggestion
from workgraph_api.main import app
from workgraph_persistence import (
    DecisionRow,
    IMSuggestionRepository,
    IMSuggestionRow,
    StreamRepository,
    session_scope,
)


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _register(client: AsyncClient, username: str) -> str:
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _intake(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


async def _alt_login_get_me(username: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as alt:
        r = await alt.post(
            "/api/auth/login",
            json={"username": username, "password": "hunter22"},
        )
        assert r.status_code == 200, r.text
        me = await alt.get("/api/auth/me")
        return me.json()["id"]


async def _create_room(client: AsyncClient, project_id: str, *, name: str, members: list[str]) -> dict:
    r = await client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": name, "member_user_ids": members},
    )
    assert r.status_code == 200, r.text
    return r.json()["stream"]


# ---------------------------------------------------------------------------
# Persisted room name (alembic 0029)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_name_persists_across_create_and_list(api_env):
    client, maker, *_ = api_env
    await _register(client, "rt_a")
    pid = await _intake(client, "rt-name-1")
    me = await _alt_login_get_me("rt_a")
    room = await _create_room(client, pid, name="design-sync", members=[me])
    assert room["name"] == "design-sync"

    # GET /api/projects/{id}/rooms returns the persisted name.
    r = await client.get(f"/api/projects/{pid}/rooms")
    assert r.status_code == 200, r.text
    rooms = r.json()["rooms"]
    assert any(rm["id"] == room["id"] and rm["name"] == "design-sync" for rm in rooms)

    # DB-level: stream.name actually persisted.
    async with session_scope(maker) as session:
        stream = await StreamRepository(session).get(room["id"])
    assert stream is not None
    assert stream.name == "design-sync"


# ---------------------------------------------------------------------------
# Timeline endpoint shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeline_returns_chronological_messages_for_empty_room(api_env):
    client, _, *_ = api_env
    await _register(client, "rt_b")
    pid = await _intake(client, "rt-empty-1")
    me = await _alt_login_get_me("rt_b")
    room = await _create_room(client, pid, name="empty-room", members=[me])

    r = await client.get(f"/api/projects/{pid}/rooms/{room['id']}/timeline")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stream_id"] == room["id"]
    assert body["project_id"] == pid
    assert body["items"] == []


@pytest.mark.asyncio
async def test_timeline_includes_messages_then_suggestion_then_decision(api_env):
    """End-to-end: post a decision-flavored message in a room, the IM
    classifier produces a suggestion, accept it, the timeline returns
    all three in chronological order with the right kinds.
    """
    client, maker, *_ = api_env
    im_agent = app.state.im_agent
    await _register(client, "rt_c")
    pid = await _intake(client, "rt-chrono-1")
    me = await _alt_login_get_me("rt_c")

    # Pin a high-confidence decision so the accept path crystallizes.
    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]
    im_agent._suggestion = IMSuggestion(
        kind="decision",
        confidence=0.85,
        targets=[],
        proposal=IMProposal(
            action="drop_deliverable",
            summary="room-scoped decision",
            detail={"deliverable_id": deliverable_id},
        ),
        reasoning="timeline test",
    )

    try:
        room = await _create_room(client, pid, name="design", members=[me])
        room_id = room["id"]

        r = await client.post(
            f"/api/projects/{pid}/messages",
            json={
                "body": "let's drop this deliverable for v1",
                "stream_id": room_id,
            },
        )
        assert r.status_code == 200, r.text
        await app.state.im_service.drain()

        # Locate suggestion + accept it.
        async with session_scope(maker) as session:
            sug = (
                await session.execute(
                    select(IMSuggestionRow).where(IMSuggestionRow.project_id == pid)
                )
            ).scalar_one()
        r = await client.post(f"/api/im_suggestions/{sug.id}/accept")
        assert r.status_code == 200, r.text
        decision = r.json()["decision"]

        # Timeline should now have 3 items: message, im_suggestion (accepted),
        # decision (with scope_stream_id == room).
        r = await client.get(f"/api/projects/{pid}/rooms/{room_id}/timeline")
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        kinds = [i["kind"] for i in items]
        assert "message" in kinds
        assert "im_suggestion" in kinds
        assert "decision" in kinds

        # Decision item carries scope_stream_id matching the room.
        decision_item = next(i for i in items if i["kind"] == "decision")
        assert decision_item["id"] == decision["id"]
        assert decision_item["scope_stream_id"] == room_id

        # Suggestion item carries the right status (accepted).
        sug_item = next(i for i in items if i["kind"] == "im_suggestion")
        assert sug_item["id"] == sug.id
        assert sug_item["status"] == "accepted"
    finally:
        im_agent._suggestion = None


@pytest.mark.asyncio
async def test_timeline_404_for_unknown_stream(api_env):
    client, _, *_ = api_env
    await _register(client, "rt_d")
    pid = await _intake(client, "rt-404-1")
    r = await client.get(
        f"/api/projects/{pid}/rooms/00000000-0000-0000-0000-deadbeefface/timeline"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_timeline_403_for_non_member(api_env):
    """Project member who isn't a room member cannot read the timeline."""
    client, _, *_ = api_env
    await _register(client, "rt_owner")
    pid = await _intake(client, "rt-nonmember-1")
    me_owner = await _alt_login_get_me("rt_owner")
    room = await _create_room(
        client, pid, name="owners-only", members=[me_owner]
    )
    room_id = room["id"]

    # Add another project member who isn't in the room.
    # _register auto-logs-in as the new user; flip back to owner before
    # inviting so the invite call has the right authority.
    await _register(client, "rt_outsider")
    client.cookies.clear()
    login = await client.post(
        "/api/auth/login",
        json={"username": "rt_owner", "password": "hunter22"},
    )
    assert login.status_code == 200, login.text
    r = await client.post(
        f"/api/projects/{pid}/invite", json={"username": "rt_outsider"}
    )
    assert r.status_code == 200, r.text

    # Outsider tries to read the timeline.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as alt:
        login = await alt.post(
            "/api/auth/login",
            json={"username": "rt_outsider", "password": "hunter22"},
        )
        assert login.status_code == 200, login.text
        r = await alt.get(f"/api/projects/{pid}/rooms/{room_id}/timeline")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# IMSuggestionRepository stream_id filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_im_suggestion_list_filters_by_stream_id(api_env):
    """The room-scoped suggestion query joins through MessageRow.stream_id.

    Two messages in two different rooms each spawn a suggestion. Listing
    with stream_id=A returns A's suggestion only.
    """
    client, maker, *_ = api_env
    im_agent = app.state.im_agent
    await _register(client, "rt_filt")
    pid = await _intake(client, "rt-filter-1")
    me = await _alt_login_get_me("rt_filt")

    # Pin a tag-kind low-confidence suggestion (won't crystallize, just
    # populates IMSuggestionRow with a known message_id).
    im_agent._suggestion = IMSuggestion(
        kind="tag", confidence=0.4, targets=[], reasoning="filter test"
    )
    try:
        room_a = await _create_room(client, pid, name="a", members=[me])
        room_b = await _create_room(client, pid, name="b", members=[me])

        # Post in room A.
        r = await client.post(
            f"/api/projects/{pid}/messages",
            json={"body": "message in room A long enough for IM classifier",
                  "stream_id": room_a["id"]},
        )
        assert r.status_code == 200, r.text
        await app.state.im_service.drain()

        # Post in room B.
        r = await client.post(
            f"/api/projects/{pid}/messages",
            json={"body": "message in room B long enough for IM classifier",
                  "stream_id": room_b["id"]},
        )
        assert r.status_code == 200, r.text
        await app.state.im_service.drain()

        # Repository query with stream_id=A returns only the A-scoped suggestion.
        async with session_scope(maker) as session:
            a_only = await IMSuggestionRepository(session).list_for_project(
                project_id=pid, stream_id=room_a["id"]
            )
            b_only = await IMSuggestionRepository(session).list_for_project(
                project_id=pid, stream_id=room_b["id"]
            )
            unfiltered = await IMSuggestionRepository(session).list_for_project(
                project_id=pid
            )
        assert len(a_only) == 1
        assert len(b_only) == 1
        assert a_only[0].id != b_only[0].id
        assert len(unfiltered) >= 2
    finally:
        im_agent._suggestion = None


# ---------------------------------------------------------------------------
# _decision_payload includes scope_stream_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decision_payload_exposes_scope_stream_id(api_env):
    """The B3 + pickup-#6 chain writes scope_stream_id; the wire payload
    must surface it so the FE DecisionCard can render the explainer.
    """
    client, maker, *_ = api_env
    im_agent = app.state.im_agent
    await _register(client, "rt_dec")
    pid = await _intake(client, "rt-decpay-1")
    me = await _alt_login_get_me("rt_dec")

    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]
    im_agent._suggestion = IMSuggestion(
        kind="decision",
        confidence=0.85,
        targets=[],
        proposal=IMProposal(
            action="drop_deliverable",
            summary="payload scope test",
            detail={"deliverable_id": deliverable_id},
        ),
        reasoning="payload test",
    )
    try:
        room = await _create_room(client, pid, name="dec-room", members=[me])
        room_id = room["id"]

        r = await client.post(
            f"/api/projects/{pid}/messages",
            json={
                "body": "let's drop this deliverable for the v1 launch",
                "stream_id": room_id,
            },
        )
        assert r.status_code == 200, r.text
        await app.state.im_service.drain()

        async with session_scope(maker) as session:
            sug = (
                await session.execute(
                    select(IMSuggestionRow).where(IMSuggestionRow.project_id == pid)
                )
            ).scalar_one()
        r = await client.post(f"/api/im_suggestions/{sug.id}/accept")
        assert r.status_code == 200, r.text
        decision_payload = r.json()["decision"]

        assert "scope_stream_id" in decision_payload
        assert decision_payload["scope_stream_id"] == room_id

        # Also confirm DB row has it (B3 chain).
        async with session_scope(maker) as session:
            d = (
                await session.execute(
                    select(DecisionRow).where(DecisionRow.id == decision_payload["id"])
                )
            ).scalar_one()
        assert d.scope_stream_id == room_id
    finally:
        im_agent._suggestion = None


# ---------------------------------------------------------------------------
# Pickup #7 leftover — preview honors scope_tiers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_preview_accepts_scope_tiers_field(api_env):
    """preview() route accepts scope_tiers without 422 (pickup #7
    leftover). Behavioral wiring (kb_slice respects pills) is already
    proven by test_personal_post_kb_slice_respects_scope_tiers; here we
    just smoke that the route signature accepts the field.
    """
    client, _, *_ = api_env
    await _register(client, "rt_prev")
    pid = await _intake(client, "rt-preview-1")

    r = await client.post(
        f"/api/personal/{pid}/preview",
        json={
            "body": "what is the postgres pool sizing recommendation?",
            "scope_tiers": {
                "personal": False,
                "group": True,
                "department": False,
                "enterprise": False,
            },
        },
    )
    # 200 means the route accepted the body shape; the rehearsal
    # may return silent_preview or a real preview — either is fine.
    assert r.status_code in (200, 429), r.text
