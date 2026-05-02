"""Shell v-Next stream-context tests (E-5 — analysisCard data).

Covers:
  * GET /api/vnext/streams/{id}/related on a project stream returns
    project tasks/decisions/risks (decisions+risks empty in seed)
  * 通用 Agent stream (project_id=NULL) returns empty lists
  * non-member viewer is 403
  * unknown stream is 404
  * anonymous is 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from workgraph_persistence import (
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


@pytest.mark.asyncio
async def test_related_for_project_stream_returns_tasks(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "vnext_streams_owner")
    project_id = await _intake(client, "vnext-streams-evt-1")

    # Find the project stream id.
    async with session_scope(maker) as session:
        repo = StreamRepository(session)
        project_stream = await repo.get_for_project(project_id)
        assert project_stream is not None
        stream_id = project_stream.id

    r = await client.get(f"/api/vnext/streams/{stream_id}/related")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "tasks" in body
    assert "decisions" in body
    assert "risks" in body
    # Intake-produced tasks should be present.
    assert isinstance(body["tasks"], list)
    # Each task carries the v-Next shape.
    for t in body["tasks"]:
        assert "id" in t and "title" in t and "status" in t and "scope" in t


@pytest.mark.asyncio
async def test_related_for_global_personal_stream_is_empty(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "vnext_streams_global")

    # Materialize the user's global personal stream by calling the
    # streams listing — it lazily creates the global agentPrimary row.
    r = await client.get("/api/streams")
    assert r.status_code == 200

    # Find any personal stream with project_id null (the 通用 Agent).
    async with session_scope(maker) as session:
        from sqlalchemy import select
        from workgraph_persistence import StreamRow, UserRepository

        user_row = await UserRepository(session).get_by_username(
            "vnext_streams_global"
        )
        assert user_row is not None
        # Force-create the global stream via repo helper since GET /api/streams
        # returns user's existing memberships and may not create one.
        repo = StreamRepository(session)
        existing = await repo.get_personal_global_for_user(user_id=user_row.id)
        if existing is None:
            existing = await repo.create(
                type="personal", owner_user_id=user_row.id
            )
            from workgraph_persistence import StreamMemberRepository

            await StreamMemberRepository(session).add(
                stream_id=existing.id,
                user_id=user_row.id,
                role_in_stream="admin",
            )
            await session.commit()
        stream_id = existing.id

    r = await client.get(f"/api/vnext/streams/{stream_id}/related")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"tasks": [], "decisions": [], "risks": []}


@pytest.mark.asyncio
async def test_related_non_member_is_403(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "vnext_streams_owner_b")
    project_id = await _intake(client, "vnext-streams-evt-2")

    async with session_scope(maker) as session:
        repo = StreamRepository(session)
        project_stream = await repo.get_for_project(project_id)
        stream_id = project_stream.id

    # Different user — not a member of this project.
    await _register(client, "vnext_streams_outsider")

    r = await client.get(f"/api/vnext/streams/{stream_id}/related")
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_related_unknown_stream_is_404(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "vnext_streams_404")

    r = await client.get("/api/vnext/streams/does-not-exist/related")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_related_anonymous_is_401(api_env):
    client, _, _, _, _, _ = api_env
    client.cookies.clear()
    r = await client.get("/api/vnext/streams/whatever/related")
    assert r.status_code == 401, r.text
