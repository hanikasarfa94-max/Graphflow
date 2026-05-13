"""RW-7 — Task detail endpoint tests.

Covers the singleton GET /api/tasks/:id added in this slice.

The list endpoint (GET /api/tasks) is already covered by existing
task_progress tests; this file targets the new singleton's
membership gate, 404 behavior, and wire shape parity with the
list endpoint serializer.
"""
from __future__ import annotations

import uuid

import pytest

from workgraph_persistence import (
    PlanRepository,
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
        session.add(ProjectRow(id=pid, title="RW7 Project"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
    return pid


async def _mk_personal_task(maker, *, project_id: str, owner_id: str) -> str:
    async with session_scope(maker) as session:
        row = await PlanRepository(session).create_personal_task(
            project_id=project_id,
            owner_user_id=owner_id,
            title="RW7 personal task",
            description="seeded",
            source_message_id=None,
            estimate_hours=4,
            assignee_role="backend",
        )
    return row.id


@pytest.mark.asyncio
async def test_singleton_returns_wire_fields_fe_consumer_uses(api_env):
    """The FE detail page reads exactly these fields. Asserting
    presence catches schema drift before the page renders blank.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw7_task_owner")
    member_id = await _register_and_login(client, "rw7_task_member")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    task_id = await _mk_personal_task(
        maker, project_id=pid, owner_id=owner_id
    )

    await _login(client, "rw7_task_owner")
    r = await client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "task" in body, body
    task = body["task"]
    for field in (
        "id",
        "scope_id",
        "project_id",
        "title",
        "description",
        "scope",
        "status",
        "owner_user_id",
        "requirement_id",
        "source_message_id",
        "assignee_role",
        "estimate_hours",
        "created_at",
    ):
        assert field in task, (field, task)
    assert task["id"] == task_id
    assert task["title"] == "RW7 personal task"
    assert task["scope_id"] == pid
    assert task["project_id"] == pid
    assert task["owner_user_id"] == owner_id
    assert task["assignee_role"] == "backend"
    assert task["estimate_hours"] == 4


@pytest.mark.asyncio
async def test_singleton_403_for_non_scope_member(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw7_task_owner_403")
    member_id = await _register_and_login(client, "rw7_task_member_403")
    outsider_id = await _register_and_login(client, "rw7_task_outsider")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    task_id = await _mk_personal_task(
        maker, project_id=pid, owner_id=owner_id
    )

    await _login(client, "rw7_task_outsider")
    r = await client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 403, r.text
    assert outsider_id != owner_id


@pytest.mark.asyncio
async def test_singleton_404_for_unknown_id(api_env):
    client, *_ = api_env
    await _register_and_login(client, "rw7_task_404")
    await _login(client, "rw7_task_404")
    r = await client.get("/api/tasks/does-not-exist")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_singleton_matches_list_serializer(api_env):
    """The singleton's `task` field uses the same _serialize_task
    output as each row in the list's `tasks[]` array. Drift between
    the two would force the FE to maintain two parallel renderers,
    so we lock the shapes together here.
    """
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "rw7_task_owner_parity")
    member_id = await _register_and_login(client, "rw7_task_member_parity")
    pid = await _mk_project_with_members(
        maker, owner_id=owner_id, member_id=member_id
    )
    task_id = await _mk_personal_task(
        maker, project_id=pid, owner_id=owner_id
    )

    await _login(client, "rw7_task_owner_parity")
    singleton = (await client.get(f"/api/tasks/{task_id}")).json()["task"]

    list_r = await client.get("/api/tasks?view=my_tasks")
    list_rows = list_r.json()["tasks"]
    row = next(r for r in list_rows if r["id"] == task_id)

    # Same field names + same values.
    assert set(singleton.keys()) == set(row.keys()), (
        sorted(singleton.keys()),
        sorted(row.keys()),
    )
    for k in singleton.keys():
        assert singleton[k] == row[k], (k, singleton[k], row[k])
