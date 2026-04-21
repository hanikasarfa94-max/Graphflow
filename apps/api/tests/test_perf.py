"""Team performance panel — project-admin observability endpoint.

Gate: role == 'owner' AND license_tier == 'full'. Every other
combination (member, observer, task_scoped owner) returns 403.

The counts are plain DB aggregates, scoped to project_id, so the
"counts match direct queries" test seeds one decision, one risk,
one assignment and walks the ORM to verify the router echoes them.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from workgraph_persistence import (
    AssignmentRow,
    DecisionRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRow,
    RiskRow,
    TaskRow,
    UserRepository,
    session_scope,
)


async def _register(
    client: AsyncClient, username: str, password: str = "hunter22"
) -> str:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _login(client: AsyncClient, username: str, password="hunter22"):
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text


async def _seed_user(maker, username: str) -> str:
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        return user.id


async def _mk_project(maker, title="Perf") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _add_member(
    maker, pid, uid, *, role="member", license_tier="full"
):
    async with session_scope(maker) as session:
        row = await ProjectMemberRepository(session).add(
            project_id=pid, user_id=uid, role=role
        )
        row.license_tier = license_tier
        await session.flush()


async def _seed_requirement(maker, pid) -> str:
    rid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            RequirementRow(
                id=rid, project_id=pid, version=1, raw_text="r"
            )
        )
        await session.flush()
    return rid


async def _seed_task(maker, pid, req_id, *, status="open") -> str:
    tid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            TaskRow(
                id=tid,
                project_id=pid,
                requirement_id=req_id,
                title="t",
                status=status,
                sort_order=_unique_sort_order(),
            )
        )
        await session.flush()
    return tid


_SORT_COUNTER = {"n": 0}


def _unique_sort_order() -> int:
    _SORT_COUNTER["n"] += 1
    return _SORT_COUNTER["n"]


async def _seed_risk(maker, pid, req_id, *, status="open") -> str:
    rid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            RiskRow(
                id=rid,
                project_id=pid,
                requirement_id=req_id,
                title="risk",
                status=status,
                sort_order=_unique_sort_order(),
            )
        )
        await session.flush()
    return rid


async def _seed_assignment(maker, pid, tid, uid) -> str:
    aid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            AssignmentRow(
                id=aid,
                project_id=pid,
                task_id=tid,
                user_id=uid,
                active=True,
            )
        )
        await session.flush()
    return aid


async def _seed_decision(maker, pid, resolver_id):
    async with session_scope(maker) as session:
        row = await DecisionRepository(session).create(
            conflict_id=None,
            project_id=pid,
            resolver_id=resolver_id,
            option_index=None,
            custom_text="c",
            rationale="t",
            apply_actions=[],
        )
        return row.id


# ---- tests ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_sees_all_members_with_counts(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    req_id = await _seed_requirement(maker, pid)

    owner_id = await _register(client, "perf_owner")
    member_id = await _seed_user(maker, "perf_member")
    await _add_member(maker, pid, owner_id, role="owner", license_tier="full")
    await _add_member(maker, pid, member_id, role="member")

    # Seed activity across both members so each row is non-trivial.
    await _seed_decision(maker, pid, owner_id)
    await _seed_decision(maker, pid, member_id)
    t1 = await _seed_task(maker, pid, req_id, status="done")
    await _seed_assignment(maker, pid, t1, member_id)
    await _seed_risk(maker, pid, req_id, status="open")

    await _login(client, "perf_owner")
    r = await client.get(f"/api/projects/{pid}/team/perf")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 2
    by_uid = {row["user_id"]: row for row in body}
    assert by_uid[owner_id]["role_in_project"] == "owner"
    assert by_uid[owner_id]["decisions_made"]["count"] == 1
    assert by_uid[owner_id]["risks_owned"]["count"] == 1
    assert by_uid[member_id]["decisions_made"]["count"] == 1
    assert by_uid[member_id]["tasks_completed"]["count"] == 1
    assert by_uid[member_id]["risks_owned"]["count"] == 0


@pytest.mark.asyncio
async def test_non_admin_member_forbidden(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _seed_user(maker, "perf_own_seed")
    member_id = await _register(client, "perf_plain_member")
    await _add_member(maker, pid, owner_id, role="owner", license_tier="full")
    await _add_member(maker, pid, member_id, role="member")

    r = await client.get(f"/api/projects/{pid}/team/perf")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_observer_tier_forbidden(api_env):
    """An owner-role member with observer license still can't see
    the panel — both gates must pass."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "perf_observer_owner")
    await _add_member(
        maker, pid, owner_id, role="owner", license_tier="observer"
    )

    r = await client.get(f"/api/projects/{pid}/team/perf")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_counts_match_direct_db_queries(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    req_id = await _seed_requirement(maker, pid)

    owner_id = await _register(client, "perf_counts_owner")
    other_id = await _seed_user(maker, "perf_counts_other")
    await _add_member(maker, pid, owner_id, role="owner", license_tier="full")
    await _add_member(maker, pid, other_id, role="member")

    # Scenario: one decision by `other`, one risk on this project,
    # one completed assignment for `other`.
    dec_id = await _seed_decision(maker, pid, other_id)
    risk_id = await _seed_risk(maker, pid, req_id, status="open")
    task_id = await _seed_task(maker, pid, req_id, status="done")
    await _seed_assignment(maker, pid, task_id, other_id)

    await _login(client, "perf_counts_owner")
    r = await client.get(f"/api/projects/{pid}/team/perf")
    assert r.status_code == 200
    body = r.json()
    by_uid = {row["user_id"]: row for row in body}

    # Verify each figure against the ORM directly.
    async with session_scope(maker) as session:
        from workgraph_persistence import DecisionRow

        dec_rows = list(
            (
                await session.execute(
                    select(DecisionRow.id).where(
                        DecisionRow.project_id == pid,
                        DecisionRow.resolver_id == other_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        risk_rows = list(
            (
                await session.execute(
                    select(RiskRow.id).where(
                        RiskRow.project_id == pid,
                        RiskRow.status == "open",
                    )
                )
            )
            .scalars()
            .all()
        )
        task_rows = list(
            (
                await session.execute(
                    select(TaskRow.id)
                    .join(AssignmentRow, AssignmentRow.task_id == TaskRow.id)
                    .where(TaskRow.project_id == pid)
                    .where(TaskRow.status == "done")
                    .where(AssignmentRow.user_id == other_id)
                )
            )
            .scalars()
            .all()
        )

    assert by_uid[other_id]["decisions_made"]["count"] == len(dec_rows) == 1
    assert dec_id in by_uid[other_id]["decisions_made"]["ids"]
    # Owner is the member credited for open risks on this project.
    assert by_uid[owner_id]["risks_owned"]["count"] == len(risk_rows) == 1
    assert risk_id in by_uid[owner_id]["risks_owned"]["ids"]
    assert by_uid[other_id]["risks_owned"]["count"] == 0
    assert by_uid[other_id]["tasks_completed"]["count"] == len(task_rows) == 1
    assert task_id in by_uid[other_id]["tasks_completed"]["ids"]
