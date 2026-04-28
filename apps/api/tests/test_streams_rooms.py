"""N-Next multi-room — POST/GET /api/projects/{id}/rooms tests.

Covers the room-creation contract (creator must be cell member, every
listed member must be cell member, name validation, creator auto-add)
and the listing contract (cell members + B4 leader-bypass for org
owners/admins).

Per new_concepts.md §6.11 + north-star Correction R.2: a cell hosts
multiple team-room streams. This file is the regression net for that
behavior; the frontend port (N.2) consumes these endpoints.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from workgraph_api.main import app
from workgraph_persistence import (
    OrganizationMemberRepository,
    OrganizationRepository,
    ProjectRow,
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


async def _invite(client: AsyncClient, project_id: str, username: str) -> None:
    r = await client.post(
        f"/api/projects/{project_id}/invite",
        json={"username": username},
    )
    assert r.status_code == 200, r.text


# ---------- create_room: happy path -------------------------------------


@pytest.mark.asyncio
async def test_create_room_happy_path(api_env):
    """Creator is cell member, all listed members are cell members ->
    room created with type='room', creator auto-added as admin."""
    client, _, _, _, _, _ = api_env
    await _register(client, "rm_creator")
    project_id = await _intake(client, "rooms-evt-happy")

    await _register(client, "rm_member_a")
    await _login(client, "rm_creator")
    await _invite(client, project_id, "rm_member_a")

    member_a_id = await _alt_login_get_me(client, "rm_member_a")

    await _login(client, "rm_creator")
    r = await client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": "design-sync", "member_user_ids": [member_a_id]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    stream = body["stream"]
    assert stream["type"] == "room"
    assert stream["project_id"] == project_id
    member_ids = {m["user_id"] for m in stream["members"]}
    # Creator + listed member; creator auto-added.
    assert len(member_ids) == 2
    assert member_a_id in member_ids


@pytest.mark.asyncio
async def test_create_room_creator_auto_added_when_omitted(api_env):
    """member_user_ids may be empty — creator is still added so the
    room has at least one occupant on creation."""
    client, _, _, _, _, _ = api_env
    await _register(client, "rm_solo_creator")
    project_id = await _intake(client, "rooms-evt-solo")

    r = await client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": "solo-think", "member_user_ids": []},
    )
    assert r.status_code == 200, r.text
    members = r.json()["stream"]["members"]
    assert len(members) == 1


# ---------- create_room: rejection paths --------------------------------


@pytest.mark.asyncio
async def test_create_room_rejects_non_member_creator(api_env):
    """A user outside the cell cannot create a room in it (403)."""
    client, _, _, _, _, _ = api_env
    await _register(client, "rm_owner")
    project_id = await _intake(client, "rooms-evt-noncreator")

    await _register(client, "rm_outsider")
    await _login(client, "rm_outsider")
    r = await client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": "stealth", "member_user_ids": []},
    )
    assert r.status_code == 403, r.text
    assert "not_a_member" in r.json()["message"]


@pytest.mark.asyncio
async def test_create_room_rejects_non_cell_member_in_payload(api_env):
    """Listing a user who isn't a cell member is rejected wholesale —
    rooms cannot exfiltrate cell-scoped state to outsiders."""
    client, _, _, _, _, _ = api_env
    await _register(client, "rm_owner_x")
    project_id = await _intake(client, "rooms-evt-leak")

    await _register(client, "rm_outsider_x")
    outsider_id = await _alt_login_get_me(client, "rm_outsider_x")

    await _login(client, "rm_owner_x")
    r = await client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": "leak-attempt", "member_user_ids": [outsider_id]},
    )
    assert r.status_code == 400, r.text
    assert "non_cell_member" in r.json()["message"]


@pytest.mark.asyncio
async def test_create_room_rejects_empty_name(api_env):
    """Pydantic catches empty name at validation (422). Whitespace-only
    falls through to service which rejects with name_required (400)."""
    client, _, _, _, _, _ = api_env
    await _register(client, "rm_owner_ws")
    project_id = await _intake(client, "rooms-evt-name")

    # Pydantic min_length=1 → 422 for empty string.
    r1 = await client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": "", "member_user_ids": []},
    )
    assert r1.status_code == 422

    # Whitespace-only passes pydantic but service strips it -> 400.
    r2 = await client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": "   ", "member_user_ids": []},
    )
    assert r2.status_code == 400, r2.text
    assert "name_required" in r2.json()["message"]


# ---------- list_rooms --------------------------------------------------


@pytest.mark.asyncio
async def test_list_rooms_returns_only_room_streams(api_env):
    """The 'project' (main team room), 'personal', and 'dm' streams
    are NOT in this listing — only type='room' streams."""
    client, _, _, _, _, _ = api_env
    await _register(client, "rm_lister")
    project_id = await _intake(client, "rooms-evt-list")

    # Create two rooms.
    for name in ("design-sync", "engineering-sync"):
        r = await client.post(
            f"/api/projects/{project_id}/rooms",
            json={"name": name, "member_user_ids": []},
        )
        assert r.status_code == 200

    r = await client.get(f"/api/projects/{project_id}/rooms")
    assert r.status_code == 200
    body = r.json()
    rooms = body["rooms"]
    assert len(rooms) == 2
    assert all(room["type"] == "room" for room in rooms)
    assert all(room["project_id"] == project_id for room in rooms)


@pytest.mark.asyncio
async def test_list_rooms_rejects_non_member_non_lead(api_env):
    """Outsiders without cell membership AND without org leadership
    get 403."""
    client, _, _, _, _, _ = api_env
    await _register(client, "rm_owner_l")
    project_id = await _intake(client, "rooms-evt-listdeny")

    await _register(client, "rm_outsider_l")
    await _login(client, "rm_outsider_l")
    r = await client.get(f"/api/projects/{project_id}/rooms")
    assert r.status_code == 403, r.text
    assert "not_a_member" in r.json()["message"]


@pytest.mark.asyncio
async def test_list_rooms_org_lead_bypass(api_env):
    """B4 leader-bypass: an org owner/admin can list rooms in a cell
    they don't directly belong to. Read-only — they cannot create."""
    client, maker, _, _, _, _ = api_env
    await _register(client, "rm_org_admin")
    admin_id = (await client.get("/api/auth/me")).json()["id"]

    await _register(client, "rm_cell_owner")
    cell_owner_id = (await client.get("/api/auth/me")).json()["id"]
    project_id = await _intake(client, "rooms-evt-leadbypass")

    # Create a room so the listing has content.
    r = await client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": "design-sync", "member_user_ids": []},
    )
    assert r.status_code == 200

    # Wire an organization with rm_org_admin as owner; attach project.
    async with session_scope(maker) as session:
        org_repo = OrganizationRepository(session)
        org = await org_repo.create(
            name="Studio X",
            slug="studio-x",
            owner_user_id=admin_id,
        )
        await OrganizationMemberRepository(session).add(
            organization_id=org.id, user_id=admin_id, role="owner"
        )
        # Attach the project to the org (R.4 hook for cross-cell read).
        proj = await session.get(ProjectRow, project_id)
        proj.organization_id = org.id
        await session.flush()

    # Switch to the org admin (NOT a cell member).
    await _login(client, "rm_org_admin")
    r = await client.get(f"/api/projects/{project_id}/rooms")
    assert r.status_code == 200, r.text
    rooms = r.json()["rooms"]
    assert len(rooms) == 1
    assert rooms[0]["type"] == "room"

    # Org admin still cannot CREATE rooms in a cell they don't belong
    # to — the bypass is read-only.
    r2 = await client.post(
        f"/api/projects/{project_id}/rooms",
        json={"name": "stealth", "member_user_ids": []},
    )
    assert r2.status_code == 403


# ---------- helpers -----------------------------------------------------


async def _alt_login_get_me(client: AsyncClient, username: str) -> str:
    """Login as `username` and return the user's id. Restores prior
    login on exit so callers don't accidentally clobber session.

    We use a separate AsyncClient so the cookie jar swap doesn't
    invalidate the test's main session — pytest's api_env fixture
    expects the main client's cookies to remain coherent.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as alt:
        r = await alt.post(
            "/api/auth/login",
            json={"username": username, "password": "hunter22"},
        )
        assert r.status_code == 200, r.text
        me = await alt.get("/api/auth/me")
        return me.json()["id"]
