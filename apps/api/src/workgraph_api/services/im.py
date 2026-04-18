"""IM service — wraps MessageService + IMAssistAgent.

Flow:
  1) user posts a message → MessageService persists + broadcasts
  2) if body is ≥5 words, IMAssistAgent runs asynchronously
  3) suggestion row is written, event emitted, delta broadcast so the UI
     can render a chip inline with the message

Accepting a suggestion is a separate call that mutates the graph or opens
a risk; we never auto-apply (per Phase 7'' AC).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import IMAssistAgent
from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    AgentRunLogRepository,
    ConstraintRow,
    DeliverableRow,
    IMSuggestionRepository,
    IMSuggestionRow,
    MessageRepository,
    PlanRepository,
    ProjectGraphRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRepository,
    RiskRow,
    TaskRow,
    UserRepository,
    session_scope,
)

from .collab import MessageService, NotificationService
from .collab_hub import CollabHub

_log = logging.getLogger("workgraph.api.im")

MIN_WORDS_FOR_CLASSIFICATION = 5


def _word_count(body: str) -> int:
    return len([w for w in body.strip().split() if w.strip()])


class IMService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
        notifications: NotificationService,
        messages: MessageService,
        agent: IMAssistAgent,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub
        self._notifications = notifications
        self._messages = messages
        self._agent = agent
        # Keep in-flight classification tasks so tests + shutdown can await.
        self._pending: set[asyncio.Task] = set()

    async def post_message(
        self,
        *,
        project_id: str,
        author_id: str,
        body: str,
    ) -> dict[str, Any]:
        post_result = await self._messages.post(
            project_id=project_id, author_id=author_id, body=body
        )
        if not post_result.get("ok"):
            return post_result

        message_id = post_result["id"]
        if _word_count(body) < MIN_WORDS_FOR_CLASSIFICATION:
            return post_result

        task = asyncio.create_task(
            self._classify_and_persist(
                project_id=project_id,
                author_id=author_id,
                message_id=message_id,
                body=body,
            ),
            name=f"im-classify-{message_id}",
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return post_result

    async def drain(self) -> None:
        if not self._pending:
            return
        await asyncio.gather(*list(self._pending), return_exceptions=True)

    async def _project_snapshot(
        self, project_id: str, *, recent_msgs_limit: int = 5
    ) -> tuple[dict, dict, list[dict]]:
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                raise ValueError(f"project not found: {project_id}")

            req = await RequirementRepository(session).latest_for_project(project_id)
            deliverables: list[DeliverableRow] = []
            tasks: list[TaskRow] = []
            risks: list[RiskRow] = []
            goal_text = project.title
            if req is not None:
                graph_repo = ProjectGraphRepository(session)
                deliverables = await graph_repo.list_deliverables(req.id)
                risks = await graph_repo.list_risks(req.id)
                tasks = await PlanRepository(session).list_tasks(req.id)
                parsed = req.parsed_json or {}
                if isinstance(parsed, dict) and parsed.get("goal"):
                    goal_text = parsed["goal"]

            recent = list(
                await MessageRepository(session).list_recent(
                    project_id, limit=recent_msgs_limit
                )
            )
            user_repo = UserRepository(session)
            recent_authors: dict[str, str] = {}
            for r in recent:
                if r.author_id not in recent_authors:
                    u = await user_repo.get(r.author_id)
                    if u is not None:
                        recent_authors[r.author_id] = u.username

            project_snapshot = {
                "id": project.id,
                "title": project.title,
                "goal": goal_text,
                "deliverables": [
                    {"id": d.id, "title": d.title, "kind": d.kind} for d in deliverables
                ],
                "tasks": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "assignee_role": t.assignee_role,
                    }
                    for t in tasks
                ],
                "risks": [
                    {"id": r.id, "title": r.title, "severity": r.severity}
                    for r in risks
                ],
            }
            author_row = await user_repo.get_by_username("")  # noop for type hint
            # Fetch message author last so we don't hit the in-thread session twice.
            return (
                project_snapshot,
                {},
                [
                    {
                        "author": recent_authors.get(r.author_id, "unknown"),
                        "body": r.body,
                        "ts": r.created_at.isoformat(),
                    }
                    for r in recent
                    # Don't feed the current message back — we already classify it.
                ],
            )

    async def _classify_and_persist(
        self,
        *,
        project_id: str,
        author_id: str,
        message_id: str,
        body: str,
    ) -> None:
        try:
            project_snapshot, _, recent_msgs = await self._project_snapshot(project_id)
            async with session_scope(self._sessionmaker) as session:
                user = await UserRepository(session).get(author_id)
                author_payload = (
                    {
                        "id": user.id,
                        "username": user.username,
                        "display_name": user.display_name,
                    }
                    if user is not None
                    else {"id": author_id}
                )

            outcome = await self._agent.classify(
                message=body,
                author=author_payload,
                project=project_snapshot,
                recent_messages=recent_msgs,
            )
            suggestion = outcome.suggestion

            async with session_scope(self._sessionmaker) as session:
                row = await IMSuggestionRepository(session).append(
                    project_id=project_id,
                    message_id=message_id,
                    kind=suggestion.kind,
                    confidence=suggestion.confidence,
                    targets=list(suggestion.targets),
                    proposal=suggestion.proposal.model_dump()
                    if suggestion.proposal
                    else None,
                    reasoning=suggestion.reasoning,
                    prompt_version=self._agent.prompt_version,
                    outcome=outcome.outcome,
                    attempts=outcome.attempts,
                )
                await AgentRunLogRepository(session).append(
                    agent="im_assist",
                    prompt_version=self._agent.prompt_version,
                    project_id=project_id,
                    trace_id=get_trace_id(),
                    outcome=outcome.outcome,
                    attempts=outcome.attempts,
                    latency_ms=outcome.result.latency_ms,
                    prompt_tokens=outcome.result.prompt_tokens,
                    completion_tokens=outcome.result.completion_tokens,
                    cache_read_tokens=outcome.result.cache_read_tokens,
                    error=outcome.error,
                )

                payload = self._suggestion_payload(row)

            await self._event_bus.emit("im_suggestion.produced", payload)
            await self._hub.publish(
                project_id, {"type": "suggestion", "payload": payload}
            )
        except Exception:
            _log.exception(
                "im_assist classification failed", extra={"message_id": message_id}
            )

    def _suggestion_payload(self, row: IMSuggestionRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "message_id": row.message_id,
            "kind": row.kind,
            "confidence": row.confidence,
            "targets": row.targets or [],
            "proposal": row.proposal,
            "reasoning": row.reasoning,
            "status": row.status,
            "outcome": row.outcome,
            "attempts": row.attempts,
            "created_at": row.created_at.isoformat(),
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }

    async def get_suggestion(self, suggestion_id: str) -> dict | None:
        async with session_scope(self._sessionmaker) as session:
            row = await IMSuggestionRepository(session).get(suggestion_id)
            if row is None:
                return None
            return self._suggestion_payload(row)

    async def list_for_project(
        self, project_id: str, *, limit: int = 100
    ) -> list[dict]:
        async with session_scope(self._sessionmaker) as session:
            # Tied to messages, so we read via message iteration.
            messages = await MessageRepository(session).list_recent(
                project_id, limit=limit
            )
            suggestions: list[IMSuggestionRow] = []
            for m in messages:
                row = await IMSuggestionRepository(session).get_for_message(m.id)
                if row is not None:
                    suggestions.append(row)
            return [self._suggestion_payload(s) for s in suggestions]

    async def accept(
        self,
        *,
        suggestion_id: str,
        actor_id: str,
    ) -> dict:
        async with session_scope(self._sessionmaker) as session:
            row = await IMSuggestionRepository(session).get(suggestion_id)
            if row is None:
                return {"ok": False, "error": "suggestion_not_found"}
            if row.status != "pending":
                return {"ok": False, "error": "already_resolved"}

            project_id = row.project_id
            applied = await self._apply_proposal(session, row)

            await IMSuggestionRepository(session).resolve(suggestion_id, "accepted")
            refreshed = await IMSuggestionRepository(session).get(suggestion_id)
            payload = self._suggestion_payload(refreshed) if refreshed else None

        await self._event_bus.emit(
            "im_suggestion.resolved",
            {
                "suggestion_id": suggestion_id,
                "status": "accepted",
                "actor_id": actor_id,
                "applied": applied,
                "project_id": project_id,
            },
        )
        if payload is not None:
            await self._hub.publish(
                project_id,
                {"type": "suggestion", "payload": payload},
            )
        if applied.get("graph_touched"):
            await self._hub.publish(
                project_id, {"type": "graph", "payload": {"reason": "im_accept"}}
            )
        return {"ok": True, "applied": applied, "suggestion": payload}

    async def dismiss(self, *, suggestion_id: str, actor_id: str) -> dict:
        async with session_scope(self._sessionmaker) as session:
            row = await IMSuggestionRepository(session).get(suggestion_id)
            if row is None:
                return {"ok": False, "error": "suggestion_not_found"}
            if row.status != "pending":
                return {"ok": False, "error": "already_resolved"}
            project_id = row.project_id
            await IMSuggestionRepository(session).resolve(suggestion_id, "dismissed")
            refreshed = await IMSuggestionRepository(session).get(suggestion_id)
            payload = self._suggestion_payload(refreshed) if refreshed else None
        await self._event_bus.emit(
            "im_suggestion.resolved",
            {
                "suggestion_id": suggestion_id,
                "status": "dismissed",
                "actor_id": actor_id,
                "project_id": project_id,
            },
        )
        if payload is not None:
            await self._hub.publish(
                project_id, {"type": "suggestion", "payload": payload}
            )
        return {"ok": True, "suggestion": payload}

    async def _apply_proposal(
        self, session, row: IMSuggestionRow
    ) -> dict[str, Any]:
        """Execute the proposal in `row`. Idempotent where possible.

        Returns a dict describing what actually changed. Graph-touching
        actions set `graph_touched=True` so the caller can rebroadcast.
        """
        proposal = row.proposal or {}
        action = proposal.get("action") if isinstance(proposal, dict) else None
        detail = proposal.get("detail", {}) if isinstance(proposal, dict) else {}

        if row.kind == "blocker" or action == "open_risk":
            project_id = row.project_id
            req = await RequirementRepository(session).latest_for_project(project_id)
            if req is None:
                return {"ok": False, "error": "no_requirement"}
            existing_count = len(
                await ProjectGraphRepository(session).list_risks(req.id)
            )
            title = detail.get("title") if isinstance(detail, dict) else None
            severity = (
                detail.get("severity", "medium") if isinstance(detail, dict) else "medium"
            )
            risk_title = (title or row.reasoning or "IM-reported blocker")[:480]
            risk_content = proposal.get("summary", "") if isinstance(proposal, dict) else ""
            new_row = RiskRow(
                id=_new_uuid(),
                project_id=project_id,
                requirement_id=req.id,
                sort_order=existing_count,
                title=risk_title,
                content=risk_content,
                severity=severity if severity in {"low", "medium", "high"} else "medium",
                status="open",
            )
            session.add(new_row)
            await session.flush()
            return {
                "ok": True,
                "graph_touched": True,
                "risk_id": new_row.id,
                "action": "open_risk",
            }

        if action == "drop_deliverable":
            deliverable_id = (
                detail.get("deliverable_id") if isinstance(detail, dict) else None
            )
            if not deliverable_id:
                return {"ok": False, "error": "missing_deliverable_id"}
            deliverable = (
                await session.execute(
                    select(DeliverableRow).where(DeliverableRow.id == deliverable_id)
                )
            ).scalar_one_or_none()
            if deliverable is None:
                return {"ok": False, "error": "deliverable_not_found"}
            deliverable.status = "dropped"
            await session.flush()
            return {
                "ok": True,
                "graph_touched": True,
                "deliverable_id": deliverable.id,
                "action": "drop_deliverable",
            }

        if action == "mark_task_done":
            task_id = detail.get("task_id") if isinstance(detail, dict) else None
            if not task_id:
                return {"ok": False, "error": "missing_task_id"}
            task = (
                await session.execute(select(TaskRow).where(TaskRow.id == task_id))
            ).scalar_one_or_none()
            if task is None:
                return {"ok": False, "error": "task_not_found"}
            task.status = "done"
            await session.flush()
            return {
                "ok": True,
                "graph_touched": True,
                "task_id": task.id,
                "action": "mark_task_done",
            }

        if action == "update_constraint":
            constraint_id = (
                detail.get("constraint_id") if isinstance(detail, dict) else None
            )
            new_status = (
                detail.get("status", "resolved") if isinstance(detail, dict) else "resolved"
            )
            if not constraint_id:
                return {"ok": False, "error": "missing_constraint_id"}
            constraint = (
                await session.execute(
                    select(ConstraintRow).where(ConstraintRow.id == constraint_id)
                )
            ).scalar_one_or_none()
            if constraint is None:
                return {"ok": False, "error": "constraint_not_found"}
            constraint.status = new_status
            await session.flush()
            return {
                "ok": True,
                "graph_touched": True,
                "constraint_id": constraint.id,
                "action": "update_constraint",
            }

        # tag or `none` kinds have nothing to apply.
        return {"ok": True, "graph_touched": False, "action": action or "noop"}


def _new_uuid() -> str:
    # Local import to avoid circular concerns.
    from uuid import uuid4

    return str(uuid4())


__all__ = ["IMService", "MIN_WORDS_FOR_CLASSIFICATION"]
