"""Pickup #6 — IM messages can be posted into a specific stream (room).

Covers MessageService.post + IMService.post_message extensions:
  * stream_id=None → legacy behavior (project's team-room stream)
  * stream_id=<room>  + author is a stream member → message lands in
    that room and the room's stream_id flows into B3's
    DecisionRow.scope_stream_id when crystallization fires
  * stream_id=<room>  + author is NOT a stream member → 403
  * stream_id=<other-project's stream> → 403 wrong_project
  * stream_id=<bogus> → 403 stream_not_found
"""
from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from workgraph_agents.im_assist import IMProposal, IMSuggestion
from workgraph_api.main import app
from workgraph_persistence import (
    DecisionRow,
    IMSuggestionRow,
    MessageRow,
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


async def _login(client: AsyncClient, username: str) -> None:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


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


async def _invite(client: AsyncClient, project_id: str, username: str) -> None:
    r = await client.post(
        f"/api/projects/{project_id}/invite",
        json={"username": username},
    )
    assert r.status_code == 200, r.text


async def _create_room(
    client: AsyncClient,
    project_id: str,
    *,
    name: str,
    member_user_ids: list[str],
) -> dict[str, Any]:
    r = await client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": name, "member_user_ids": member_user_ids},
    )
    assert r.status_code == 200, r.text
    return r.json()["stream"]


# ---------------------------------------------------------------------------
# happy paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_to_team_room_when_no_stream_id(api_env):
    """Default (no stream_id in body) → message lands in team-room stream."""
    client, maker, *_ = api_env
    await _register(client, "rm_im_a")
    pid = await _intake(client, "im-stream-a")

    r = await client.post(
        f"/api/projects/{pid}/messages",
        json={"body": "hello team room"},
    )
    assert r.status_code == 200, r.text
    msg_id = r.json()["id"]

    async with session_scope(maker) as session:
        msg = (
            await session.execute(
                select(MessageRow).where(MessageRow.id == msg_id)
            )
        ).scalar_one()
        team_room = await StreamRepository(session).get_for_project(pid)
    assert team_room is not None
    assert msg.stream_id == team_room.id


@pytest.mark.asyncio
async def test_post_to_room_lands_in_room_stream(api_env):
    """stream_id=<room> + author is room member → message scope-stamps room."""
    client, maker, *_ = api_env
    await _register(client, "rm_im_b")
    pid = await _intake(client, "im-stream-b")

    # Create a room with the creator as the only member.
    me_b = await _alt_login_get_me("rm_im_b")
    room = await _create_room(
        client, pid, name="dev-sync", member_user_ids=[me_b]
    )
    room_id = room["id"]

    r = await client.post(
        f"/api/projects/{pid}/messages",
        json={"body": "room-scoped message", "stream_id": room_id},
    )
    assert r.status_code == 200, r.text
    msg_id = r.json()["id"]
    assert r.json()["stream_id"] == room_id

    async with session_scope(maker) as session:
        msg = (
            await session.execute(
                select(MessageRow).where(MessageRow.id == msg_id)
            )
        ).scalar_one()
    assert msg.stream_id == room_id


# ---------------------------------------------------------------------------
# rejection paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_to_room_rejects_non_member(api_env):
    """A project member who isn't in the room cannot post there (403)."""
    client, _, *_ = api_env
    await _register(client, "rm_owner")
    pid = await _intake(client, "im-stream-c")
    await _register(client, "rm_outsider")

    # Owner creates the room with only themselves in it.
    await _login(client, "rm_owner")
    me_owner = await _alt_login_get_me("rm_owner")
    room = await _create_room(
        client, pid, name="owners-only", member_user_ids=[me_owner]
    )
    room_id = room["id"]

    # Invite the outsider to the project but NOT the room.
    await _invite(client, pid, "rm_outsider")

    # Outsider tries to post — must get 403.
    await _login(client, "rm_outsider")
    r = await client.post(
        f"/api/projects/{pid}/messages",
        json={"body": "trespass", "stream_id": room_id},
    )
    assert r.status_code == 403, r.text
    assert "not_a_stream_member" in r.json()["message"]


@pytest.mark.asyncio
async def test_post_rejects_unknown_stream_id(api_env):
    """Bogus stream_id → 403 stream_not_found."""
    client, *_ = api_env
    await _register(client, "rm_d")
    pid = await _intake(client, "im-stream-d")
    r = await client.post(
        f"/api/projects/{pid}/messages",
        json={"body": "ghost", "stream_id": "00000000-0000-0000-0000-deadbeefface"},
    )
    assert r.status_code == 403, r.text
    assert "stream_not_found" in r.json()["message"]


@pytest.mark.asyncio
async def test_post_rejects_cross_project_stream(api_env):
    """A stream from project A cannot receive messages routed via project B.

    Both projects are owned by the same caller — so the project-
    membership gate on /messages passes for project B; the error that
    fires is specifically the wrong_project guard inside MessageService.
    """
    client, _, *_ = api_env
    await _register(client, "rm_x_owner")
    pid_a = await _intake(client, "im-stream-x-a")
    me = await _alt_login_get_me("rm_x_owner")
    room_a = await _create_room(
        client, pid_a, name="proj-a-room", member_user_ids=[me]
    )

    pid_b = await _intake(client, "im-stream-x-b")

    # Both projects belong to the same caller (the canonical intake
    # path makes the requester the project owner). So the
    # project-membership gate on /api/projects/{pid_b}/messages passes
    # — the only thing that should reject is the new wrong_project
    # check inside MessageService.post.
    r = await client.post(
        f"/api/projects/{pid_b}/messages",
        json={"body": "wrong project", "stream_id": room_a["id"]},
    )
    assert r.status_code == 403, r.text
    assert "wrong_project" in r.json()["message"]


# ---------------------------------------------------------------------------
# B3 sequel — decision crystallization stamps the right room
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b3_crystallize_stamps_room_stream_when_posted_in_room(api_env):
    """The point of pickup #6: when a high-confidence decision-kind
    suggestion is accepted on a message that was posted IN A ROOM,
    the resulting DecisionRow.scope_stream_id is THAT ROOM'S id, not
    the project's team-room.
    """
    client, maker, *_ = api_env
    im_agent = app.state.im_agent

    await _register(client, "rm_b3_owner")
    pid = await _intake(client, "im-stream-b3")
    me = await _alt_login_get_me("rm_b3_owner")

    # Pre-fetch a deliverable id so the stub im_agent can target a real one.
    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]

    im_agent._suggestion = IMSuggestion(
        kind="decision",
        confidence=0.85,
        targets=[],
        proposal=IMProposal(
            action="drop_deliverable",
            summary="room-scoped scope cut",
            detail={"deliverable_id": deliverable_id},
        ),
        reasoning="pickup #6 b3 sequel test",
    )

    try:
        # Create a room and post the decision-flavored message into it.
        room = await _create_room(
            client, pid, name="design-decisions", member_user_ids=[me]
        )
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

        # Find the suggestion the agent created.
        async with session_scope(maker) as session:
            sug_row = (
                await session.execute(
                    select(IMSuggestionRow).where(
                        IMSuggestionRow.project_id == pid
                    )
                )
            ).scalar_one()
            suggestion_id = sug_row.id

        # Accept it — crystallization should fire and scope_stream_id
        # should equal the ROOM stream, not the team-room.
        r = await client.post(
            f"/api/im_suggestions/{suggestion_id}/accept"
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["decision"] is not None

        async with session_scope(maker) as session:
            decision = (
                await session.execute(
                    select(DecisionRow).where(
                        DecisionRow.id == body["decision"]["id"]
                    )
                )
            ).scalar_one()
            team_room = await StreamRepository(session).get_for_project(pid)

        assert decision.scope_stream_id == room_id, (
            f"expected room stream {room_id}; got {decision.scope_stream_id}"
        )
        assert team_room is not None
        assert decision.scope_stream_id != team_room.id
    finally:
        im_agent._suggestion = None
