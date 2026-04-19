"""Phase B (v2) — stream-primitive tests.

Covers:
  * project stream auto-creation when a project is created (via intake)
  * DM dedup: calling POST /api/streams/dm twice returns the same stream
  * GET /api/streams ordering by last_activity_at
  * message post bumps stream.last_activity_at
  * observer-tier members cannot post messages (403)

All paths go through the HTTP surface so auth guards + the stream service
are exercised together.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from workgraph_api.main import app
from workgraph_persistence import (
    ProjectMemberRow,
    StreamMemberRow,
    StreamRow,
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


# ---------- project stream auto-creation ---------------------------------


@pytest.mark.asyncio
async def test_project_creation_auto_creates_project_stream(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "stream_owner_1")
    project_id = await _intake(client, "streams-evt-1")

    async with session_scope(maker) as session:
        rows = list(
            (
                await session.execute(
                    select(StreamRow).where(StreamRow.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1, "expected exactly one project stream"
        stream = rows[0]
        assert stream.type == "project"

        members = list(
            (
                await session.execute(
                    select(StreamMemberRow).where(
                        StreamMemberRow.stream_id == stream.id
                    )
                )
            )
            .scalars()
            .all()
        )
        # Creator is automatically a member of the project stream.
        assert len(members) == 1
        # Creator gets admin role in the stream (mirrors project owner).
        assert members[0].role_in_stream == "admin"


@pytest.mark.asyncio
async def test_get_streams_lists_project_stream_for_member(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "stream_lister")
    project_id = await _intake(client, "streams-evt-list")

    r = await client.get("/api/streams")
    assert r.status_code == 200, r.text
    body = r.json()
    project_streams = [s for s in body["streams"] if s["type"] == "project"]
    assert len(project_streams) == 1
    assert project_streams[0]["project_id"] == project_id
    assert project_streams[0]["unread_count"] == 0
    # Creator is the sole member right after intake.
    assert len(project_streams[0]["members"]) == 1


# ---------- DM dedup -----------------------------------------------------


@pytest.mark.asyncio
async def test_create_dm_is_idempotent(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "dm_alice")
    me = await client.get("/api/auth/me")
    assert me.status_code == 200

    await _register(client, "dm_bob")
    bob = await client.get("/api/auth/me")
    assert bob.status_code == 200
    bob_id = bob.json()["id"]

    await _login(client, "dm_alice")

    r1 = await client.post("/api/streams/dm", json={"other_user_id": bob_id})
    assert r1.status_code == 200, r1.text
    first = r1.json()
    assert first["ok"] is True
    assert first["created"] is True
    stream_id = first["stream"]["id"]
    assert first["stream"]["type"] == "dm"
    assert len(first["stream"]["members"]) == 2

    # Second call returns the same stream; no duplicate created.
    r2 = await client.post("/api/streams/dm", json={"other_user_id": bob_id})
    assert r2.status_code == 200, r2.text
    second = r2.json()
    assert second["ok"] is True
    assert second["created"] is False
    assert second["stream"]["id"] == stream_id

    # Bob initiating from the other side must find the same stream.
    await _login(client, "dm_bob")
    me_alice = await client.get("/api/auth/me")  # Bob is logged in now
    # Fetch Alice's id via the stream members returned earlier.
    alice_id = next(
        m["user_id"]
        for m in first["stream"]["members"]
        if m["username"] == "dm_alice"
    )
    r3 = await client.post("/api/streams/dm", json={"other_user_id": alice_id})
    assert r3.status_code == 200, r3.text
    third = r3.json()
    assert third["created"] is False
    assert third["stream"]["id"] == stream_id


@pytest.mark.asyncio
async def test_create_dm_rejects_unknown_user(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "dm_lone")
    r = await client.post(
        "/api/streams/dm", json={"other_user_id": "nope-this-user-does-not-exist"}
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_dm_self_rejected(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "dm_solo")
    me = (await client.get("/api/auth/me")).json()
    r = await client.post("/api/streams/dm", json={"other_user_id": me["id"]})
    assert r.status_code == 400


# ---------- streams list ordering ---------------------------------------


@pytest.mark.asyncio
async def test_streams_list_ordered_by_last_activity(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "order_owner")
    project_id_1 = await _intake(client, "streams-order-1")
    # Small gap so timestamps differ.
    await asyncio.sleep(0.01)
    project_id_2 = await _intake(client, "streams-order-2")

    # Post a message into project 1 to bump its last_activity_at past project 2.
    await asyncio.sleep(0.01)
    r = await client.post(
        f"/api/projects/{project_id_1}/messages",
        json={"body": "hello stream one, bumping activity"},
    )
    assert r.status_code == 200

    body = (await client.get("/api/streams")).json()
    project_streams = [s for s in body["streams"] if s["type"] == "project"]
    assert len(project_streams) == 2
    # Most recent activity first.
    assert project_streams[0]["project_id"] == project_id_1
    assert project_streams[1]["project_id"] == project_id_2


@pytest.mark.asyncio
async def test_message_post_updates_stream_last_activity_at(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "activity_owner")
    project_id = await _intake(client, "streams-activity")

    async with session_scope(maker) as session:
        stream = (
            await session.execute(
                select(StreamRow).where(StreamRow.project_id == project_id)
            )
        ).scalar_one()
        before = stream.last_activity_at

    await asyncio.sleep(0.01)
    r = await client.post(
        f"/api/projects/{project_id}/messages",
        json={"body": "activity ping message to bump last_activity_at"},
    )
    assert r.status_code == 200

    async with session_scope(maker) as session:
        stream = (
            await session.execute(
                select(StreamRow).where(StreamRow.project_id == project_id)
            )
        ).scalar_one()
        after = stream.last_activity_at

    assert after > before


# ---------- observer license tier ----------------------------------------


@pytest.mark.asyncio
async def test_observer_cannot_post_message(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "obs_owner")
    project_id = await _intake(client, "streams-observer")
    await _register(client, "obs_reader")
    await _login(client, "obs_owner")
    invite = await client.post(
        f"/api/projects/{project_id}/invite", json={"username": "obs_reader"}
    )
    assert invite.status_code == 200

    # Flip the invited member to observer tier directly via ORM —
    # no UI endpoint yet (v2 polish), but enforcement must already work.
    async with session_scope(maker) as session:
        member = (
            await session.execute(
                select(ProjectMemberRow).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id != (
                        (await client.get("/api/auth/me")).json()["id"]
                    ),
                )
            )
        ).scalar_one()
        member.license_tier = "observer"

    await _login(client, "obs_reader")
    r = await client.post(
        f"/api/projects/{project_id}/messages",
        json={"body": "observer trying to post — this must be rejected"},
    )
    assert r.status_code == 403
