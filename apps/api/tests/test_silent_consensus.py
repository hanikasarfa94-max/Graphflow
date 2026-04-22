"""Phase 1.A silent-consensus tests.

Covers the four acceptance criteria from PLAN-v4.md Phase 1.A:

1. Scanner detects unanimous action on a seeded topic.
2. Ratification crystallizes a DecisionRow with correct lineage.
3. Dissent on the topic suppresses the proposal (or invalidates an
   existing pending one).
4. Rejection clears the row (status flips, no DecisionRow created).

Plus a membership-gating regression test so the owner / full-tier
ratify-reject gate doesn't silently open up.

Run with `-p no:randomly` — conftest boots api_env with shared state,
and a subset of test_collab tests are order-sensitive on the session
ordering. Test suite flake is pre-existing.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    AssignmentRepository,
    DecisionRepository,
    DecisionRow,
    DeliverableRow,
    DissentRepository,
    PlanRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRepository,
    RequirementRow,
    SilentConsensusRepository,
    SilentConsensusRow,
    StatusTransitionRepository,
    TaskRow,
    UserRepository,
    session_scope,
)


# ---- helpers -------------------------------------------------------------


async def _register(client, username: str) -> str:
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


async def _seed_user(maker, username: str) -> str:
    async with session_scope(maker) as session:
        u = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        return u.id


async def _mk_project(maker, title: str = "SilentConsensus") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _add_member(
    maker,
    pid: str,
    uid: str,
    *,
    role: str = "member",
    license_tier: str = "full",
) -> None:
    async with session_scope(maker) as session:
        row = await ProjectMemberRepository(session).add(
            project_id=pid, user_id=uid, role=role
        )
        row.license_tier = license_tier
        await session.flush()


async def _seed_requirement_and_deliverable(
    maker, pid: str, *, deliverable_title: str = "Checkout flow"
) -> tuple[str, str]:
    """Return (requirement_id, deliverable_id)."""
    async with session_scope(maker) as session:
        req = RequirementRow(
            id=str(uuid.uuid4()),
            project_id=pid,
            version=1,
            raw_text="Seeded requirement for silent-consensus tests.",
        )
        session.add(req)
        await session.flush()
        deliverable = DeliverableRow(
            id=str(uuid.uuid4()),
            project_id=pid,
            requirement_id=req.id,
            title=deliverable_title,
            kind="feature",
            sort_order=0,
            status="open",
        )
        session.add(deliverable)
        await session.flush()
        return req.id, deliverable.id


async def _seed_task(
    maker,
    *,
    project_id: str,
    requirement_id: str,
    deliverable_id: str,
    title: str,
    sort_order: int,
    status: str = "open",
) -> str:
    async with session_scope(maker) as session:
        row = TaskRow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            requirement_id=requirement_id,
            deliverable_id=deliverable_id,
            title=title,
            description="",
            assignee_role="backend",
            sort_order=sort_order,
            status=status,
        )
        session.add(row)
        await session.flush()
        return row.id


async def _assign_and_complete_task(
    maker,
    *,
    project_id: str,
    task_id: str,
    user_id: str,
) -> None:
    """Assign the task to `user_id`, flip it done, and record a status
    transition crediting the user. This is the canonical "member
    acted on a topic" signal the scanner looks for."""
    async with session_scope(maker) as session:
        await AssignmentRepository(session).set_assignment(
            project_id=project_id, task_id=task_id, user_id=user_id
        )
        task = (
            await session.execute(select(TaskRow).where(TaskRow.id == task_id))
        ).scalar_one()
        old = task.status
        task.status = "done"
        await session.flush()
        await StatusTransitionRepository(session).record(
            project_id=project_id,
            entity_kind="task",
            entity_id=task_id,
            old_status=old,
            new_status="done",
            changed_by_user_id=user_id,
        )


async def _seed_dissent(
    maker,
    *,
    decision_id: str,
    dissenter_user_id: str,
    stance_text: str = "disagree",
) -> str:
    async with session_scope(maker) as session:
        row = await DissentRepository(session).upsert(
            decision_id=decision_id,
            dissenter_user_id=dissenter_user_id,
            stance_text=stance_text,
        )
        return row.id


# ---- tests ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_scanner_detects_unanimous_action_on_seeded_topic(api_env):
    """(1) When 3 members each complete a task under the same
    deliverable, the scanner emits exactly one SilentConsensusRow
    with their ids and the right confidence shape.
    """
    from workgraph_api.main import app

    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "sc_owner_1")
    m1 = await _register(client, "sc_member_1_a")
    m2 = await _register(client, "sc_member_1_b")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")
    await _add_member(maker, pid, m1, role="member")
    await _add_member(maker, pid, m2, role="member")

    req_id, deliv_id = await _seed_requirement_and_deliverable(maker, pid)
    t_ids = []
    for i, uid in enumerate([owner, m1, m2]):
        tid = await _seed_task(
            maker,
            project_id=pid,
            requirement_id=req_id,
            deliverable_id=deliv_id,
            title=f"task-{i}",
            sort_order=i,
        )
        await _assign_and_complete_task(
            maker, project_id=pid, task_id=tid, user_id=uid
        )
        t_ids.append(tid)

    service = app.state.silent_consensus_service
    result = await service.scan(pid)
    assert result["ok"] is True
    assert len(result["created"]) == 1

    async with session_scope(maker) as session:
        rows = list(
            (
                await session.execute(
                    select(SilentConsensusRow).where(
                        SilentConsensusRow.project_id == pid
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    sc = rows[0]
    assert sc.status == "pending"
    assert set(sc.member_user_ids) == {owner, m1, m2}
    assert sc.confidence == pytest.approx(1.0)
    assert len(sc.supporting_action_ids) == 3
    assert all(
        a["kind"] == "task_status" and a["id"] in t_ids
        for a in sc.supporting_action_ids
    )
    assert "Checkout flow" in sc.topic_text

    # Running scan again is a no-op (pending dedupe by topic).
    result2 = await service.scan(pid)
    assert result2["created"] == []


@pytest.mark.asyncio
async def test_ratification_crystallizes_decision_with_lineage(api_env):
    """(2) Owner ratifies a pending SilentConsensusRow → a DecisionRow
    is created with rationale pointing back at the supporting action
    IDs, and the SilentConsensusRow flips to 'ratified'."""
    from workgraph_api.main import app

    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "sc_owner_2")
    m1 = await _register(client, "sc_member_2_a")
    m2 = await _register(client, "sc_member_2_b")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")
    await _add_member(maker, pid, m1, role="member")
    await _add_member(maker, pid, m2, role="member")

    req_id, deliv_id = await _seed_requirement_and_deliverable(maker, pid)
    for i, uid in enumerate([owner, m1, m2]):
        tid = await _seed_task(
            maker,
            project_id=pid,
            requirement_id=req_id,
            deliverable_id=deliv_id,
            title=f"task-{i}",
            sort_order=i,
        )
        await _assign_and_complete_task(
            maker, project_id=pid, task_id=tid, user_id=uid
        )

    service = app.state.silent_consensus_service
    await service.scan(pid)
    async with session_scope(maker) as session:
        rows = await SilentConsensusRepository(
            session
        ).list_pending_for_project(pid)
    assert len(rows) == 1
    sc_id = rows[0].id
    supporting = list(rows[0].supporting_action_ids)

    # Ratify via HTTP as the owner.
    await _login(client, "sc_owner_2")
    r = await client.post(
        f"/api/projects/{pid}/silent-consensus/{sc_id}/ratify",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    decision_id = body["decision_id"]

    async with session_scope(maker) as session:
        sc_row = await SilentConsensusRepository(session).get(sc_id)
        decision = await DecisionRepository(session).get(decision_id)
    assert sc_row.status == "ratified"
    assert sc_row.ratified_decision_id == decision_id
    assert sc_row.ratified_at is not None
    assert decision is not None
    assert decision.resolver_id == owner
    assert decision.project_id == pid
    # Lineage stored in rationale (no dedicated lineage column on
    # DecisionRow in v1).
    assert "Ratified silent consensus:" in decision.rationale
    for action in supporting:
        assert action["id"] in decision.rationale
    # Apply detail also carries the structured lineage for clean
    # programmatic access.
    assert decision.apply_detail.get("silent_consensus_id") == sc_id


@pytest.mark.asyncio
async def test_dissent_on_topic_suppresses_proposal(api_env):
    """(3) A dissent on a decision attached to the same deliverable
    suppresses any NEW silent-consensus proposal on that deliverable.
    The scanner sees the dissent, recognizes live disagreement, and
    refuses to broadcast false agreement.
    """
    from workgraph_api.main import app

    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "sc_owner_3")
    m1 = await _register(client, "sc_member_3_a")
    m2 = await _register(client, "sc_member_3_b")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")
    await _add_member(maker, pid, m1, role="member")
    await _add_member(maker, pid, m2, role="member")

    req_id, deliv_id = await _seed_requirement_and_deliverable(maker, pid)
    task_ids = []
    for i, uid in enumerate([owner, m1, m2]):
        tid = await _seed_task(
            maker,
            project_id=pid,
            requirement_id=req_id,
            deliverable_id=deliv_id,
            title=f"task-{i}",
            sort_order=i,
        )
        await _assign_and_complete_task(
            maker, project_id=pid, task_id=tid, user_id=uid
        )
        task_ids.append(tid)

    # Seed a decision that REFERENCES one of the tasks (and thus the
    # deliverable) so the scanner's suppression-by-dissent lookup can
    # find the linkage. Then dissent on that decision.
    async with session_scope(maker) as session:
        decision = await DecisionRepository(session).create(
            conflict_id=None,
            project_id=pid,
            resolver_id=owner,
            option_index=None,
            custom_text="drive the feature forward",
            rationale="seed to attach dissent",
            apply_actions=[{"kind": "assign_task", "task_id": task_ids[0]}],
            apply_outcome="advisory",
        )
        did = decision.id
    await _seed_dissent(maker, decision_id=did, dissenter_user_id=m1)

    service = app.state.silent_consensus_service
    result = await service.scan(pid)
    assert result["ok"] is True
    assert result["created"] == []

    async with session_scope(maker) as session:
        rows = await SilentConsensusRepository(
            session
        ).list_pending_for_project(pid)
    assert rows == []


@pytest.mark.asyncio
async def test_rejection_flips_status_without_creating_decision(api_env):
    """(4) Owner rejects a pending SilentConsensusRow → status flips
    to 'rejected', no DecisionRow is created."""
    from workgraph_api.main import app

    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "sc_owner_4")
    m1 = await _register(client, "sc_member_4_a")
    m2 = await _register(client, "sc_member_4_b")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")
    await _add_member(maker, pid, m1, role="member")
    await _add_member(maker, pid, m2, role="member")

    req_id, deliv_id = await _seed_requirement_and_deliverable(maker, pid)
    for i, uid in enumerate([owner, m1, m2]):
        tid = await _seed_task(
            maker,
            project_id=pid,
            requirement_id=req_id,
            deliverable_id=deliv_id,
            title=f"task-{i}",
            sort_order=i,
        )
        await _assign_and_complete_task(
            maker, project_id=pid, task_id=tid, user_id=uid
        )

    service = app.state.silent_consensus_service
    await service.scan(pid)
    async with session_scope(maker) as session:
        rows = await SilentConsensusRepository(
            session
        ).list_pending_for_project(pid)
    assert len(rows) == 1
    sc_id = rows[0].id

    # Count decisions before reject.
    async with session_scope(maker) as session:
        before = list(
            (
                await session.execute(
                    select(DecisionRow).where(DecisionRow.project_id == pid)
                )
            )
            .scalars()
            .all()
        )
    before_count = len(before)

    await _login(client, "sc_owner_4")
    r = await client.post(
        f"/api/projects/{pid}/silent-consensus/{sc_id}/reject",
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True

    async with session_scope(maker) as session:
        sc_row = await SilentConsensusRepository(session).get(sc_id)
        after = list(
            (
                await session.execute(
                    select(DecisionRow).where(DecisionRow.project_id == pid)
                )
            )
            .scalars()
            .all()
        )
    assert sc_row.status == "rejected"
    assert sc_row.ratified_decision_id is None
    assert len(after) == before_count


@pytest.mark.asyncio
async def test_non_owner_cannot_ratify_or_reject(api_env):
    """Regression guard — ratify / reject are owner + full-tier only.
    A plain member gets 403 on both endpoints."""
    from workgraph_api.main import app

    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _register(client, "sc_owner_5")
    m1 = await _register(client, "sc_member_5_a")
    m2 = await _register(client, "sc_member_5_b")
    await _add_member(maker, pid, owner, role="owner", license_tier="full")
    await _add_member(maker, pid, m1, role="member")
    await _add_member(maker, pid, m2, role="member")

    req_id, deliv_id = await _seed_requirement_and_deliverable(maker, pid)
    for i, uid in enumerate([owner, m1, m2]):
        tid = await _seed_task(
            maker,
            project_id=pid,
            requirement_id=req_id,
            deliverable_id=deliv_id,
            title=f"task-{i}",
            sort_order=i,
        )
        await _assign_and_complete_task(
            maker, project_id=pid, task_id=tid, user_id=uid
        )

    service = app.state.silent_consensus_service
    await service.scan(pid)
    async with session_scope(maker) as session:
        rows = await SilentConsensusRepository(
            session
        ).list_pending_for_project(pid)
    sc_id = rows[0].id

    # Log in as a plain member (not the owner).
    await _login(client, "sc_member_5_a")
    r1 = await client.post(
        f"/api/projects/{pid}/silent-consensus/{sc_id}/ratify",
    )
    assert r1.status_code == 403
    r2 = await client.post(
        f"/api/projects/{pid}/silent-consensus/{sc_id}/reject",
    )
    assert r2.status_code == 403

    # But the member CAN list pending proposals.
    r3 = await client.get(f"/api/projects/{pid}/silent-consensus")
    assert r3.status_code == 200
    assert len(r3.json()["proposals"]) == 1
