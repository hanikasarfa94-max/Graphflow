"""TaskProgressService — Phase U status self-reports + leader scoring.

Solves the off-platform-work problem: when a task assignee does the
actual work outside WorkGraph (Unity, Figma, code), the platform can't
auto-detect progress. So:

  * Owner manually transitions task status (open → in_progress →
    blocked → done; done → in_progress to reopen; any → canceled).
  * Project owner scores the completion (good / ok / needs_work) when
    status hits done.
  * Score feeds perf_aggregation as a `task_quality_index` per member.

Design notes:

  * Status flips go through TaskRepository (which already exists for
    plan-side mutations) AND write an audit row to TaskStatusUpdateRow.
    Both writes share one session_scope so a crash leaves no orphan.

  * `update_status` accepts assignee OR project owner. Lets a leader
    intervene if a member ghosts. The audit row records `actor_user_id`
    so we don't lose attribution.

  * The state machine forbids weird transitions (open → done direct).
    Concrete transitions are enumerated in `_VALID_TRANSITIONS`.

  * `score_completion` is upsert-keyed on (task_id, assignee_user_id) —
    one score per (task, person who did it). Reviewer can change their
    verdict until the task is canceled; after canceled, edits are
    rejected (history is closed).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    AssignmentRepository,
    ProjectMemberRepository,
    TaskRow,
    TaskScoreRepository,
    TaskStatusUpdateRepository,
    UserRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.task_progress")


# Status taxonomy. The TaskRow.status column already accepts arbitrary
# String(32); these are the values the self-report flow writes. Other
# subsystems (planning, drift) may emit additional terminal-ish values
# we don't know about — we don't try to enumerate every legal source
# state, only what the assignee can transition INTO.
VALID_TARGET_STATES: frozenset[str] = frozenset(
    {"open", "in_progress", "blocked", "done", "canceled"}
)

# Forbidden direct hops. Everything else is allowed (we trust the
# caller — this is human-driven). The point is to catch obvious
# fat-fingers, not enforce a strict graph.
_FORBIDDEN_TRANSITIONS: set[tuple[str, str]] = {
    ("open", "done"),       # must mark in_progress at least once
    ("canceled", "done"),   # canceled is terminal for this assignee
    ("canceled", "in_progress"),
    ("canceled", "blocked"),
}

VALID_QUALITIES: frozenset[str] = frozenset({"good", "ok", "needs_work"})

# Quality → numeric index for perf rollup. Keep simple; v2 can weight
# differently. Documented here so the perf surface and the UI agree.
QUALITY_INDEX: dict[str, float] = {
    "good": 1.0,
    "ok": 0.5,
    "needs_work": 0.0,
}


class TaskProgressError(Exception):
    """Service-layer error with a machine-readable code. Mapped to HTTP
    by the router."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


class TaskProgressService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus

    # ---- status updates ------------------------------------------------

    async def update_status(
        self,
        *,
        task_id: str,
        actor_user_id: str,
        new_status: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Owner OR assignee can transition. Logs to audit, updates
        TaskRow.status, emits `task.status_changed` AFTER the commit
        (subscriber-task-drain discipline)."""
        if new_status not in VALID_TARGET_STATES:
            raise TaskProgressError(
                "invalid_status",
                f"new_status must be one of {sorted(VALID_TARGET_STATES)}",
            )
        if note is not None:
            note = (note or "").strip()
            if len(note) > 2000:
                note = note[:2000]
            if not note:
                note = None

        async with session_scope(self._sessionmaker) as session:
            task = (
                await session.execute(
                    select(TaskRow).where(TaskRow.id == task_id)
                )
            ).scalar_one_or_none()
            if task is None:
                raise TaskProgressError("task_not_found")

            # Permission: assignee OR project owner.
            project_id = task.project_id
            assignee_user_id = await _current_assignee(session, task_id)
            is_assignee = (
                assignee_user_id is not None and assignee_user_id == actor_user_id
            )
            is_project_owner = await _is_project_owner(
                session, project_id, actor_user_id
            )
            if not (is_assignee or is_project_owner):
                raise TaskProgressError("forbidden")

            old_status = task.status or "open"
            if old_status == new_status:
                # No-op; don't write an audit row, return current state.
                return {
                    "ok": True,
                    "task_id": task_id,
                    "status": old_status,
                    "no_op": True,
                }
            if (old_status, new_status) in _FORBIDDEN_TRANSITIONS:
                raise TaskProgressError(
                    "invalid_transition",
                    f"cannot transition {old_status} → {new_status} directly",
                )

            await TaskStatusUpdateRepository(session).append(
                task_id=task_id,
                actor_user_id=actor_user_id,
                old_status=old_status,
                new_status=new_status,
                note=note,
            )
            task.status = new_status

        # Emit AFTER commit (the discipline established in earlier
        # event-bus race-condition fixes).
        await self._event_bus.emit(
            "task.status_changed",
            {
                "task_id": task_id,
                "project_id": project_id,
                "actor_user_id": actor_user_id,
                "old_status": old_status,
                "new_status": new_status,
                "note": note,
            },
        )
        return {
            "ok": True,
            "task_id": task_id,
            "status": new_status,
            "old_status": old_status,
        }

    # ---- scoring -------------------------------------------------------

    async def score_completion(
        self,
        *,
        task_id: str,
        reviewer_user_id: str,
        quality: str,
        feedback: str | None = None,
    ) -> dict[str, Any]:
        """Project owner scores a done-status task. Quality must be in
        VALID_QUALITIES. Upsert keyed on (task_id, assignee_user_id) —
        one score per (task, person who did it)."""
        if quality not in VALID_QUALITIES:
            raise TaskProgressError("invalid_quality")
        if feedback is not None:
            feedback = (feedback or "").strip()
            if len(feedback) > 2000:
                feedback = feedback[:2000]
            if not feedback:
                feedback = None

        async with session_scope(self._sessionmaker) as session:
            task = (
                await session.execute(
                    select(TaskRow).where(TaskRow.id == task_id)
                )
            ).scalar_one_or_none()
            if task is None:
                raise TaskProgressError("task_not_found")
            project_id = task.project_id
            current_status = task.status or "open"
            if current_status == "canceled":
                raise TaskProgressError(
                    "canceled_task", "cannot score a canceled task"
                )
            if current_status != "done":
                raise TaskProgressError(
                    "not_done",
                    "task must be in `done` status before scoring",
                )

            if not await _is_project_owner(
                session, project_id, reviewer_user_id
            ):
                raise TaskProgressError("forbidden")

            assignee_user_id = await _current_assignee(session, task_id)
            if assignee_user_id is None:
                raise TaskProgressError(
                    "no_assignee",
                    "cannot score a task with no active assignment",
                )

            row, created = await TaskScoreRepository(session).upsert(
                task_id=task_id,
                reviewer_user_id=reviewer_user_id,
                assignee_user_id=assignee_user_id,
                quality=quality,
                feedback=feedback,
            )
            payload_quality = row.quality
            payload_feedback = row.feedback
            payload_assignee = assignee_user_id

        await self._event_bus.emit(
            "task.scored",
            {
                "task_id": task_id,
                "project_id": project_id,
                "reviewer_user_id": reviewer_user_id,
                "assignee_user_id": payload_assignee,
                "quality": payload_quality,
                "created": created,
            },
        )
        return {
            "ok": True,
            "task_id": task_id,
            "quality": payload_quality,
            "feedback": payload_feedback,
            "assignee_user_id": payload_assignee,
            "reviewer_user_id": reviewer_user_id,
            "created": created,
        }

    # ---- read paths (for UI + perf) ------------------------------------

    async def history(
        self, *, task_id: str, viewer_user_id: str
    ) -> dict[str, Any]:
        """Status timeline + score (if any). Project membership gates."""
        async with session_scope(self._sessionmaker) as session:
            task = (
                await session.execute(
                    select(TaskRow).where(TaskRow.id == task_id)
                )
            ).scalar_one_or_none()
            if task is None:
                raise TaskProgressError("task_not_found")
            project_id = task.project_id
            if not await ProjectMemberRepository(session).is_member(
                project_id, viewer_user_id
            ):
                raise TaskProgressError("forbidden")
            updates = await TaskStatusUpdateRepository(
                session
            ).list_for_task(task_id)
            score = await TaskScoreRepository(session).get_for_task(task_id)
            user_repo = UserRepository(session)
            actor_names: dict[str, str] = {}
            for row in updates:
                if row.actor_user_id not in actor_names:
                    u = await user_repo.get(row.actor_user_id)
                    actor_names[row.actor_user_id] = (
                        u.display_name or u.username
                    ) if u else row.actor_user_id
            score_payload: dict[str, Any] | None = None
            if score is not None:
                score_payload = {
                    "quality": score.quality,
                    "feedback": score.feedback,
                    "reviewer_user_id": score.reviewer_user_id,
                    "assignee_user_id": score.assignee_user_id,
                    "created_at": (
                        score.created_at.isoformat() if score.created_at else None
                    ),
                    "updated_at": (
                        score.updated_at.isoformat() if score.updated_at else None
                    ),
                }
        return {
            "task_id": task_id,
            "current_status": task.status or "open",
            "updates": [
                {
                    "id": u.id,
                    "actor_user_id": u.actor_user_id,
                    "actor_display_name": actor_names.get(u.actor_user_id),
                    "old_status": u.old_status,
                    "new_status": u.new_status,
                    "note": u.note,
                    "created_at": u.created_at.isoformat()
                    if u.created_at
                    else None,
                }
                for u in updates
            ],
            "score": score_payload,
        }


# ---- helpers ----------------------------------------------------------


async def _current_assignee(session, task_id: str) -> str | None:
    """Returns the user_id of the active assignment, or None."""
    repo = AssignmentRepository(session)
    row = await repo.active_for_task(task_id)
    return row.user_id if row is not None else None


async def _is_project_owner(session, project_id: str, user_id: str) -> bool:
    members = await ProjectMemberRepository(session).list_for_project(
        project_id
    )
    return any(m.user_id == user_id and m.role == "owner" for m in members)


__all__ = [
    "TaskProgressService",
    "TaskProgressError",
    "VALID_TARGET_STATES",
    "VALID_QUALITIES",
    "QUALITY_INDEX",
]
