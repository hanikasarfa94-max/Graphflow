"""RW-8 — Document detail endpoint tests.

Covers the singleton GET /api/documents/:id added in this slice.
The list endpoint GET /api/documents is already covered by the
documents router tests; this file targets the singleton's wire
shape, membership gate, and 404 behavior.
"""
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
        session.add(ProjectRow(id=pid, title="RW8 Project"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
    return pid


async def _create_kb_doc(client, pid: str, title: str, body: str) -> str:
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={"title": title, "content_md": body, "scope": "group"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_singleton_returns_full_envelope(api_env):
    """GET /api/documents/:id wraps KbItemService.get and returns
    the v0.6.2 document envelope with content_md + attachment +
    owner_user_id populated. Every field the FE detail page reads
    is asserted here.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw8_doc_owner")
    member_id = await _register_and_login(client, "rw8_doc_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "rw8_doc_owner")
    doc_id = await _create_kb_doc(
        client, pid, "RW8 sanity doc", "# RW8 body"
    )

    r = await client.get(f"/api/documents/{doc_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "document" in body
    doc = body["document"]
    for field in (
        "document_id",
        "scope_id",
        "title",
        "scope",
        "status",
        "is_project_brief",
        "updated_at",
        "created_at",
        "source",
        "owner_user_id",
        "content_md",
        "attachment",
        "folder_id",
    ):
        assert field in doc, (field, doc)
    assert doc["document_id"] == doc_id
    assert doc["title"] == "RW8 sanity doc"
    assert doc["content_md"] == "# RW8 body"
    assert doc["scope_id"] == pid
    assert doc["owner_user_id"] == owner_id


@pytest.mark.asyncio
async def test_singleton_403_for_non_member(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw8_doc_owner_403")
    member_id = await _register_and_login(client, "rw8_doc_member_403")
    outsider_id = await _register_and_login(client, "rw8_doc_outsider")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "rw8_doc_owner_403")
    doc_id = await _create_kb_doc(client, pid, "scope-fenced", "x")

    await _login(client, "rw8_doc_outsider")
    r = await client.get(f"/api/documents/{doc_id}")
    assert r.status_code in (403, 404), r.text
    assert outsider_id != owner_id


@pytest.mark.asyncio
async def test_singleton_404_for_unknown_id(api_env):
    client, *_ = api_env
    await _register_and_login(client, "rw8_doc_404")
    await _login(client, "rw8_doc_404")
    r = await client.get("/api/documents/does-not-exist")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_singleton_list_envelope_parity(api_env):
    """Common fields between the singleton response and each row in
    the list endpoint must match — same names, same values. The FE
    consumes one renderer for both.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw8_doc_parity_owner")
    member_id = await _register_and_login(client, "rw8_doc_parity_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "rw8_doc_parity_owner")
    doc_id = await _create_kb_doc(client, pid, "parity doc", "body")

    singleton = (
        await client.get(f"/api/documents/{doc_id}")
    ).json()["document"]
    list_r = await client.get(f"/api/documents?scope_id={pid}&type=all")
    list_rows = list_r.json()["documents"]
    row = next(d for d in list_rows if d["document_id"] == doc_id)

    # Singleton must be a superset of the list shape; common fields
    # must agree.
    common = set(row.keys()) & set(singleton.keys())
    assert "document_id" in common
    assert "title" in common
    assert "scope_id" in common
    for k in common:
        assert singleton[k] == row[k], (k, singleton[k], row[k])
