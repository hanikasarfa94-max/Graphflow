"""CommitmentService tests (Sprint 2a).

Covers service-level contracts without going through HTTP:
  * create with minimum fields
  * create with scope anchor validates membership-in-project
  * create rejects unknown scope kind
  * create rejects invalid headline length
  * set_status cycles through open → met → open → withdrawn with
    correct `resolved_at` stamping
  * list filters by status

HTTP-layer tests live separately; this file stays focused on the
service semantics so the backend can be iterated without router
churn.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from workgraph_api.services import (
    CommitmentService,
    CommitmentValidationError,
)
from workgraph_domain import EventBus
from workgraph_persistence import (
    DeliverableRow,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRow,
    UserRepository,
    session_scope,
)


def _uid() -> str:
    return str(uuid4())


async def _mk_project(maker, title: str = "commit test") -> str:
    async with session_scope(maker) as session:
        pid = _uid()
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _mk_requirement(maker, project_id: str) -> str:
    async with session_scope(maker) as session:
        rid = _uid()
        session.add(
            RequirementRow(
                id=rid,
                project_id=project_id,
                version=1,
                raw_text="stub",
                parse_outcome="ok",
            )
        )
        await session.flush()
    return rid


async def _mk_user(maker, username: str) -> str:
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        return user.id


async def _add_member(maker, project_id: str, user_id: str) -> None:
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id
        )


async def _mk_deliverable(maker, project_id: str, requirement_id: str) -> str:
    async with session_scope(maker) as session:
        did = _uid()
        session.add(
            DeliverableRow(
                id=did,
                project_id=project_id,
                requirement_id=requirement_id,
                sort_order=0,
                title="ship season 1",
            )
        )
        await session.flush()
    return did


@pytest.mark.asyncio
async def test_create_minimum_fields(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(maker, "cm_min")
    await _add_member(maker, pid, uid)

    service = CommitmentService(maker, EventBus(maker))
    payload = await service.create(
        project_id=pid,
        actor_user_id=uid,
        headline="Ship Stellar Drift by Apr 30",
    )
    assert payload["id"]
    assert payload["project_id"] == pid
    assert payload["created_by_user_id"] == uid
    assert payload["owner_user_id"] == uid  # defaults to creator
    assert payload["status"] == "open"
    assert payload["resolved_at"] is None
    assert payload["headline"] == "Ship Stellar Drift by Apr 30"


@pytest.mark.asyncio
async def test_create_with_scope_anchor_validates_in_project(api_env):
    """A commitment scoped to a deliverable from PROJECT A cannot be
    created on PROJECT B — the anchor must live in the same project."""
    _, maker, *_ = api_env
    pid_a = await _mk_project(maker, "A")
    pid_b = await _mk_project(maker, "B")
    req_a = await _mk_requirement(maker, pid_a)
    del_a = await _mk_deliverable(maker, pid_a, req_a)
    uid = await _mk_user(maker, "cm_scope")
    await _add_member(maker, pid_a, uid)
    await _add_member(maker, pid_b, uid)

    service = CommitmentService(maker, EventBus(maker))

    # Anchor in same project — succeeds.
    payload = await service.create(
        project_id=pid_a,
        actor_user_id=uid,
        headline="Ship deliverable A by Apr 30",
        scope_ref_kind="deliverable",
        scope_ref_id=del_a,
    )
    assert payload["scope_ref_kind"] == "deliverable"
    assert payload["scope_ref_id"] == del_a

    # Anchor in cross-project — rejected.
    with pytest.raises(CommitmentValidationError):
        await service.create(
            project_id=pid_b,
            actor_user_id=uid,
            headline="Cross-anchor should fail",
            scope_ref_kind="deliverable",
            scope_ref_id=del_a,
        )


@pytest.mark.asyncio
async def test_create_rejects_unknown_scope_kind(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(maker, "cm_badkind")
    await _add_member(maker, pid, uid)

    service = CommitmentService(maker, EventBus(maker))
    with pytest.raises(CommitmentValidationError):
        await service.create(
            project_id=pid,
            actor_user_id=uid,
            headline="Bad scope kind",
            scope_ref_kind="nonexistent",
            scope_ref_id=_uid(),
        )


@pytest.mark.asyncio
async def test_create_rejects_invalid_headline(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(maker, "cm_bad_headline")
    await _add_member(maker, pid, uid)

    service = CommitmentService(maker, EventBus(maker))
    for bad in ("", "  ", "no", "x" * 501):
        with pytest.raises(CommitmentValidationError):
            await service.create(
                project_id=pid,
                actor_user_id=uid,
                headline=bad,
            )


@pytest.mark.asyncio
async def test_status_lifecycle_stamps_resolved_at(api_env):
    """Terminal states stamp resolved_at; reverting to open clears it."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(maker, "cm_status")
    await _add_member(maker, pid, uid)

    service = CommitmentService(maker, EventBus(maker))
    payload = await service.create(
        project_id=pid,
        actor_user_id=uid,
        headline="Ship season 1 on time",
    )
    cid = payload["id"]

    # open → met
    met = await service.set_status(
        commitment_id=cid, actor_user_id=uid, status="met"
    )
    assert met is not None
    assert met["status"] == "met"
    assert met["resolved_at"] is not None

    # met → open (reset)
    reopen = await service.set_status(
        commitment_id=cid, actor_user_id=uid, status="open"
    )
    assert reopen is not None
    assert reopen["status"] == "open"
    assert reopen["resolved_at"] is None

    # open → withdrawn
    wd = await service.set_status(
        commitment_id=cid, actor_user_id=uid, status="withdrawn"
    )
    assert wd is not None
    assert wd["status"] == "withdrawn"
    assert wd["resolved_at"] is not None


@pytest.mark.asyncio
async def test_list_filters_by_status(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(maker, "cm_list")
    await _add_member(maker, pid, uid)
    service = CommitmentService(maker, EventBus(maker))

    c1 = await service.create(
        project_id=pid, actor_user_id=uid, headline="open promise one"
    )
    await service.create(
        project_id=pid, actor_user_id=uid, headline="open promise two"
    )
    await service.set_status(
        commitment_id=c1["id"], actor_user_id=uid, status="met"
    )

    open_only = await service.list_for_project(
        project_id=pid, status="open"
    )
    met_only = await service.list_for_project(
        project_id=pid, status="met"
    )
    both = await service.list_for_project(project_id=pid)

    assert len(open_only) == 1
    assert len(met_only) == 1
    assert len(both) == 2


@pytest.mark.asyncio
async def test_set_status_unknown_returns_none(api_env):
    _, maker, *_ = api_env
    service = CommitmentService(maker, EventBus(maker))
    result = await service.set_status(
        commitment_id=_uid(), actor_user_id="whatever", status="met"
    )
    assert result is None


@pytest.mark.asyncio
async def test_set_status_rejects_unknown_status(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _mk_user(maker, "cm_badstatus")
    await _add_member(maker, pid, uid)
    service = CommitmentService(maker, EventBus(maker))
    payload = await service.create(
        project_id=pid, actor_user_id=uid, headline="status test"
    )
    with pytest.raises(CommitmentValidationError):
        await service.set_status(
            commitment_id=payload["id"],
            actor_user_id=uid,
            status="nonexistent",
        )
