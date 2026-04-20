"""SimulationService tests — counterfactual blast-radius (Sprint new).

Covers:
  * drop-a-task with no downstream: only the task itself is reported
  * drop-a-task with linear downstream A → B → C: A dropped, B + C
    orphan, dep-chain traced transitively
  * fork in the chain: A → B, A → C, D → B. Dropping A orphans only
    C (B still has D upstream)
  * deliverable exposure: dropping the SOLE task of a deliverable
    exposes it; dropping one of many does not
  * milestone slip: any related_task_id in removed-set flips the
    milestone
  * commitment risk: commitments scoped to affected entities surface
  * unknown simulation kind → SimulationError
  * task not in project → SimulationError
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from workgraph_api.services import SimulationError, SimulationService
from workgraph_persistence import (
    CommitmentRepository,
    DeliverableRow,
    MilestoneRow,
    ProjectRow,
    RequirementRow,
    TaskDependencyRow,
    TaskRow,
    session_scope,
)


def _uid() -> str:
    return str(uuid4())


async def _mk_project(maker) -> tuple[str, str]:
    pid = _uid()
    req_id = _uid()
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="sim"))
        session.add(
            RequirementRow(
                id=req_id,
                project_id=pid,
                version=1,
                raw_text="stub",
                parse_outcome="ok",
            )
        )
        await session.flush()
    return pid, req_id


async def _mk_task(
    maker,
    pid: str,
    req_id: str,
    *,
    title: str,
    sort_order: int,
    deliverable_id: str | None = None,
) -> str:
    tid = _uid()
    async with session_scope(maker) as session:
        session.add(
            TaskRow(
                id=tid,
                project_id=pid,
                requirement_id=req_id,
                deliverable_id=deliverable_id,
                sort_order=sort_order,
                title=title,
            )
        )
        await session.flush()
    return tid


async def _mk_dep(maker, pid: str, req_id: str, frm: str, to: str) -> None:
    async with session_scope(maker) as session:
        session.add(
            TaskDependencyRow(
                id=_uid(),
                requirement_id=req_id,
                from_task_id=frm,
                to_task_id=to,
            )
        )
        await session.flush()


async def _mk_deliverable(
    maker, pid: str, req_id: str, *, title: str, sort_order: int
) -> str:
    did = _uid()
    async with session_scope(maker) as session:
        session.add(
            DeliverableRow(
                id=did,
                project_id=pid,
                requirement_id=req_id,
                sort_order=sort_order,
                title=title,
            )
        )
        await session.flush()
    return did


async def _mk_milestone(
    maker,
    pid: str,
    req_id: str,
    *,
    title: str,
    related: list[str],
    sort_order: int = 0,
) -> str:
    """Milestones have UniqueConstraint(requirement_id, sort_order),
    so callers creating two milestones under the same requirement MUST
    pass distinct sort_order values."""
    mid = _uid()
    async with session_scope(maker) as session:
        session.add(
            MilestoneRow(
                id=mid,
                project_id=pid,
                requirement_id=req_id,
                sort_order=sort_order,
                title=title,
                related_task_ids=related,
            )
        )
        await session.flush()
    return mid


@pytest.mark.asyncio
async def test_drop_task_with_no_downstream_reports_only_itself(api_env):
    _, maker, *_ = api_env
    pid, req = await _mk_project(maker)
    t = await _mk_task(maker, pid, req, title="alone", sort_order=0)

    svc = SimulationService(maker)
    result = await svc.simulate(
        project_id=pid,
        kind="drop_task",
        entity_kind="task",
        entity_id=t,
    )
    payload = result.to_dict()
    assert [d["id"] for d in payload["dropped"]] == [t]
    assert payload["orphan_tasks"] == []
    assert payload["total_blast_radius"] == 0


@pytest.mark.asyncio
async def test_drop_task_orphans_transitive_downstream(api_env):
    """Linear chain A → B → C. Drop A → both B and C orphan."""
    _, maker, *_ = api_env
    pid, req = await _mk_project(maker)
    a = await _mk_task(maker, pid, req, title="A", sort_order=0)
    b = await _mk_task(maker, pid, req, title="B", sort_order=1)
    c = await _mk_task(maker, pid, req, title="C", sort_order=2)
    await _mk_dep(maker, pid, req, a, b)
    await _mk_dep(maker, pid, req, b, c)

    svc = SimulationService(maker)
    result = await svc.simulate(
        project_id=pid,
        kind="drop_task",
        entity_kind="task",
        entity_id=a,
    )
    payload = result.to_dict()
    orphan_ids = {o["id"] for o in payload["orphan_tasks"]}
    assert orphan_ids == {b, c}


@pytest.mark.asyncio
async def test_fork_with_alternate_upstream_does_not_orphan(api_env):
    """A → B, D → B, A → C. Drop A → C orphans; B does NOT (still has D)."""
    _, maker, *_ = api_env
    pid, req = await _mk_project(maker)
    a = await _mk_task(maker, pid, req, title="A", sort_order=0)
    b = await _mk_task(maker, pid, req, title="B", sort_order=1)
    c = await _mk_task(maker, pid, req, title="C", sort_order=2)
    d = await _mk_task(maker, pid, req, title="D", sort_order=3)
    await _mk_dep(maker, pid, req, a, b)
    await _mk_dep(maker, pid, req, a, c)
    await _mk_dep(maker, pid, req, d, b)  # B has a live upstream after A drops

    svc = SimulationService(maker)
    result = await svc.simulate(
        project_id=pid,
        kind="drop_task",
        entity_kind="task",
        entity_id=a,
    )
    orphan_ids = {o["id"] for o in result.to_dict()["orphan_tasks"]}
    assert c in orphan_ids
    assert b not in orphan_ids


@pytest.mark.asyncio
async def test_deliverable_exposed_only_when_all_tasks_removed(api_env):
    _, maker, *_ = api_env
    pid, req = await _mk_project(maker)
    del_solo = await _mk_deliverable(maker, pid, req, title="solo", sort_order=0)
    del_fat = await _mk_deliverable(maker, pid, req, title="fat", sort_order=1)
    solo_t = await _mk_task(
        maker, pid, req, title="solo-t", sort_order=0, deliverable_id=del_solo
    )
    fat_t1 = await _mk_task(
        maker, pid, req, title="fat-1", sort_order=1, deliverable_id=del_fat
    )
    await _mk_task(
        maker, pid, req, title="fat-2", sort_order=2, deliverable_id=del_fat
    )

    svc = SimulationService(maker)
    # Dropping the solo task exposes its deliverable (100% coverage lost).
    r_solo = await svc.simulate(
        project_id=pid,
        kind="drop_task",
        entity_kind="task",
        entity_id=solo_t,
    )
    exposed = {d["id"] for d in r_solo.to_dict()["exposed_deliverables"]}
    assert exposed == {del_solo}

    # Dropping one of two tasks on the fat deliverable does NOT expose it.
    r_fat = await svc.simulate(
        project_id=pid,
        kind="drop_task",
        entity_kind="task",
        entity_id=fat_t1,
    )
    assert r_fat.to_dict()["exposed_deliverables"] == []


@pytest.mark.asyncio
async def test_milestone_slips_when_related_task_removed(api_env):
    _, maker, *_ = api_env
    pid, req = await _mk_project(maker)
    t = await _mk_task(maker, pid, req, title="anchor", sort_order=0)
    unrelated = await _mk_task(maker, pid, req, title="unrelated", sort_order=1)
    m = await _mk_milestone(
        maker, pid, req, title="cert", related=[t], sort_order=0
    )
    await _mk_milestone(
        maker, pid, req, title="other", related=[unrelated], sort_order=1
    )

    svc = SimulationService(maker)
    result = await svc.simulate(
        project_id=pid,
        kind="drop_task",
        entity_kind="task",
        entity_id=t,
    )
    slipping_ids = {m["id"] for m in result.to_dict()["slipping_milestones"]}
    assert slipping_ids == {m}


@pytest.mark.asyncio
async def test_commitment_anchored_to_affected_entity_surfaces(api_env):
    _, maker, *_ = api_env
    pid, req = await _mk_project(maker)
    t = await _mk_task(maker, pid, req, title="anchor", sort_order=0)

    # Seed a commitment anchored to this task. We need a user to own
    # it; reuse the simplest path: insert a user row directly.
    from workgraph_persistence import UserRow

    uid = _uid()
    async with session_scope(maker) as session:
        session.add(
            UserRow(
                id=uid,
                username="sim_owner",
                display_name="sim owner",
                password_hash="x",
                password_salt="y",
            )
        )
        await session.flush()
        await CommitmentRepository(session).create(
            project_id=pid,
            created_by_user_id=uid,
            owner_user_id=uid,
            headline="Ship this task",
            scope_ref_kind="task",
            scope_ref_id=t,
        )

    svc = SimulationService(maker)
    result = await svc.simulate(
        project_id=pid,
        kind="drop_task",
        entity_kind="task",
        entity_id=t,
    )
    assert len(result.to_dict()["at_risk_commitments"]) == 1


@pytest.mark.asyncio
async def test_unknown_kind_raises(api_env):
    _, maker, *_ = api_env
    pid, req = await _mk_project(maker)
    t = await _mk_task(maker, pid, req, title="a", sort_order=0)
    svc = SimulationService(maker)
    with pytest.raises(SimulationError):
        await svc.simulate(
            project_id=pid,
            kind="rename",  # not supported
            entity_kind="task",
            entity_id=t,
        )


@pytest.mark.asyncio
async def test_task_not_in_project_raises(api_env):
    _, maker, *_ = api_env
    pid, _ = await _mk_project(maker)
    svc = SimulationService(maker)
    with pytest.raises(SimulationError):
        await svc.simulate(
            project_id=pid,
            kind="drop_task",
            entity_kind="task",
            entity_id=_uid(),  # never inserted
        )
