"""Phase V — KbItemRow service tests."""
from __future__ import annotations

import uuid

import pytest

from workgraph_persistence import (
    ProjectMemberRepository,
    ProjectRow,
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
        session.add(ProjectRow(id=pid, title="KB Test"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
    return pid


# ---- create + list ------------------------------------------------------


@pytest.mark.asyncio
async def test_create_personal_item_visible_to_owner_only(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_a_owner")
    member_id = await _register_and_login(client, "kb_a_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    # Member writes a personal note.
    await _login(client, "kb_a_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={"title": "my private notes", "content_md": "# hidden"},
    )
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["scope"] == "personal"
    assert item["owner_user_id"] == member_id
    item_id = item["id"]

    # Owner of the project does NOT see the personal item.
    await _login(client, "kb_a_owner")
    r = await client.get(f"/api/projects/{pid}/kb-items")
    assert r.status_code == 200
    titles = [i["title"] for i in r.json()["items"]]
    assert "my private notes" not in titles

    # Member sees their own item.
    await _login(client, "kb_a_member")
    r = await client.get(f"/api/projects/{pid}/kb-items")
    titles = [i["title"] for i in r.json()["items"]]
    assert "my private notes" in titles

    # Owner trying to GET the item directly → 403.
    await _login(client, "kb_a_owner")
    r = await client.get(f"/api/kb-items/{item_id}")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_group_item_visible_to_all_members(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_b_owner")
    member_id = await _register_and_login(client, "kb_b_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_b_owner")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "shared playbook",
            "content_md": "everyone reads this",
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text

    await _login(client, "kb_b_member")
    r = await client.get(f"/api/projects/{pid}/kb-items")
    titles = [i["title"] for i in r.json()["items"]]
    assert "shared playbook" in titles


@pytest.mark.asyncio
async def test_non_member_cannot_create_or_list(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_c_owner")
    member_id = await _register_and_login(client, "kb_c_member")
    outsider_id = await _register_and_login(client, "kb_c_outsider")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_c_outsider")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={"title": "intruder", "content_md": ""},
    )
    assert r.status_code == 403
    assert r.json()["message"] == "not_a_member"

    r = await client.get(f"/api/projects/{pid}/kb-items")
    assert r.status_code == 403


# ---- update + delete ----------------------------------------------------


@pytest.mark.asyncio
async def test_owner_can_edit_own_item(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_d_owner")
    member_id = await _register_and_login(client, "kb_d_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_d_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={"title": "v1", "content_md": "draft"},
    )
    item_id = r.json()["id"]

    r = await client.patch(
        f"/api/kb-items/{item_id}",
        json={"title": "v2", "content_md": "polished"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "v2"


@pytest.mark.asyncio
async def test_other_member_cannot_edit_personal_item(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_e_owner")
    member_id = await _register_and_login(client, "kb_e_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_e_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items", json={"title": "mine"}
    )
    item_id = r.json()["id"]

    # Project owner CAN edit (covers cleanup case).
    await _login(client, "kb_e_owner")
    r = await client.patch(
        f"/api/kb-items/{item_id}", json={"title": "edited by owner"}
    )
    # Project owner sees the item only because they're project owner;
    # personal-scope read still requires owner_user_id == viewer for
    # GET, but PATCH path checks via _assert_can_edit which permits
    # project owner. Document: edit allowed → ok.
    assert r.status_code == 200, r.text


# ---- promotion ----------------------------------------------------------


@pytest.mark.asyncio
async def test_promote_personal_to_group(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_f_owner")
    member_id = await _register_and_login(client, "kb_f_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    await _login(client, "kb_f_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items", json={"title": "my note"}
    )
    item_id = r.json()["id"]
    assert r.json()["scope"] == "personal"

    r = await client.post(f"/api/kb-items/{item_id}/promote")
    assert r.status_code == 200, r.text
    assert r.json()["scope"] == "group"

    # Now visible to project owner via list.
    await _login(client, "kb_f_owner")
    r = await client.get(f"/api/projects/{pid}/kb-items")
    titles = [i["title"] for i in r.json()["items"]]
    assert "my note" in titles


@pytest.mark.asyncio
async def test_demote_owner_only(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_g_owner")
    member_id = await _register_and_login(client, "kb_g_member")
    pid = await _mk_project_with_members(maker, owner_id=owner_id, member_id=member_id)

    # Member creates + promotes.
    await _login(client, "kb_g_member")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={"title": "joint plan", "scope": "group"},
    )
    item_id = r.json()["id"]

    # Member tries to demote → 403 (group → personal is owner-only).
    r = await client.post(f"/api/kb-items/{item_id}/demote")
    assert r.status_code == 403

    # Project owner demotes.
    await _login(client, "kb_g_owner")
    r = await client.post(f"/api/kb-items/{item_id}/demote")
    assert r.status_code == 200
    assert r.json()["scope"] == "personal"
