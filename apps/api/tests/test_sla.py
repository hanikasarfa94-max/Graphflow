"""SlaService tests (Sprint 2b — SLA escalation ladder).

Seeds commitments with various target_date/sla_window permutations,
drives SlaService.check_project, asserts:
  * due-soon commitments emit exactly one sla-alert MessageRow
  * overdue commitments emit one sla-alert with band=overdue
  * OK commitments emit nothing
  * throttling: a repeat sweep within the window does not re-fire
  * commitments without sla_window or target_date are ignored
  * closed/withdrawn commitments are ignored even if past target_date
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from workgraph_api.services import SlaService
from workgraph_domain import EventBus
from workgraph_persistence import (
    CommitmentRepository,
    MessageRow,
    ProjectMemberRepository,
    ProjectRow,
    StreamRow,
    UserRepository,
    session_scope,
)


def _uid() -> str:
    return str(uuid4())


async def _mk_project(maker) -> str:
    async with session_scope(maker) as session:
        pid = _uid()
        session.add(ProjectRow(id=pid, title="sla test"))
        await session.flush()
    return pid


async def _mk_user_with_stream(maker, project_id: str, username: str) -> str:
    """Create user, add as member, create a personal stream. SlaService
    finds the personal stream by looking up project streams of
    type=personal and matching the owner. Mirroring the streams_backfill
    pattern here."""
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        uid = user.id
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=uid
        )
        # Personal stream: v1 StreamRow carries owner_user_id; the
        # SlaService path uses StreamRepository.get_personal_for_user_in_project
        # which filters on (project_id, owner_user_id, type='personal').
        stream = StreamRow(
            id=_uid(),
            type="personal",
            project_id=project_id,
            owner_user_id=uid,
        )
        session.add(stream)
        await session.flush()
    return uid


async def _mk_commitment(
    maker,
    project_id: str,
    owner_id: str,
    *,
    target_date: datetime,
    sla_window_seconds: int | None,
    status: str = "open",
) -> str:
    async with session_scope(maker) as session:
        row = await CommitmentRepository(session).create(
            project_id=project_id,
            created_by_user_id=owner_id,
            owner_user_id=owner_id,
            headline="ship it",
            target_date=target_date,
            sla_window_seconds=sla_window_seconds,
        )
        if status != "open":
            await CommitmentRepository(session).set_status(
                row.id, status=status
            )
        return row.id


async def _count_alerts_for_owner(maker, owner_id: str) -> list[MessageRow]:
    async with session_scope(maker) as session:
        from sqlalchemy import select

        rows = list(
            (
                await session.execute(
                    select(MessageRow).where(
                        MessageRow.author_id == owner_id,
                        MessageRow.kind == "sla-alert",
                    )
                )
            )
            .scalars()
            .all()
        )
        return rows


@pytest.mark.asyncio
async def test_due_soon_fires_alert(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user_with_stream(maker, pid, "sla_due_soon")
    # Target is 1h away; sla_window is 6h, so we're inside due-soon.
    target = datetime.now(timezone.utc) + timedelta(hours=1)
    await _mk_commitment(
        maker, pid, owner,
        target_date=target,
        sla_window_seconds=6 * 3600,
    )

    svc = SlaService(
        maker,
        EventBus(maker),
        stream_service=None,  # unused in check_project path
    )
    result = await svc.check_project(project_id=pid)

    assert result["ok"] is True
    assert len(result["fired"]) == 1
    assert result["fired"][0]["band"] == "due_soon"
    alerts = await _count_alerts_for_owner(maker, owner)
    assert len(alerts) == 1


@pytest.mark.asyncio
async def test_overdue_fires_alert(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user_with_stream(maker, pid, "sla_overdue")
    target = datetime.now(timezone.utc) - timedelta(hours=2)
    await _mk_commitment(
        maker, pid, owner,
        target_date=target,
        sla_window_seconds=3600,
    )

    svc = SlaService(maker, EventBus(maker), stream_service=None)
    result = await svc.check_project(project_id=pid)

    assert len(result["fired"]) == 1
    assert result["fired"][0]["band"] == "overdue"
    assert result["fired"][0]["seconds_remaining"] < 0


@pytest.mark.asyncio
async def test_ok_band_does_not_fire(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user_with_stream(maker, pid, "sla_ok")
    # Target is 5 days away; sla_window is 24h. OK band.
    target = datetime.now(timezone.utc) + timedelta(days=5)
    await _mk_commitment(
        maker, pid, owner,
        target_date=target,
        sla_window_seconds=24 * 3600,
    )

    svc = SlaService(maker, EventBus(maker), stream_service=None)
    result = await svc.check_project(project_id=pid)

    assert result["fired"] == []
    alerts = await _count_alerts_for_owner(maker, owner)
    assert alerts == []


@pytest.mark.asyncio
async def test_throttle_suppresses_repeat_within_window(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user_with_stream(maker, pid, "sla_throttle")
    target = datetime.now(timezone.utc) + timedelta(minutes=30)
    await _mk_commitment(
        maker, pid, owner,
        target_date=target,
        sla_window_seconds=3600,
    )

    svc = SlaService(maker, EventBus(maker), stream_service=None)
    first = await svc.check_project(project_id=pid)
    assert len(first["fired"]) == 1

    # Second sweep happens immediately — the throttle window is
    # `sla_window_seconds` (3600s here), so no re-fire.
    second = await svc.check_project(project_id=pid)
    assert second["fired"] == []
    alerts = await _count_alerts_for_owner(maker, owner)
    assert len(alerts) == 1


@pytest.mark.asyncio
async def test_commitment_without_sla_window_is_ignored(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user_with_stream(maker, pid, "sla_no_window")
    target = datetime.now(timezone.utc) - timedelta(hours=5)  # past
    await _mk_commitment(
        maker, pid, owner,
        target_date=target,
        sla_window_seconds=None,  # explicitly no SLA
    )

    svc = SlaService(maker, EventBus(maker), stream_service=None)
    result = await svc.check_project(project_id=pid)

    assert result["fired"] == []


@pytest.mark.asyncio
async def test_commitment_without_target_date_is_ignored(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user_with_stream(maker, pid, "sla_no_target")
    # No target_date — quality promise. SLA can't apply.
    async with session_scope(maker) as session:
        await CommitmentRepository(session).create(
            project_id=pid,
            created_by_user_id=owner,
            owner_user_id=owner,
            headline="ship with quality",
            target_date=None,
            sla_window_seconds=3600,
        )

    svc = SlaService(maker, EventBus(maker), stream_service=None)
    result = await svc.check_project(project_id=pid)

    assert result["fired"] == []


@pytest.mark.asyncio
async def test_non_open_status_is_ignored(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner = await _mk_user_with_stream(maker, pid, "sla_resolved")
    target = datetime.now(timezone.utc) - timedelta(hours=2)
    await _mk_commitment(
        maker, pid, owner,
        target_date=target,
        sla_window_seconds=3600,
        status="met",
    )

    svc = SlaService(maker, EventBus(maker), stream_service=None)
    result = await svc.check_project(project_id=pid)

    assert result["fired"] == []
