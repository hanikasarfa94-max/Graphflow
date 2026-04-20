"""SlaService — Sprint 2b escalation ladder.

A commitment with `sla_window_seconds` set + `target_date` set defines
three bands relative to now:

  * OK      — more than sla_window before target_date. Silent.
  * DUE-SOON — within `sla_window` of target_date. Ambient nudge.
  * OVERDUE — past target_date. Louder nudge.

This service sweeps a project's open commitments on demand and emits
one `sla-alert` MessageRow per breach into the owner's personal
project stream. Subscribed to `decision.applied` / `delivery.generated`
/ `commitment.created` events via EventBus.subscribe (the Sprint 1c
mechanism), so escalation runs whenever the project's graph moves AND
on commitment creation (catches "created but already overdue").

Throttle: CommitmentRow.sla_last_escalated_at ensures we don't re-
page the same owner every time a graph event lands within the same
sla_window. Concrete rule: re-escalate only when >= `sla_window`
seconds have passed since the last poke (or never).

The service is read-heavy + emit-occasional; cost stays low because
the per-commitment check is cheap SQL + a Python inequality. LLM
calls are NOT involved — escalation is structurally derivable from
target_date and sla_window, no agent required.

v2 adds:
  * ladder promotion (LLM → IM → face-to-face tag) vs the current
    single-band "sla-alert" signal;
  * periodic scheduler for commitments on projects with no recent
    graph activity (today we only fire on graph events);
  * DM-level escalation that crosses project boundaries.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    CommitmentRepository,
    CommitmentRow,
    MessageRepository,
    ProjectMemberRepository,
    StreamRepository,
    session_scope,
)

from .streams import StreamService

_log = logging.getLogger("workgraph.api.sla")

# "due-soon" covers the sla_window_seconds leading up to target_date.
# "overdue" begins at target_date. The throttle uses the same window —
# we re-page at most once per band per window-length.
_DUE_SOON = "due_soon"
_OVERDUE = "overdue"


@dataclass(frozen=True)
class _SlaState:
    band: str  # "due_soon" | "overdue"
    target_date: datetime
    # Seconds remaining to target (negative when overdue).
    seconds_remaining: int


def _as_naive_utc(dt: datetime | None) -> datetime | None:
    """Normalize to naive UTC — SQLite test backend returns naive
    datetimes, production Postgres returns aware. Use naive-UTC as
    the internal comparison coordinate so aware/naive mixing never
    raises. This mirrors the pattern in routing_suggest."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def _evaluate(
    row: CommitmentRow, *, now_naive: datetime
) -> _SlaState | None:
    if row.status != "open":
        return None
    if row.sla_window_seconds is None or row.target_date is None:
        return None
    target = _as_naive_utc(row.target_date)
    if target is None:
        return None
    delta_seconds = int((target - now_naive).total_seconds())
    if delta_seconds < 0:
        return _SlaState(
            band=_OVERDUE,
            target_date=target,
            seconds_remaining=delta_seconds,
        )
    if delta_seconds <= row.sla_window_seconds:
        return _SlaState(
            band=_DUE_SOON,
            target_date=target,
            seconds_remaining=delta_seconds,
        )
    return None


def _should_fire(
    row: CommitmentRow, *, now_naive: datetime
) -> bool:
    """Throttle: fire if never escalated, or if the last escalation
    was older than `sla_window_seconds` ago. Keeps us from spamming
    the owner when multiple graph events land in the same window."""
    last = _as_naive_utc(row.sla_last_escalated_at)
    if last is None:
        return True
    if row.sla_window_seconds is None:
        return True
    throttle_seconds = row.sla_window_seconds
    return (now_naive - last).total_seconds() >= throttle_seconds


class SlaService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        stream_service: StreamService,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._stream_service = stream_service

    async def check_project(
        self, *, project_id: str
    ) -> dict[str, Any]:
        """Sweep all open commitments in a project, escalate any in
        due-soon or overdue bands (respecting the per-commitment
        throttle), and stamp `sla_last_escalated_at` on each one we
        fire on. Returns a summary dict the caller can log or return
        as JSON."""
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        fired: list[dict[str, Any]] = []

        async with session_scope(self._sessionmaker) as session:
            cm_repo = CommitmentRepository(session)
            commitments = await cm_repo.list_open_for_project(
                project_id, limit=200
            )
            if not commitments:
                return {
                    "ok": True,
                    "project_id": project_id,
                    "checked": 0,
                    "fired": [],
                }

            # Resolve per-owner personal stream lazily inside the loop
            # below. StreamRepository.get_personal_for_user_in_project
            # is a single indexed lookup, so N owners = N cheap queries.
            stream_repo = StreamRepository(session)
            msg_repo = MessageRepository(session)
            pm_repo = ProjectMemberRepository(session)

            for row in commitments:
                state = _evaluate(row, now_naive=now_naive)
                if state is None:
                    continue
                if not _should_fire(row, now_naive=now_naive):
                    continue
                owner_id = row.owner_user_id or row.created_by_user_id
                if owner_id is None:
                    continue
                # Owner must still be a member of the project — if
                # they've been removed, the alert has nowhere to
                # land. Skip silently; resolving the commitment is
                # the owner's successor's problem.
                if not await pm_repo.is_member(project_id, owner_id):
                    continue
                target_stream = await stream_repo.get_personal_for_user_in_project(
                    user_id=owner_id, project_id=project_id
                )
                if target_stream is None:
                    continue

                import json

                body = json.dumps(
                    {
                        "band": state.band,
                        "commitment_id": row.id,
                        "project_id": project_id,
                        "headline": row.headline,
                        "target_date": state.target_date.isoformat(),
                        "seconds_remaining": state.seconds_remaining,
                        "sla_window_seconds": row.sla_window_seconds,
                    }
                )
                await msg_repo.append(
                    project_id=project_id,
                    author_id=owner_id,  # signal surfaces in owner's thread
                    body=body,
                    stream_id=target_stream.id,
                    kind="sla-alert",
                    linked_id=row.id,
                )
                await cm_repo.mark_escalated(row.id, at=datetime.now(timezone.utc))
                fired.append(
                    {
                        "commitment_id": row.id,
                        "owner_user_id": owner_id,
                        "band": state.band,
                        "seconds_remaining": state.seconds_remaining,
                    }
                )

        if fired:
            await self._event_bus.emit(
                "sla.escalated",
                {
                    "project_id": project_id,
                    "count": len(fired),
                    "items": fired,
                },
            )

        return {
            "ok": True,
            "project_id": project_id,
            "checked": len(commitments),
            "fired": fired,
        }


__all__ = ["SlaService"]
