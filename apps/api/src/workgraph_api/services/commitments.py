"""CommitmentService — Sprint 2a (thesis-commit primitive).

A commitment is a human-authored promise of a future state, distinct
from a DecisionRow. Decisions pick between options; commitments bind
an owner to an outcome. Drift detection (Sprint 1c, already auto-
firing on `decision.applied`) will read commitments as its "thesis"
proxy once Sprint 2b wires them in — this sprint just ships the CRUD
and lineage.

Policy at this layer:
  * Membership: any project member may create a commitment or mark
    an owned commitment as met/missed/withdrawn. Admin approvals are
    a v2 concern.
  * Headline is immutable once created — withdraw + re-create if the
    promise changes. Preserves the timeline.
  * Scope anchor (task / deliverable / goal / milestone) is optional.
    When present, it must belong to the same project — service
    validates this before the row is written.
  * `target_date` is free-form — no "target_date must be future"
    check, because backdated commitments are valid ("we committed to
    April 28 on April 15, but actually decided on April 13").
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    CommitmentRepository,
    CommitmentRow,
    DeliverableRow,
    GoalRow,
    MessageRow,
    MilestoneRow,
    ProjectMemberRepository,
    TaskRow,
    session_scope,
)

_log = logging.getLogger("workgraph.api.commitments")

_ALLOWED_SCOPE_KINDS = frozenset(
    {"task", "deliverable", "goal", "milestone"}
)
_ALLOWED_STATUS_TRANSITIONS = frozenset(
    {"open", "met", "missed", "withdrawn"}
)
_SCOPE_MODEL = {
    "task": TaskRow,
    "deliverable": DeliverableRow,
    "goal": GoalRow,
    "milestone": MilestoneRow,
}


class CommitmentValidationError(Exception):
    """Raised by the service when a create/update call is semantically
    invalid (unknown scope kind, anchor not in the project, unknown
    status transition). Routers translate these to HTTP 422.
    """


def _row_to_dict(row: CommitmentRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "created_by_user_id": row.created_by_user_id,
        "owner_user_id": row.owner_user_id,
        "headline": row.headline,
        "target_date": (
            row.target_date.isoformat() if row.target_date else None
        ),
        "metric": row.metric,
        "scope_ref_kind": row.scope_ref_kind,
        "scope_ref_id": row.scope_ref_id,
        "status": row.status,
        "source_message_id": row.source_message_id,
        "created_at": (
            row.created_at.isoformat() if row.created_at else None
        ),
        "resolved_at": (
            row.resolved_at.isoformat() if row.resolved_at else None
        ),
    }


class CommitmentService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus

    async def is_member(self, *, project_id: str, user_id: str) -> bool:
        async with session_scope(self._sessionmaker) as session:
            return await ProjectMemberRepository(session).is_member(
                project_id, user_id
            )

    async def create(
        self,
        *,
        project_id: str,
        actor_user_id: str,
        headline: str,
        owner_user_id: str | None = None,
        target_date: datetime | None = None,
        metric: str | None = None,
        scope_ref_kind: str | None = None,
        scope_ref_id: str | None = None,
        source_message_id: str | None = None,
    ) -> dict[str, Any]:
        # Semantic validation on scope anchor first — cheap rejection
        # before we touch the DB.
        if scope_ref_kind is not None:
            if scope_ref_kind not in _ALLOWED_SCOPE_KINDS:
                raise CommitmentValidationError(
                    f"scope_ref_kind must be one of {sorted(_ALLOWED_SCOPE_KINDS)}"
                )
            if not scope_ref_id:
                raise CommitmentValidationError(
                    "scope_ref_id required when scope_ref_kind is set"
                )
        elif scope_ref_id is not None:
            raise CommitmentValidationError(
                "scope_ref_kind required when scope_ref_id is set"
            )

        # Headline bounds — 3 to 500 chars, stripped.
        cleaned_headline = (headline or "").strip()
        if not 3 <= len(cleaned_headline) <= 500:
            raise CommitmentValidationError(
                "headline must be 3..500 chars"
            )

        async with session_scope(self._sessionmaker) as session:
            # Anchor-in-project check. The scope entity must belong to
            # this project; cross-project anchoring is rejected.
            if scope_ref_kind is not None and scope_ref_id is not None:
                model = _SCOPE_MODEL[scope_ref_kind]
                stmt = select(model.id).where(
                    model.id == scope_ref_id,
                    model.project_id == project_id,
                )
                found = (await session.execute(stmt)).scalar_one_or_none()
                if found is None:
                    raise CommitmentValidationError(
                        f"{scope_ref_kind} {scope_ref_id} not in project"
                    )

            # Source-message-in-project check (if supplied).
            if source_message_id is not None:
                stmt = select(MessageRow.id).where(
                    MessageRow.id == source_message_id,
                    MessageRow.project_id == project_id,
                )
                found = (await session.execute(stmt)).scalar_one_or_none()
                if found is None:
                    raise CommitmentValidationError(
                        "source_message_id not in project"
                    )

            repo = CommitmentRepository(session)
            row = await repo.create(
                project_id=project_id,
                created_by_user_id=actor_user_id,
                headline=cleaned_headline,
                owner_user_id=owner_user_id,
                target_date=target_date,
                metric=metric,
                scope_ref_kind=scope_ref_kind,
                scope_ref_id=scope_ref_id,
                source_message_id=source_message_id,
            )
            payload = _row_to_dict(row)

        # Emit so drift / eventually SLA watchers can react. Fire after
        # the transaction commits so subscribers see the persisted row.
        await self._event_bus.emit(
            "commitment.created",
            {
                "project_id": project_id,
                "commitment_id": payload["id"],
                "actor_user_id": actor_user_id,
            },
        )
        return payload

    async def set_status(
        self,
        *,
        commitment_id: str,
        actor_user_id: str,
        status: str,
    ) -> dict[str, Any] | None:
        if status not in _ALLOWED_STATUS_TRANSITIONS:
            raise CommitmentValidationError(
                f"status must be one of {sorted(_ALLOWED_STATUS_TRANSITIONS)}"
            )
        async with session_scope(self._sessionmaker) as session:
            repo = CommitmentRepository(session)
            current = await repo.get(commitment_id)
            if current is None:
                return None
            updated = await repo.set_status(commitment_id, status=status)

        if updated is None:
            return None
        payload = _row_to_dict(updated)
        await self._event_bus.emit(
            "commitment.status_changed",
            {
                "project_id": updated.project_id,
                "commitment_id": updated.id,
                "old_status": current.status,
                "new_status": updated.status,
                "actor_user_id": actor_user_id,
            },
        )
        return payload

    async def list_for_project(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            rows = await CommitmentRepository(session).list_for_project(
                project_id, status=status, limit=limit
            )
        return [_row_to_dict(r) for r in rows]


__all__ = ["CommitmentService", "CommitmentValidationError"]
