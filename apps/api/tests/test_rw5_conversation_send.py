"""RW-5 — Conversation send endpoint tests.

Exercises POST /api/conversations/:id/messages end-to-end against
the live StreamService. Coverage:

  * member can post + GET refetch surfaces the new message
  * non-member POST returns 403 not_a_member with the WG envelope
  * unknown conversation id returns 404 stream_not_found
  * empty body fails 422 validation (pydantic min_length=1)
  * over-long body fails 422 validation (pydantic max_length=4000)

The happy path is already touched by RW-4's wire-shape test; the
membership 403 path is the load-bearing one we add here so the FE's
typed error decoder has a real assertion.
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
        session.add(ProjectRow(id=pid, title="RW5 Project"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
    return pid


async def _mk_room(maker, *, project_id: str, members: list[str]) -> str:
    async with session_scope(maker) as session:
        repo = StreamRepository(session)
        stream = await repo.create(
            type="room", project_id=project_id, name="RW5 Room"
        )
        member_repo = StreamMemberRepository(session)
        for uid in members:
            await member_repo.add(stream_id=stream.id, user_id=uid)
    return stream.id


# ---- happy path: member posts, GET sees the message --------------------


@pytest.mark.asyncio
async def test_member_can_post_and_refetch_sees_message(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw5_owner_post")
    member_id = await _register_and_login(client, "rw5_member_post")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    sid = await _mk_room(maker, project_id=pid, members=[owner_id, member_id])

    await _login(client, "rw5_member_post")
    body = "hello from the member"
    r = await client.post(
        f"/api/conversations/{sid}/messages",
        json={"body": body},
    )
    assert r.status_code == 200, r.text
    posted = r.json()
    assert posted.get("ok") is True
    assert posted.get("body") == body
    assert posted.get("author_id") == member_id

    # GET refetch sees the new message — the FE relies on this path
    # rather than appending the POST response, so verify the wire.
    r = await client.get(f"/api/conversations/{sid}")
    assert r.status_code == 200, r.text
    msgs = r.json()["messages"]
    bodies = [m["body"] for m in msgs]
    assert body in bodies, msgs


# ---- 403 non-member ----------------------------------------------------


@pytest.mark.asyncio
async def test_non_member_post_returns_403(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw5_owner_403")
    member_id = await _register_and_login(client, "rw5_member_403")
    outsider_id = await _register_and_login(client, "rw5_outsider_403")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    sid = await _mk_room(maker, project_id=pid, members=[owner_id, member_id])

    await _login(client, "rw5_outsider_403")
    r = await client.post(
        f"/api/conversations/{sid}/messages",
        json={"body": "outsider tries to chat"},
    )
    assert r.status_code == 403, r.text
    # WG envelope — string detail surfaces as `message`.
    assert r.json().get("message") == "not_a_member"
    # outsider_id used by name to make the test readable
    assert outsider_id != owner_id


# ---- 404 unknown stream ------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_stream_post_returns_404(api_env):
    client, *_ = api_env
    await _register_and_login(client, "rw5_404_user")
    await _login(client, "rw5_404_user")
    r = await client.post(
        "/api/conversations/stream-does-not-exist/messages",
        json={"body": "into the void"},
    )
    assert r.status_code == 404, r.text
    assert r.json().get("message") == "stream_not_found"


# ---- 422 validation ----------------------------------------------------


@pytest.mark.asyncio
async def test_empty_body_returns_422(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw5_empty_owner")
    member_id = await _register_and_login(client, "rw5_empty_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    sid = await _mk_room(maker, project_id=pid, members=[owner_id, member_id])

    await _login(client, "rw5_empty_owner")
    r = await client.post(
        f"/api/conversations/{sid}/messages",
        json={"body": ""},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_over_long_body_returns_422(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw5_long_owner")
    member_id = await _register_and_login(client, "rw5_long_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    sid = await _mk_room(maker, project_id=pid, members=[owner_id, member_id])

    await _login(client, "rw5_long_owner")
    r = await client.post(
        f"/api/conversations/{sid}/messages",
        json={"body": "x" * 4001},
    )
    assert r.status_code == 422, r.text
