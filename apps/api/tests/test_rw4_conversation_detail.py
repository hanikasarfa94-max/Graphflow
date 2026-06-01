"""RW-4 — Conversation detail endpoint tests.

Exercises GET /api/conversations/:id end-to-end against the live
StreamService. Covers:

  * direct (DM) shape: type='direct', participants both members,
    scope_id=null, real messages from the wire
  * room shape: type='room', scope_id=project_id, participants
    contain all stream members with display names
  * 403 on non-member viewer
  * 404 on unknown stream id
  * messages array uses the BE wire field names (created_at, body,
    author_id, author_username) so the FE consumes them unchanged
"""
from __future__ import annotations

import uuid

import pytest

from workgraph_persistence import (
    ProjectMemberRepository,
    ProjectRow,
    StreamMemberRepository,
    StreamRepository,
    session_scope,
)


async def _register_and_login(client, username: str) -> str:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _login(client, username: str) -> None:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


async def _mk_project_with_members(maker, *, owner_id: str, member_id: str):
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="RW4 Project"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
    return pid


async def _mk_room(maker, *, project_id: str, members: list[str]) -> str:
    """Create a 'room' StreamRow attached to a project, with the
    given members. Returns the stream id.
    """
    async with session_scope(maker) as session:
        repo = StreamRepository(session)
        stream = await repo.create(
            type="room", project_id=project_id, name="RW4 Room"
        )
        member_repo = StreamMemberRepository(session)
        for uid in members:
            await member_repo.add(stream_id=stream.id, user_id=uid)
    return stream.id


# ---- room (multi-party) shape -------------------------------------------


@pytest.mark.asyncio
async def test_room_detail_returns_full_shape(api_env):
    """Room conversation: title, type='room', scope_id=project_id,
    participants populated, right_rail null, messages array exists.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw4_room_owner")
    member_id = await _register_and_login(client, "rw4_room_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    sid = await _mk_room(maker, project_id=pid, members=[owner_id, member_id])

    await _login(client, "rw4_room_owner")
    r = await client.get(f"/api/conversations/{sid}")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["id"] == sid
    assert body["type"] == "room"
    assert body["title"] == "RW4 Room"
    assert body["scope_id"] == pid
    assert body["topic_status"] is None
    assert body["right_rail"] is None

    participants = body["participants"]
    assert isinstance(participants, list)
    pids_seen = {p["user_id"] for p in participants}
    assert owner_id in pids_seen
    assert member_id in pids_seen
    # Each participant carries the display fields the FE consumes.
    for p in participants:
        assert "user_id" in p
        assert "username" in p
        assert "display_name" in p

    assert isinstance(body["messages"], list)


# ---- direct (DM) shape --------------------------------------------------


@pytest.mark.asyncio
async def test_dm_detail_returns_direct_type_and_two_members(api_env):
    """DM created via /api/streams/dm should report type='direct'
    with both members in `participants` and scope_id=null.
    """
    client, _maker, *_ = api_env
    await _register_and_login(client, "rw4_dm_a")
    other_id = await _register_and_login(client, "rw4_dm_b")

    await _login(client, "rw4_dm_a")
    r = await client.post(
        "/api/streams/dm", json={"other_user_id": other_id}
    )
    assert r.status_code == 200, r.text
    sid = r.json()["stream"]["id"]

    r = await client.get(f"/api/conversations/{sid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "direct"
    assert body["scope_id"] is None
    assert len(body["participants"]) == 2
    # Title fallback when DM has no name + no project — id prefix.
    assert body["title"]


# ---- membership + not-found gates --------------------------------------


@pytest.mark.asyncio
async def test_non_member_gets_403(api_env):
    """Caller not in the stream → 403, no detail leakage."""
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw4_403_owner")
    member_id = await _register_and_login(client, "rw4_403_member")
    outsider_id = await _register_and_login(client, "rw4_403_outsider")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    sid = await _mk_room(maker, project_id=pid, members=[owner_id, member_id])

    await _login(client, "rw4_403_outsider")
    r = await client.get(f"/api/conversations/{sid}")
    assert r.status_code == 403, r.text
    # Outsider id is unused at runtime — just here to make the test
    # name describe the actual gate exercised.
    assert outsider_id != owner_id


@pytest.mark.asyncio
async def test_unknown_id_returns_404(api_env):
    """Stream id that doesn't exist → 404."""
    client, *_ = api_env
    await _register_and_login(client, "rw4_404_user")
    await _login(client, "rw4_404_user")
    r = await client.get(
        "/api/conversations/stream-that-does-not-exist"
    )
    assert r.status_code == 404, r.text


# ---- message wire shape -------------------------------------------------


@pytest.mark.asyncio
async def test_message_wire_fields_match_fe_consumer(api_env):
    """Post a message in a room, GET the detail, assert the message
    rows carry the field names the FE reads (`author_id`,
    `author_username`, `body`, `created_at`, `kind`, `linked_id`).
    The FE's MessageStream relies on these exact names; a rename
    breaks the surface silently.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw4_msg_owner")
    member_id = await _register_and_login(client, "rw4_msg_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    sid = await _mk_room(maker, project_id=pid, members=[owner_id, member_id])

    await _login(client, "rw4_msg_owner")
    r = await client.post(
        f"/api/conversations/{sid}/messages",
        json={"body": "Hello room"},
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/conversations/{sid}")
    assert r.status_code == 200, r.text
    body = r.json()
    msgs = body["messages"]
    assert len(msgs) >= 1
    first = msgs[0]
    for field in (
        "id",
        "stream_id",
        "author_id",
        "author_username",
        "body",
        "kind",
        "linked_id",
        "created_at",
    ):
        assert field in first, (field, first)
    assert first["body"] == "Hello room"
    assert first["author_id"] == owner_id
    # author_username is resolved from UserRow; should not be None for
    # a known-registered author.
    assert first["author_username"]


# ---- list endpoint: last_message_at is populated -----------------------


@pytest.mark.asyncio
async def test_list_recent_carries_non_null_last_message_at(api_env):
    """GET /api/conversations must surface a non-null `last_message_at`
    for a conversation with activity.

    Regression: the list handler used to read the source key
    `last_message_at` from the shaped stream dict, but _shape_stream
    only emits `last_activity_at`. The mismatch made the wire field
    permanently null, so the FE's "last active {time}" label never
    rendered (ConversationList.tsx guards on `row.last_message_at`).
    The handler now reads `last_activity_at`; the wire field name
    stays `last_message_at` for the FE consumer.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw4_list_owner")
    member_id = await _register_and_login(client, "rw4_list_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    sid = await _mk_room(maker, project_id=pid, members=[owner_id, member_id])

    await _login(client, "rw4_list_owner")
    # Post a message to bump last_activity_at (also non-null on create).
    r = await client.post(
        f"/api/conversations/{sid}/messages",
        json={"body": "Hello room"},
    )
    assert r.status_code == 200, r.text

    r = await client.get("/api/conversations")
    assert r.status_code == 200, r.text
    body = r.json()

    rooms = [c for c in body["recent"] if c["id"] == sid]
    assert len(rooms) == 1, body
    row = rooms[0]
    # The wire field the FE reads must be present and non-null — an ISO
    # timestamp string, not None.
    assert row["last_message_at"] is not None, row
    assert isinstance(row["last_message_at"], str)
