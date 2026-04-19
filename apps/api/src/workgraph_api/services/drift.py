"""Drift detection service — vision.md §5.8.

Orchestrates the DriftAgent:
  1. gather — pull the project's committed thesis (latest requirement
     text as v1 proxy per vision.md §5.2 which is still pending), recent
     decisions, active tasks, recent completed deliverables, and the
     member pool the agent uses as the `affected_user_ids` candidate set.
  2. rate-limit — 60-second per-project lockout. `check_project` returns
     a `rate_limited` error shape if the last successful run happened
     more recently than the lockout window. Prevents runaway LLM cost
     on an endpoint intended for manual/admin trigger (auto-schedule is
     v2.5).
  3. call — DriftAgent.check(context) → DriftCheckResult.
  4. post — for every drift_item with severity ≥ medium, post an ambient
     signal message (kind="drift-alert", linked_id=project_id, body=
     drift_item JSON) into each affected user's personal project stream.
     Low-severity items are logged in the agent-run row but suppressed
     from streams (surface-noise protection per the agent prompt contract).
  5. observe — append one AgentRunLogRow per check so cost/latency show
     up in the health dashboard.

Drift alerts are NOT persisted in a dedicated table per the plan — they
live as MessageRow entries with kind="drift-alert". The body is the
drift_item JSON; the DriftCard frontend parses it to render the card.
`linked_id` stores the project_id so downstream (recent-for-project
endpoint) can filter cheaply.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents.drift import DriftAgent, DriftItem
from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    AgentRunLogRepository,
    AssignmentRepository,
    DecisionRepository,
    MessageRow,
    PlanRepository,
    ProjectGraphRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRepository,
    StreamRow,
    UserRepository,
    session_scope,
)

from .streams import StreamService

_log = logging.getLogger("workgraph.api.drift")

# 60-second per-project lockout. The vision.md §5.8 story is "checks on day
# 2" — there's no user-visible reason to drift-check the same project more
# than once a minute. Auto-schedule is v2.5; today this is a manual trigger
# that needs a guard against a double-click or a tight admin loop.
DRIFT_RATE_LIMIT_SECONDS = 60

# Only severities at or above this get fanned out as in-stream cards. The
# agent prompt is instructed to still emit low-severity items so the
# observability log captures them.
_SURFACEABLE_SEVERITIES = {"medium", "high"}


class DriftService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        agent: DriftAgent,
        stream_service: StreamService,
        *,
        rate_limit_seconds: int = DRIFT_RATE_LIMIT_SECONDS,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._agent = agent
        self._streams = stream_service
        self._rate_limit_seconds = rate_limit_seconds
        # Per-project last-check timestamp (monotonic seconds). Kept in
        # memory — the endpoint is intended for manual trigger, and in a
        # single-instance deploy a memory counter is simpler than adding
        # a new table. Multi-instance deploys would move this to Redis.
        self._last_check: dict[str, float] = {}
        self._last_check_lock = asyncio.Lock()

    async def check_project(
        self,
        project_id: str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Run a drift check. Returns a dict:
          {"ok": True, "alerts_posted": N, "result": DriftCheckResult-dict}
          {"ok": False, "error": "rate_limited", "retry_after_s": n}
          {"ok": False, "error": "project_not_found"}
          {"ok": False, "error": "requirement_not_ready"}
        """
        # Rate-limit first — cheap guard before any IO.
        now = time.monotonic()
        async with self._last_check_lock:
            last = self._last_check.get(project_id)
            if last is not None and (now - last) < self._rate_limit_seconds:
                remaining = max(
                    1, int(self._rate_limit_seconds - (now - last))
                )
                return {
                    "ok": False,
                    "error": "rate_limited",
                    "retry_after_s": remaining,
                }
            # Claim the slot pre-emptively. If the subsequent IO fails we
            # still hold the lockout — this is the conservative choice for
            # LLM cost protection.
            self._last_check[project_id] = now

        # Gather context.
        context = await self._gather(project_id)
        if context is None:
            return {"ok": False, "error": "project_not_found"}
        if context.get("_no_requirement"):
            return {"ok": False, "error": "requirement_not_ready"}

        effective_trace_id = trace_id or get_trace_id()

        # Call the agent.
        outcome = await self._agent.check(context)

        # Log the run for the dashboard (same shape as every other agent).
        async with session_scope(self._sessionmaker) as session:
            await AgentRunLogRepository(session).append(
                agent="drift",
                prompt_version=self._agent.prompt_version,
                project_id=project_id,
                trace_id=effective_trace_id,
                outcome=outcome.outcome,
                attempts=outcome.attempts,
                latency_ms=outcome.result.latency_ms,
                prompt_tokens=outcome.result.prompt_tokens,
                completion_tokens=outcome.result.completion_tokens,
                cache_read_tokens=outcome.result.cache_read_tokens,
                error=outcome.error,
            )

        result = outcome.result_payload
        alerts_posted = 0

        # Fan out surfaceable items into each affected user's personal
        # stream. Deliberately serial — drift checks are rare, and keeping
        # order predictable helps the frontend poll resolve cleanly.
        if result.has_drift and result.drift_items:
            member_ids = {
                m["user_id"] for m in context.get("members", [])
            }
            for item in result.drift_items:
                if item.severity not in _SURFACEABLE_SEVERITIES:
                    continue
                recipients = [
                    uid
                    for uid in (item.affected_user_ids or [])
                    if uid in member_ids
                ]
                # If the agent didn't name recipients (or none are in the
                # member pool), skip — we refuse to broadcast to everyone
                # since that defeats the "targeted early warning" design.
                if not recipients:
                    continue
                body = _encode_drift_body(item, project_id=project_id)
                for user_id in recipients:
                    try:
                        stream_payload = (
                            await self._streams.ensure_personal_stream(
                                user_id=user_id, project_id=project_id
                            )
                        )
                        stream_id = stream_payload["stream_id"]
                        post = await self._streams.post_system_message(
                            stream_id=stream_id,
                            author_id=EDGE_AGENT_SYSTEM_USER_ID,
                            body=body,
                            kind="drift-alert",
                            linked_id=project_id,
                        )
                        if post.get("ok"):
                            alerts_posted += 1
                    except Exception:  # pragma: no cover - defensive
                        _log.exception(
                            "drift alert post failed",
                            extra={
                                "project_id": project_id,
                                "user_id": user_id,
                            },
                        )

        await self._event_bus.emit(
            "drift.checked",
            {
                "project_id": project_id,
                "has_drift": result.has_drift,
                "drift_count": len(result.drift_items),
                "alerts_posted": alerts_posted,
                "outcome": outcome.outcome,
                "trace_id": effective_trace_id,
            },
        )

        return {
            "ok": True,
            "alerts_posted": alerts_posted,
            "has_drift": result.has_drift,
            "drift_items": [item.model_dump() for item in result.drift_items],
            "reasoning": result.reasoning,
            "outcome": outcome.outcome,
        }

    async def recent_for_project(
        self,
        project_id: str,
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return the last N drift-alert messages across users for a project.

        Used by the lightweight dashboard endpoint. Returns parsed drift
        items (decoded from the message body) with author + timestamp,
        not the raw MessageRow shape — callers don't need the stream_id
        plumbing here.
        """
        async with session_scope(self._sessionmaker) as session:
            # Pull personal-stream messages with kind=drift-alert scoped to
            # the project. We JOIN through StreamRow.project_id rather than
            # MessageRow.project_id because personal-stream messages are
            # stored with the stream's project_id on the MessageRow already,
            # but filtering by stream type keeps DM/project streams out.
            stmt = (
                select(MessageRow, StreamRow)
                .join(StreamRow, StreamRow.id == MessageRow.stream_id)
                .where(
                    MessageRow.kind == "drift-alert",
                    MessageRow.linked_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.project_id == project_id,
                )
                .order_by(desc(MessageRow.created_at))
                .limit(limit)
            )
            rows = list((await session.execute(stmt)).all())
            user_repo = UserRepository(session)
            owner_map: dict[str, str] = {}
            for _msg, stream in rows:
                if stream.owner_user_id and stream.owner_user_id not in owner_map:
                    u = await user_repo.get(stream.owner_user_id)
                    if u is not None:
                        owner_map[stream.owner_user_id] = (
                            u.display_name or u.username
                        )

        out: list[dict[str, Any]] = []
        for msg, stream in rows:
            parsed = _decode_drift_body(msg.body)
            out.append(
                {
                    "id": msg.id,
                    "project_id": project_id,
                    "recipient_user_id": stream.owner_user_id,
                    "recipient_display_name": owner_map.get(
                        stream.owner_user_id or "", ""
                    ),
                    "drift_item": parsed,
                    "created_at": msg.created_at.isoformat()
                    if msg.created_at
                    else None,
                }
            )
        return out

    # ---- internals ------------------------------------------------------

    async def _gather(self, project_id: str) -> dict[str, Any] | None:
        """Build the DriftAgent context.

        Returns None when the project doesn't exist. Returns a dict with
        `_no_requirement=True` when the project exists but has no
        requirement row yet (caller maps to 'requirement_not_ready').
        """
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return None

            req = await RequirementRepository(session).latest_for_project(
                project_id
            )
            if req is None:
                return {"_no_requirement": True}

            # v1 proxy for "committed thesis": the latest requirement text.
            # Once thesis-commit (§5.2) ships, the service swaps to
            # ThesisRepository.latest_for_project and drops this comment.
            committed_thesis = req.raw_text or ""

            decisions = await DecisionRepository(session).list_for_project(
                project_id, limit=20
            )

            plan_repo = PlanRepository(session)
            tasks = await plan_repo.list_tasks(req.id)
            # "Active" is open + in_progress; done tasks are history.
            active_tasks = [
                t for t in tasks if t.status in ("open", "in_progress")
            ]

            assignments = await AssignmentRepository(session).list_for_project(
                project_id
            )
            assignment_by_task = {a.task_id: a.user_id for a in assignments}

            graph_repo = ProjectGraphRepository(session)
            deliverables = await graph_repo.list_deliverables(req.id)
            # "Recently completed" — status=done in v1. (No completed_at
            # column on _GraphEntityBase, so we trust status.)
            completed_deliverables = [
                d for d in deliverables if d.status == "done"
            ]

            pm_repo = ProjectMemberRepository(session)
            members_rows = await pm_repo.list_for_project(project_id)
            user_repo = UserRepository(session)
            members: list[dict[str, Any]] = []
            for m in members_rows:
                if m.user_id == EDGE_AGENT_SYSTEM_USER_ID:
                    continue
                u = await user_repo.get(m.user_id)
                if u is None:
                    continue
                members.append(
                    {
                        "user_id": u.id,
                        "username": u.username,
                        "display_name": u.display_name or u.username,
                        "role": m.role,
                    }
                )

        return {
            "project_id": project_id,
            "title": project.title,
            "committed_thesis": committed_thesis,
            "recent_decisions": [
                {
                    "id": d.id,
                    "option_index": d.option_index,
                    "custom_text": d.custom_text,
                    "rationale": d.rationale,
                    "apply_outcome": d.apply_outcome,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "resolver_id": d.resolver_id,
                }
                for d in decisions
            ],
            "active_tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "status": t.status,
                    "assignee_role": t.assignee_role,
                    "assignee_user_id": assignment_by_task.get(t.id),
                }
                for t in active_tasks
            ],
            "recent_completed_deliverables": [
                {"id": d.id, "title": d.title, "kind": d.kind}
                for d in completed_deliverables
            ],
            "members": members,
        }


def _encode_drift_body(item: DriftItem, *, project_id: str) -> str:
    """Serialize a DriftItem into the MessageRow body.

    We embed project_id too so the frontend card can render a jump-to-
    project link without cross-referencing linked_id.
    """
    payload = item.model_dump()
    payload["project_id"] = project_id
    return json.dumps(payload, ensure_ascii=False)


def _decode_drift_body(body: str) -> dict[str, Any]:
    """Decode a drift-alert message body. Returns an empty dict if the
    body is not a JSON object (e.g. legacy rows or corruption).
    """
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


__all__ = ["DriftService", "DRIFT_RATE_LIMIT_SECONDS"]
