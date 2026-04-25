"""Phase U — task status self-reports + leader scoring tests."""
from __future__ import annotations

import uuid

import pytest

from workgraph_persistence import (
    AssignmentRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRow,
    TaskRow,
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


async def _seed_project_with_task(maker, *, owner_id: str, assignee_id: str):
    """Insert a project + requirement + task + active assignment."""
    pid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="Stellar Drift"))
        session.add(
            RequirementRow(id=rid, project_id=pid, raw_text="x", version=1)
        )
        session.add(
            TaskRow(
                id=tid,
                project_id=pid,
                requirement_id=rid,
                title="Wire OTP",
                description="hand-rolled OTP service",
                status="open",
                sort_order=0,
            )
        )
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=assignee_id, role="member"
        )
        await AssignmentRepository(session).set_assignment(
            project_id=pid, task_id=tid, user_id=assignee_id
        )
    return pid, tid


# ---- 1. status updates --------------------------------------------------


@pytest.mark.asyncio
async def test_assignee_can_walk_through_status_states(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_1")
    assignee_id = await _register_and_login(client, "tp_assignee_1")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_assignee_1")
    r = await client.post(
        f"/api/tasks/{tid}/status",
        json={"new_status": "in_progress", "note": "started"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"

    r = await client.post(
        f"/api/tasks/{tid}/status",
        json={"new_status": "done", "note": "shipped to staging"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "done"


@pytest.mark.asyncio
async def test_invalid_transition_rejected(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_2")
    assignee_id = await _register_and_login(client, "tp_assignee_2")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_assignee_2")
    # open → done direct (must mark in_progress first).
    r = await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "done"}
    )
    assert r.status_code == 400
    assert r.json()["message"] == "invalid_transition"


@pytest.mark.asyncio
async def test_non_assignee_non_owner_forbidden(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_3")
    assignee_id = await _register_and_login(client, "tp_assignee_3")
    intruder_id = await _register_and_login(client, "tp_intruder_3")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_intruder_3")
    r = await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "in_progress"}
    )
    assert r.status_code == 403
    assert r.json()["message"] == "forbidden"


@pytest.mark.asyncio
async def test_project_owner_can_force_status(api_env):
    """Owner can intervene if assignee ghosts."""
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_4")
    assignee_id = await _register_and_login(client, "tp_assignee_4")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_owner_4")
    r = await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "canceled"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"


# ---- 2. scoring ---------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_scores_done_task(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_5")
    assignee_id = await _register_and_login(client, "tp_assignee_5")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    # Assignee marks done.
    await _login(client, "tp_assignee_5")
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "in_progress"}
    )
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "done"}
    )

    # Owner scores good.
    await _login(client, "tp_owner_5")
    r = await client.post(
        f"/api/tasks/{tid}/score",
        json={"quality": "good", "feedback": "shipped clean"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["quality"] == "good"
    assert r.json()["assignee_user_id"] == assignee_id

    # Re-score updates the same row (upsert).
    r = await client.post(
        f"/api/tasks/{tid}/score",
        json={"quality": "ok", "feedback": "actually a few rough edges"},
    )
    assert r.status_code == 200
    assert r.json()["quality"] == "ok"
    assert r.json()["created"] is False


@pytest.mark.asyncio
async def test_cannot_score_unfinished_task(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_6")
    assignee_id = await _register_and_login(client, "tp_assignee_6")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_owner_6")
    r = await client.post(
        f"/api/tasks/{tid}/score", json={"quality": "good"}
    )
    assert r.status_code == 400
    assert r.json()["message"] == "not_done"


@pytest.mark.asyncio
async def test_non_owner_cannot_score(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_7")
    assignee_id = await _register_and_login(client, "tp_assignee_7")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_assignee_7")
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "in_progress"}
    )
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "done"}
    )

    # Assignee tries to score themselves.
    r = await client.post(
        f"/api/tasks/{tid}/score", json={"quality": "good"}
    )
    assert r.status_code == 403
    assert r.json()["message"] == "forbidden"


# ---- 3. history ---------------------------------------------------------


@pytest.mark.asyncio
async def test_history_shows_status_timeline_and_score(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_8")
    assignee_id = await _register_and_login(client, "tp_assignee_8")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_assignee_8")
    await client.post(
        f"/api/tasks/{tid}/status",
        json={"new_status": "in_progress", "note": "started"},
    )
    await client.post(
        f"/api/tasks/{tid}/status",
        json={"new_status": "done", "note": "complete"},
    )
    await _login(client, "tp_owner_8")
    await client.post(
        f"/api/tasks/{tid}/score",
        json={"quality": "good", "feedback": "ok"},
    )

    r = await client.get(f"/api/tasks/{tid}/history")
    assert r.status_code == 200
    data = r.json()
    assert data["current_status"] == "done"
    assert len(data["updates"]) == 2
    assert data["updates"][0]["new_status"] == "in_progress"
    assert data["updates"][1]["new_status"] == "done"
    assert data["score"]["quality"] == "good"
    assert data["score"]["feedback"] == "ok"


# ---- 4. perf integration ------------------------------------------------


@pytest.mark.asyncio
async def test_perf_includes_task_quality_payload(api_env):
    """A scored task surfaces in /team/perf via task_quality."""
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_perf_owner")
    assignee_id = await _register_and_login(client, "tp_perf_assignee")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_perf_assignee")
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "in_progress"}
    )
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "done"}
    )
    await _login(client, "tp_perf_owner")
    await client.post(
        f"/api/tasks/{tid}/score", json={"quality": "good"}
    )

    r = await client.get(f"/api/projects/{pid}/team/perf")
    assert r.status_code == 200, r.text
    # team_perf returns the list directly, not wrapped in {"members": ...}.
    members = r.json()
    assignee_row = next(m for m in members if m["user_id"] == assignee_id)
    assert assignee_row["task_quality"]["good"] == 1
    assert assignee_row["task_quality"]["total"] == 1
    assert assignee_row["task_quality"]["quality_index"] == 1.0
