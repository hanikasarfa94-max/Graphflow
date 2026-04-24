"""Phase 7'' collab services: assignments, comments, notifications, messages.

Every mutation follows the same three-step pattern:
  1) persist via a repository
  2) emit a domain event (auth / trace_id propagate via ContextVar)
  3) broadcast a WS payload via CollabHub so every subscriber of the project
     sees the delta without a refetch

Notifications fan in to users (assignee + @mentions); every other delta
fans out to all project subscribers.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    AssignmentRepository,
    CommentRepository,
    MessageRepository,
    NotificationRepository,
    PlanRepository,
    ProjectMemberRepository,
    ProjectMemberRow,
    ProjectRow,
    StreamRepository,
    TaskRow,
    UserRepository,
    session_scope,
)

from .collab_hub import CollabHub
from .signal_tally import SignalTallyService

_log = logging.getLogger("workgraph.api.collab")

_MENTION_RE = re.compile(r"@([A-Za-z0-9_-]{3,32})")


def _broadcast_payload(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": kind, "payload": data}


class NotificationService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub

    async def notify(
        self,
        *,
        user_id: str,
        project_id: str,
        kind: str,
        body: str,
        target_kind: str | None = None,
        target_id: str | None = None,
    ) -> dict:
        async with session_scope(self._sessionmaker) as session:
            row = await NotificationRepository(session).append(
                user_id=user_id,
                project_id=project_id,
                kind=kind,
                body=body,
                target_kind=target_kind,
                target_id=target_id,
            )
            payload = {
                "id": row.id,
                "user_id": row.user_id,
                "project_id": row.project_id,
                "kind": row.kind,
                "body": row.body,
                "target_kind": row.target_kind,
                "target_id": row.target_id,
                "read": row.read,
                "created_at": row.created_at.isoformat(),
            }

        await self._event_bus.emit("notification.produced", payload)
        await self._hub.publish(project_id, _broadcast_payload("notification", payload))
        return payload

    async def list_for_user(
        self, user_id: str, *, unread_only: bool = False, limit: int = 50
    ) -> list[dict]:
        async with session_scope(self._sessionmaker) as session:
            rows = await NotificationRepository(session).list_for_user(
                user_id, unread_only=unread_only, limit=limit
            )
            return [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "project_id": r.project_id,
                    "kind": r.kind,
                    "body": r.body,
                    "target_kind": r.target_kind,
                    "target_id": r.target_id,
                    "read": r.read,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]

    async def unread_count(self, user_id: str) -> int:
        async with session_scope(self._sessionmaker) as session:
            return await NotificationRepository(session).unread_count(user_id)

    async def mark_read(self, notification_id: str, user_id: str) -> bool:
        async with session_scope(self._sessionmaker) as session:
            row = await NotificationRepository(session).mark_read(
                notification_id, user_id
            )
            return row is not None

    async def mark_all_read(self, user_id: str) -> int:
        async with session_scope(self._sessionmaker) as session:
            return await NotificationRepository(session).mark_all_read(user_id)


class AssignmentService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
        notifications: NotificationService,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub
        self._notifications = notifications

    async def set_assignment(
        self, *, task_id: str, user_id: str | None, actor_id: str
    ) -> dict:
        """Assign `task_id` to `user_id` (null = unassign). Emits + broadcasts."""
        async with session_scope(self._sessionmaker) as session:
            task = (
                await session.execute(select(TaskRow).where(TaskRow.id == task_id))
            ).scalar_one_or_none()
            if task is None:
                return {"ok": False, "error": "task_not_found"}
            project_id = task.project_id

            if user_id is not None:
                user = await UserRepository(session).get(user_id)
                if user is None:
                    return {"ok": False, "error": "user_not_found"}
                # Auto-join the assignee to the project so they can see notifications.
                await ProjectMemberRepository(session).add(
                    project_id=project_id, user_id=user_id
                )

            row = await AssignmentRepository(session).set_assignment(
                project_id=project_id, task_id=task_id, user_id=user_id
            )
            task_title = task.title

        payload = {
            "task_id": task_id,
            "project_id": project_id,
            "user_id": user_id,
            "assignment_id": row.id if row is not None else None,
            "actor_id": actor_id,
        }
        # Notify BEFORE emit — see signal_tally / decisions.py precedent
        # (commit d0bf1fe). EventBus.emit() schedules subscribers via
        # asyncio.create_task whose concurrent aiosqlite sessions race
        # any follow-up DB write and silently drop it. The notification
        # row must land first so fresh-session reads see it.
        if user_id and user_id != actor_id:
            await self._notifications.notify(
                user_id=user_id,
                project_id=project_id,
                kind="assigned",
                body=f"You were assigned to: {task_title}",
                target_kind="task",
                target_id=task_id,
            )
        await self._event_bus.emit("assignment.changed", payload)
        await self._hub.publish(project_id, _broadcast_payload("assignment", payload))
        return {"ok": True, **payload}

    async def list_for_project(self, project_id: str) -> list[dict]:
        async with session_scope(self._sessionmaker) as session:
            rows = await AssignmentRepository(session).list_for_project(project_id)
            return [
                {
                    "id": r.id,
                    "task_id": r.task_id,
                    "user_id": r.user_id,
                    "active": r.active,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]


@dataclass(slots=True)
class _CommentTarget:
    project_id: str
    target_kind: str
    target_id: str
    title: str | None = None
    assignee_user_id: str | None = None


async def _resolve_target(
    session, *, project_id_hint: str | None, target_kind: str, target_id: str
) -> _CommentTarget | None:
    """Fetch the parent row for a comment target. Returns None if not found.

    For tasks, populates assignee_user_id so the comment service can notify.
    """
    if target_kind == "task":
        task = (
            await session.execute(select(TaskRow).where(TaskRow.id == target_id))
        ).scalar_one_or_none()
        if task is None:
            return None
        # Active assignment is optional.
        from workgraph_persistence import AssignmentRepository as _AR  # local import

        assignment = await _AR(session).active_for_task(target_id)
        return _CommentTarget(
            project_id=task.project_id,
            target_kind="task",
            target_id=target_id,
            title=task.title,
            assignee_user_id=assignment.user_id if assignment else None,
        )
    # deliverable / risk — no assignee tracking yet.
    if project_id_hint is None:
        return None
    project = (
        await session.execute(select(ProjectRow).where(ProjectRow.id == project_id_hint))
    ).scalar_one_or_none()
    if project is None:
        return None
    return _CommentTarget(
        project_id=project_id_hint, target_kind=target_kind, target_id=target_id
    )


class CommentService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
        notifications: NotificationService,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub
        self._notifications = notifications

    async def post(
        self,
        *,
        author_id: str,
        target_kind: str,
        target_id: str,
        body: str,
        project_id_hint: str | None = None,
        parent_comment_id: str | None = None,
    ) -> dict:
        async with session_scope(self._sessionmaker) as session:
            tgt = await _resolve_target(
                session,
                project_id_hint=project_id_hint,
                target_kind=target_kind,
                target_id=target_id,
            )
            if tgt is None:
                return {"ok": False, "error": "target_not_found"}

            row = await CommentRepository(session).append(
                project_id=tgt.project_id,
                author_id=author_id,
                target_kind=tgt.target_kind,
                target_id=tgt.target_id,
                body=body,
                parent_comment_id=parent_comment_id,
            )
            author = await UserRepository(session).get(author_id)
            # Resolve @mentions while we have the session.
            mention_usernames = set(_MENTION_RE.findall(body))
            mention_user_ids: list[tuple[str, str]] = []
            if mention_usernames:
                for uname in mention_usernames:
                    u = await UserRepository(session).get_by_username(uname)
                    if u is not None and u.id != author_id:
                        mention_user_ids.append((u.id, uname))

            payload = {
                "id": row.id,
                "project_id": row.project_id,
                "author_id": row.author_id,
                "author_username": author.username if author else None,
                "target_kind": row.target_kind,
                "target_id": row.target_id,
                "parent_comment_id": row.parent_comment_id,
                "body": row.body,
                "created_at": row.created_at.isoformat(),
            }
            assignee_user_id = tgt.assignee_user_id
            target_title = tgt.title

        # Notify BEFORE emit — see signal_tally / decisions.py precedent
        # (commit d0bf1fe). EventBus.emit() schedules subscribers via
        # asyncio.create_task whose concurrent aiosqlite sessions race
        # any follow-up DB write and silently drop it. Notification rows
        # must land first so fresh-session reads (e.g. assignee/mentioned
        # user's /api/notifications GET) see them.
        notified: set[str] = set()
        if (
            assignee_user_id
            and assignee_user_id != author_id
            and assignee_user_id not in notified
        ):
            notified.add(assignee_user_id)
            title = target_title or target_id
            await self._notifications.notify(
                user_id=assignee_user_id,
                project_id=payload["project_id"],
                kind="comment",
                body=f"New comment on {title}",
                target_kind=target_kind,
                target_id=target_id,
            )
        for uid, _uname in mention_user_ids:
            if uid in notified:
                continue
            notified.add(uid)
            await self._notifications.notify(
                user_id=uid,
                project_id=payload["project_id"],
                kind="mentioned",
                body=f"You were mentioned in a comment",
                target_kind=target_kind,
                target_id=target_id,
            )
        await self._event_bus.emit("comment.posted", payload)
        await self._hub.publish(
            payload["project_id"], _broadcast_payload("comment", payload)
        )
        return {"ok": True, **payload}

    async def list_for_target(
        self, target_kind: str, target_id: str
    ) -> list[dict]:
        async with session_scope(self._sessionmaker) as session:
            rows = await CommentRepository(session).list_for_target(
                target_kind, target_id
            )
            if not rows:
                return []
            user_repo = UserRepository(session)
            authors: dict[str, str] = {}
            for r in rows:
                if r.author_id not in authors:
                    u = await user_repo.get(r.author_id)
                    if u is not None:
                        authors[r.author_id] = u.username
            return [
                {
                    "id": r.id,
                    "project_id": r.project_id,
                    "author_id": r.author_id,
                    "author_username": authors.get(r.author_id),
                    "target_kind": r.target_kind,
                    "target_id": r.target_id,
                    "parent_comment_id": r.parent_comment_id,
                    "body": r.body,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]


class MessageService:
    """Persist + broadcast project IM messages. Rate-limited per user.

    IM-AI classification runs separately via IMService and writes
    IMSuggestionRow keyed by message_id, so the message write itself stays
    fast and deterministic.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
        notifications: NotificationService,
        signal_tally: SignalTallyService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub
        self._notifications = notifications
        self._signal_tally = signal_tally

    async def post(
        self, *, project_id: str, author_id: str, body: str
    ) -> dict:
        if not self._hub.rate_limit_ok(author_id, project_id, limit_per_sec=10):
            return {"ok": False, "error": "rate_limited"}

        async with session_scope(self._sessionmaker) as session:
            # Phase B (v2): observer-tier members cannot post messages.
            pm_repo = ProjectMemberRepository(session)
            member = (
                await session.execute(
                    select(ProjectMemberRow).where(
                        ProjectMemberRow.project_id == project_id,
                        ProjectMemberRow.user_id == author_id,
                    )
                )
            ).scalar_one_or_none()
            if member is not None and member.license_tier == "observer":
                return {"ok": False, "error": "observer_cannot_post"}

            # Fetch (or backfill) the project stream so every message gets a
            # stream_id. Idempotent — the boot-time backfill usually does this
            # already, but tests + freshly-seeded projects may race.
            stream_repo = StreamRepository(session)
            stream = await stream_repo.get_for_project(project_id)
            if stream is None:
                stream = await stream_repo.create(
                    type="project", project_id=project_id
                )
            stream_id = stream.id

            row = await MessageRepository(session).append(
                project_id=project_id,
                author_id=author_id,
                body=body,
                stream_id=stream_id,
            )
            # Bump stream activity so GET /api/streams ordering stays fresh.
            await stream_repo.touch_activity(stream_id)
            author = await UserRepository(session).get(author_id)
            member_rows = await pm_repo.list_for_project(project_id)
            member_ids = [m.user_id for m in member_rows if m.user_id != author_id]

        payload = {
            "id": row.id,
            "project_id": project_id,
            "stream_id": stream_id,
            "author_id": author_id,
            "author_username": author.username if author else None,
            "body": body,
            "created_at": row.created_at.isoformat(),
        }
        # Tally + notify before emit — see decisions.py / signal_tally
        # precedent (commit d0bf1fe). EventBus.emit() schedules
        # subscribers via asyncio.create_task whose concurrent aiosqlite
        # sessions race any follow-up DB write and silently drop it.
        # Both the tally and the fanout notification rows must land
        # before control hands off to fire-and-forget subscribers.
        if self._signal_tally is not None:
            await self._signal_tally.increment(author_id, "messages_posted")
        for uid in member_ids:
            await self._notifications.notify(
                user_id=uid,
                project_id=project_id,
                kind="message",
                body=f"{author.username if author else 'someone'} posted a message",
                target_kind="message",
                target_id=row.id,
            )
        await self._event_bus.emit("message.posted", payload)
        await self._hub.publish(project_id, _broadcast_payload("message", payload))
        return {"ok": True, **payload}

    async def list_recent(self, project_id: str, limit: int = 100) -> list[dict]:
        """Team-room messages only.

        Post-Phase-L architectural correction: personal streams are
        anchored to the same project_id as the team room, so filtering
        by project_id alone leaked personal-stream messages into the
        team view. We now scope strictly to the project's team-room
        stream (type='project').
        """
        async with session_scope(self._sessionmaker) as session:
            team_stream = await StreamRepository(session).get_for_project(project_id)
            if team_stream is None:
                return []
            rows = await MessageRepository(session).list_for_stream(
                team_stream.id, limit=limit
            )
            user_repo = UserRepository(session)
            authors: dict[str, str] = {}
            for r in rows:
                if r.author_id not in authors:
                    u = await user_repo.get(r.author_id)
                    if u is not None:
                        authors[r.author_id] = u.username
            return [
                {
                    "id": r.id,
                    "project_id": r.project_id,
                    "stream_id": r.stream_id,
                    "author_id": r.author_id,
                    "author_username": authors.get(r.author_id),
                    "body": r.body,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ]


# Re-export so the router can fetch task metadata for comments-drawer.
async def resolve_task_project(
    sessionmaker: async_sessionmaker, task_id: str
) -> str | None:
    async with session_scope(sessionmaker) as session:
        task = (
            await session.execute(select(TaskRow).where(TaskRow.id == task_id))
        ).scalar_one_or_none()
        return task.project_id if task is not None else None


async def list_plan_tasks_for_project(
    sessionmaker: async_sessionmaker, project_id: str
) -> list[str]:
    async with session_scope(sessionmaker) as session:
        # A project's plan tasks — used by IM service to anchor suggestions.
        from workgraph_persistence import RequirementRepository as _RR  # local import

        req = await _RR(session).latest_for_project(project_id)
        if req is None:
            return []
        tasks = await PlanRepository(session).list_tasks(req.id)
        return [t.id for t in tasks]
