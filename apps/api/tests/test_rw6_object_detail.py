"""RW-6 — object-detail endpoint tests.

Covers the two read-only singletons added in this slice:
  * GET /api/scopes/:id     (scope X-ray)
  * GET /api/decisions/:id  (decision proof)

The existing GET /api/kb-items/:id endpoint is already covered by
test_kb_items.py (read access cases). We add one assertion here for
the wire shape the new /kb-items/:id FE page consumes, so any
schema drift surfaces before the page renders empty fields.
"""
from __future__ import annotations

import uuid

import pytest

from workgraph_persistence import (
    ConflictRepository,
    ConflictRow,
    DecisionRow,
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
        session.add(ProjectRow(id=pid, title="RW6 Project"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
    return pid


# ---- /api/scopes/:id ----------------------------------------------------


@pytest.mark.asyncio
async def test_scope_detail_returns_title_role_members(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw6_scope_owner")
    member_id = await _register_and_login(client, "rw6_scope_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    await _login(client, "rw6_scope_owner")
    r = await client.get(f"/api/scopes/{pid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == pid
    assert body["title"] == "RW6 Project"
    assert body["role"] == "owner"
    assert body["tier"] == "cell"
    user_ids = {m["user_id"] for m in body["members"]}
    assert owner_id in user_ids
    assert member_id in user_ids


@pytest.mark.asyncio
async def test_scope_detail_403_for_non_member(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw6_scope_owner2")
    member_id = await _register_and_login(client, "rw6_scope_member2")
    outsider_id = await _register_and_login(client, "rw6_scope_outsider")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    await _login(client, "rw6_scope_outsider")
    r = await client.get(f"/api/scopes/{pid}")
    assert r.status_code == 403, r.text
    assert outsider_id != owner_id


# ---- /api/decisions/:id -------------------------------------------------


@pytest.mark.asyncio
async def test_decision_detail_returns_payload_fields(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw6_dec_owner")
    member_id = await _register_and_login(client, "rw6_dec_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    # Seed a decision row directly — exercising the conflict-resolution
    # service is heavyweight and unrelated to this endpoint's contract.
    # The decision needs a conflict_id because DecisionRow has a NOT NULL
    # FK on conflict_id (the model carries it as a required column).
    decision_id = str(uuid.uuid4())
    conflict_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            ConflictRow(
                id=conflict_id,
                project_id=pid,
                rule="missing_owner",
                severity="medium",
                summary="seeded conflict",
                targets=[],
                detail={},
                fingerprint=f"rw6-test-{conflict_id}",
                status="open",
            )
        )
        await session.flush()
        session.add(
            DecisionRow(
                id=decision_id,
                conflict_id=conflict_id,
                project_id=pid,
                resolver_id=owner_id,
                option_index=0,
                custom_text=None,
                rationale="seeded decision rationale",
                apply_actions=[],
                apply_outcome="advisory",
                apply_detail={},
            )
        )

    await _login(client, "rw6_dec_owner")
    r = await client.get(f"/api/decisions/{decision_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == decision_id
    assert body["project_id"] == pid
    assert body["resolver_id"] == owner_id
    assert body["rationale"] == "seeded decision rationale"
    assert body["apply_outcome"] == "advisory"
    # Every field the FE detail page reads must exist.
    for field in (
        "id",
        "conflict_id",
        "source_suggestion_id",
        "project_id",
        "resolver_id",
        "option_index",
        "custom_text",
        "rationale",
        "apply_actions",
        "apply_outcome",
        "apply_detail",
        "created_at",
        "applied_at",
    ):
        assert field in body, (field, body)


@pytest.mark.asyncio
async def test_decision_detail_403_for_non_member(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw6_dec_owner2")
    member_id = await _register_and_login(client, "rw6_dec_member2")
    outsider_id = await _register_and_login(client, "rw6_dec_outsider")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    decision_id = str(uuid.uuid4())
    conflict_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            ConflictRow(
                id=conflict_id,
                project_id=pid,
                rule="missing_owner",
                severity="low",
                summary="seeded conflict 2",
                targets=[],
                detail={},
                fingerprint=f"rw6-test-{conflict_id}",
                status="open",
            )
        )
        await session.flush()
        session.add(
            DecisionRow(
                id=decision_id,
                conflict_id=conflict_id,
                project_id=pid,
                resolver_id=owner_id,
                option_index=0,
                custom_text=None,
                rationale="r",
                apply_actions=[],
                apply_outcome="ok",
                apply_detail={},
            )
        )

    await _login(client, "rw6_dec_outsider")
    r = await client.get(f"/api/decisions/{decision_id}")
    assert r.status_code == 403, r.text
    assert outsider_id != owner_id


@pytest.mark.asyncio
async def test_decision_detail_404_for_unknown_id(api_env):
    client, *_ = api_env
    await _register_and_login(client, "rw6_dec_404")
    await _login(client, "rw6_dec_404")
    r = await client.get("/api/decisions/does-not-exist")
    assert r.status_code == 404, r.text


# ---- /api/kb-items/:id wire-shape sanity --------------------------------


@pytest.mark.asyncio
async def test_kb_item_detail_wire_shape_for_fe_consumer(api_env):
    """Sanity check the field names the new /kb-items/:id FE page
    reads. test_kb_items.py covers access semantics; this case
    is the wire-shape canary.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw6_kb_owner")
    member_id = await _register_and_login(client, "rw6_kb_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )

    await _login(client, "rw6_kb_owner")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "RW6 sanity item",
            "content_md": "body",
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text
    item_id = r.json()["id"]

    r = await client.get(f"/api/kb-items/{item_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    for field in (
        "id",
        "project_id",
        "owner_user_id",
        "scope",
        "title",
        "content_md",
        "status",
        "source",
        "attachment",
        "created_at",
        "updated_at",
    ):
        assert field in body, (field, body)
    assert body["title"] == "RW6 sanity item"
    assert body["scope"] == "group"
