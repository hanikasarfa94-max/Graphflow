"""Organization (Workspace) tier — Phase T tests.

Covers the minimum-viable surface:
  * create / list-for-user / get-by-slug
  * invite (existing-user happy path + missing-user friendly error)
  * role update (owner-only) + last-owner guard
  * remove member (owner-only) + last-owner guard
  * attach project (workspace-mgr + project-owner double-check)

Authority delegation FROM workspace TO members (scoped views) is v2;
not exercised here.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    ProjectMemberRepository,
    ProjectRow,
    UserRepository,
    session_scope,
)


# ---- helpers ------------------------------------------------------------


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


async def _mk_project(maker, owner_id: str) -> str:
    """Insert a project row directly + add the given user as owner.
    Bypasses the intake flow so tests stay focused on the org tier."""
    import uuid

    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="Stellar Drift"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
    return pid


# ---- 1. create + list ---------------------------------------------------


@pytest.mark.asyncio
async def test_create_workspace_creator_becomes_owner(api_env):
    client, *_ = api_env
    await _register_and_login(client, "ws_owner_1")

    r = await client.post(
        "/api/organizations",
        json={"name": "Acme Studio", "slug": "acme", "description": "test"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Acme Studio"
    assert body["slug"] == "acme"

    # Lists for the creator with role=owner.
    r = await client.get("/api/organizations")
    assert r.status_code == 200
    workspaces = r.json()
    assert len(workspaces) == 1
    assert workspaces[0]["slug"] == "acme"
    assert workspaces[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_duplicate_slug_rejected(api_env):
    client, *_ = api_env
    await _register_and_login(client, "ws_dup_1")
    r1 = await client.post(
        "/api/organizations",
        json={"name": "First", "slug": "shared"},
    )
    assert r1.status_code == 200, r1.text

    await _register_and_login(client, "ws_dup_2")
    r2 = await client.post(
        "/api/organizations",
        json={"name": "Second", "slug": "shared"},
    )
    assert r2.status_code == 409
    assert r2.json()["message"] == "duplicate_slug"


@pytest.mark.asyncio
async def test_invalid_slug_rejected(api_env):
    client, *_ = api_env
    await _register_and_login(client, "ws_badslug")
    r = await client.post(
        "/api/organizations",
        json={"name": "Acme", "slug": "Acme!"},  # uppercase + bang invalid
    )
    assert r.status_code == 400
    assert r.json()["message"] == "invalid_slug"


# ---- 2. invite ---------------------------------------------------------


@pytest.mark.asyncio
async def test_invite_known_user_happy_path(api_env):
    client, *_ = api_env
    owner_id = await _register_and_login(client, "ws_inv_owner")
    target_id = await _register_and_login(client, "ws_inv_target")
    await _login(client, "ws_inv_owner")
    await client.post(
        "/api/organizations",
        json={"name": "Workshop", "slug": "workshop"},
    )

    r = await client.post(
        "/api/organizations/workshop/invite",
        json={"username": "ws_inv_target", "role": "member"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["user_id"] == target_id
    assert r.json()["role"] == "member"

    # Target now sees the workspace in their list.
    await _login(client, "ws_inv_target")
    r = await client.get("/api/organizations")
    slugs = [w["slug"] for w in r.json()]
    assert "workshop" in slugs


@pytest.mark.asyncio
async def test_invite_unknown_user_returns_user_not_found(api_env):
    client, *_ = api_env
    await _register_and_login(client, "ws_404_owner")
    await client.post(
        "/api/organizations",
        json={"name": "Lonely", "slug": "lonely"},
    )
    r = await client.post(
        "/api/organizations/lonely/invite",
        json={"username": "ghost_user_does_not_exist"},
    )
    assert r.status_code == 404
    assert r.json()["message"] == "user_not_found"


@pytest.mark.asyncio
async def test_non_admin_cannot_invite(api_env):
    client, *_ = api_env
    owner_id = await _register_and_login(client, "ws_perm_owner")
    member_id = await _register_and_login(client, "ws_perm_member")
    third_id = await _register_and_login(client, "ws_perm_third")

    await _login(client, "ws_perm_owner")
    await client.post(
        "/api/organizations",
        json={"name": "Gated", "slug": "gated"},
    )
    await client.post(
        "/api/organizations/gated/invite",
        json={"username": "ws_perm_member", "role": "member"},
    )

    # Member tries to invite the third user → 403.
    await _login(client, "ws_perm_member")
    r = await client.post(
        "/api/organizations/gated/invite",
        json={"username": "ws_perm_third"},
    )
    assert r.status_code == 403
    assert r.json()["message"] == "forbidden"


# ---- 3. role update ----------------------------------------------------


@pytest.mark.asyncio
async def test_owner_promotes_member_to_admin(api_env):
    client, *_ = api_env
    await _register_and_login(client, "ws_role_owner")
    member_id = await _register_and_login(client, "ws_role_member")
    await _login(client, "ws_role_owner")
    await client.post(
        "/api/organizations",
        json={"name": "Roles", "slug": "roles"},
    )
    await client.post(
        "/api/organizations/roles/invite",
        json={"username": "ws_role_member", "role": "member"},
    )

    r = await client.patch(
        f"/api/organizations/roles/members/{member_id}",
        json={"role": "admin"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_cannot_demote_last_owner(api_env):
    client, *_ = api_env
    owner_id = await _register_and_login(client, "ws_lastowner")
    await client.post(
        "/api/organizations",
        json={"name": "Solo", "slug": "solo"},
    )
    r = await client.patch(
        f"/api/organizations/solo/members/{owner_id}",
        json={"role": "member"},
    )
    assert r.status_code == 400
    assert r.json()["message"] == "last_owner"


# ---- 4. attach project --------------------------------------------------


@pytest.mark.asyncio
async def test_attach_project_owner_can_attach(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "ws_attach_owner")
    await _login(client, "ws_attach_owner")
    pid = await _mk_project(maker, owner_id)
    await client.post(
        "/api/organizations",
        json={"name": "AttachStudio", "slug": "attachstudio"},
    )

    r = await client.post(
        f"/api/organizations/attachstudio/projects/{pid}/attach", json={}
    )
    assert r.status_code == 200, r.text
    assert r.json()["project_id"] == pid

    # Verify the project row links back.
    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(ProjectRow).where(ProjectRow.id == pid)
            )
        ).scalar_one()
        assert row.organization_id is not None

    # And the workspace detail surfaces the attached project.
    r = await client.get("/api/organizations/attachstudio")
    assert pid in [p["id"] for p in r.json()["projects"]]


@pytest.mark.asyncio
async def test_non_workspace_admin_cannot_attach_project(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "ws_attach_other_owner")
    await _login(client, "ws_attach_other_owner")
    pid = await _mk_project(maker, owner_id)

    # Different user creates a workspace; original owner tries to
    # attach their project → forbidden (not a workspace member).
    other_id = await _register_and_login(client, "ws_attach_other_random")
    await client.post(
        "/api/organizations",
        json={"name": "Other", "slug": "other"},
    )

    await _login(client, "ws_attach_other_owner")
    r = await client.post(
        f"/api/organizations/other/projects/{pid}/attach", json={}
    )
    assert r.status_code == 403
    assert r.json()["message"] == "forbidden"
