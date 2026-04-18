"""Conflict service — Phase 8 (PLAN.md line 629).

Runs the rule engine against the current project graph, persists matches
via ConflictRepository (idempotent on fingerprint), and backfills each new
or reopened conflict with an LLM-generated explanation. On each detection
pass, any previously-open conflict whose fingerprint no longer fires is
flipped to `stale` — dismissed/resolved rows stay put.

Explanation is best-effort: if the agent times out or fails its parse
ladder, the row keeps its manual_review fallback and the UI renders the
raw rule detail anyway. We never block the graph write on the LLM.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import (
    ConflictExplanationAgent,
    GraphSnapshot,
    RuleMatch,
    detect_all,
)
from workgraph_domain import EventBus
from workgraph_persistence import (
    AgentRunLogRepository,
    AssignmentRepository,
    ConflictRepository,
    ConflictRow,
    PlanRepository,
    ProjectGraphRepository,
    ProjectRow,
    RequirementRepository,
    session_scope,
)

from .collab_hub import CollabHub

_log = logging.getLogger("workgraph.api.conflicts")

# Ranking for list ordering — DB can't sort "high > medium" textually.
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class ConflictService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
        agent: ConflictExplanationAgent,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub
        self._agent = agent
        self._pending: set[asyncio.Task] = set()

    async def drain(self) -> None:
        # Recheck spawns a backfill task mid-flight, so one gather pass can
        # miss it. Loop until the set is stable + empty.
        while self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    def kick_recheck(
        self, project_id: str, *, trace_id: str | None = None
    ) -> asyncio.Task:
        """Fire-and-forget recheck — used by write-path hooks.

        The task is tracked so shutdown drain + tests can await it.
        Exceptions are logged and swallowed; they never propagate to the
        hot-path request.
        """

        async def _run() -> None:
            try:
                await self.recheck(project_id, trace_id=trace_id)
            except Exception:
                _log.exception(
                    "conflict recheck (fire-and-forget) failed",
                    extra={"project_id": project_id},
                )

        task = asyncio.create_task(
            _run(), name=f"conflict-recheck-{project_id[:8]}"
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return task

    # ---------- Public API -----------------------------------------------

    async def recheck(
        self,
        project_id: str,
        *,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Run rules + persist. Kicks off explanation backfill in background.

        Returns the current open-conflict list shape (post-upsert, pre-
        explanation-completion). Callers that need fresh summaries should
        re-read via list_for_project after the WS frame fires.
        """
        snapshot, project_snapshot = await self._build_snapshot(project_id)
        if snapshot is None:
            return {"ok": False, "error": "requirement_not_ready"}

        matches = detect_all(snapshot)
        new_rows: list[ConflictRow] = []
        refreshed_rows: list[ConflictRow] = []

        async with session_scope(self._sessionmaker) as session:
            repo = ConflictRepository(session)
            for m in matches:
                row, is_new = await repo.upsert(
                    project_id=project_id,
                    requirement_id=snapshot.requirement_id,
                    rule=m.rule,
                    severity=m.severity,
                    fingerprint=m.fingerprint,
                    targets=list(m.targets),
                    detail=dict(m.detail),
                    trace_id=trace_id,
                )
                (new_rows if is_new else refreshed_rows).append(row)
            stale_count = await repo.mark_stale(
                project_id, keep={m.fingerprint for m in matches}
            )
            open_rows = await repo.list_for_project(project_id)

        await self._event_bus.emit(
            "conflicts.rechecked",
            {
                "project_id": project_id,
                "match_count": len(matches),
                "new_count": len(new_rows),
                "refreshed_count": len(refreshed_rows),
                "stale_count": stale_count,
                "trace_id": trace_id,
            },
        )

        # Fire-and-forget explanation backfill for new rows. Refreshed rows
        # keep their prior summary — rerunning would burn tokens on the same
        # fingerprint. On first detection (outcome=="pending") we backfill.
        need_explanation = [
            r for r in (new_rows + refreshed_rows) if r.explanation_outcome == "pending"
        ]
        if need_explanation:
            task = asyncio.create_task(
                self._backfill_explanations(
                    project_id=project_id,
                    rows=need_explanation,
                    project_snapshot=project_snapshot,
                    trace_id=trace_id,
                ),
                name=f"conflict-backfill-{project_id[:8]}",
            )
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)

        payload = {
            "conflicts": [self._row_payload(r) for r in self._sorted(open_rows)],
            "summary": self._summarize(open_rows),
        }
        await self._hub.publish(
            project_id, {"type": "conflicts", "payload": payload}
        )
        return {
            "ok": True,
            "match_count": len(matches),
            "new_count": len(new_rows),
            "refreshed_count": len(refreshed_rows),
            "stale_count": stale_count,
            "conflicts": payload["conflicts"],
            "summary": payload["summary"],
        }

    async def list_for_project(
        self,
        project_id: str,
        *,
        include_closed: bool = False,
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            rows = await ConflictRepository(session).list_for_project(
                project_id, include_closed=include_closed
            )
        return {
            "conflicts": [self._row_payload(r) for r in self._sorted(rows)],
            "summary": self._summarize(rows),
        }

    async def resolve(
        self,
        *,
        conflict_id: str,
        actor_id: str,
        option_index: int | None,
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            repo = ConflictRepository(session)
            row = await repo.get(conflict_id)
            if row is None:
                return {"ok": False, "error": "conflict_not_found"}
            if row.status in ("resolved", "dismissed"):
                return {"ok": False, "error": "already_resolved"}
            if option_index is not None:
                opts = row.options or []
                if option_index < 0 or option_index >= len(opts):
                    return {"ok": False, "error": "option_out_of_range"}
            refreshed = await repo.resolve(
                conflict_id, user_id=actor_id, option_index=option_index
            )
            project_id = row.project_id
            payload = self._row_payload(refreshed) if refreshed else None

        await self._event_bus.emit(
            "conflict.resolved",
            {
                "conflict_id": conflict_id,
                "project_id": project_id,
                "actor_id": actor_id,
                "option_index": option_index,
            },
        )
        if payload is not None:
            await self._hub.publish(
                project_id, {"type": "conflict", "payload": payload}
            )
        return {"ok": True, "conflict": payload}

    async def dismiss(
        self, *, conflict_id: str, actor_id: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            repo = ConflictRepository(session)
            row = await repo.get(conflict_id)
            if row is None:
                return {"ok": False, "error": "conflict_not_found"}
            if row.status in ("resolved", "dismissed"):
                return {"ok": False, "error": "already_resolved"}
            refreshed = await repo.dismiss(conflict_id, user_id=actor_id)
            project_id = row.project_id
            payload = self._row_payload(refreshed) if refreshed else None

        await self._event_bus.emit(
            "conflict.dismissed",
            {
                "conflict_id": conflict_id,
                "project_id": project_id,
                "actor_id": actor_id,
            },
        )
        if payload is not None:
            await self._hub.publish(
                project_id, {"type": "conflict", "payload": payload}
            )
        return {"ok": True, "conflict": payload}

    # ---------- Internals -------------------------------------------------

    async def _build_snapshot(
        self, project_id: str
    ) -> tuple[GraphSnapshot | None, dict]:
        """Read-only pull of everything the rule engine needs.

        Returns (snapshot, project_snapshot_for_prompt). If the project has
        no requirement yet (pre-intake), returns (None, {}).
        """
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return None, {}
            req = await RequirementRepository(session).latest_for_project(project_id)
            if req is None:
                return None, {}

            graph_repo = ProjectGraphRepository(session)
            deliverables = await graph_repo.list_deliverables(req.id)
            constraints = await graph_repo.list_constraints(req.id)
            risks = await graph_repo.list_risks(req.id)
            goals = await graph_repo.list_goals(req.id)

            plan_repo = PlanRepository(session)
            tasks = await plan_repo.list_tasks(req.id)
            dependencies = await plan_repo.list_dependencies(req.id)
            milestones = await plan_repo.list_milestones(req.id)

            assignments = await AssignmentRepository(session).list_for_project(
                project_id
            )

        assignment_map: dict[str, list[str]] = {}
        for a in assignments:
            assignment_map.setdefault(a.task_id, []).append(a.user_id)

        snapshot = GraphSnapshot(
            project_id=project_id,
            requirement_id=req.id,
            goals=[{"id": g.id, "title": g.title} for g in goals],
            deliverables=[
                {
                    "id": d.id,
                    "title": d.title,
                    "kind": d.kind,
                    "status": d.status,
                }
                for d in deliverables
            ],
            constraints=[
                {
                    "id": c.id,
                    "kind": c.kind,
                    "content": c.content,
                    "severity": c.severity,
                    "status": c.status,
                }
                for c in constraints
            ],
            risks=[
                {
                    "id": r.id,
                    "title": r.title,
                    "content": r.content,
                    "severity": r.severity,
                    "status": r.status,
                }
                for r in risks
            ],
            tasks=[
                {
                    "id": t.id,
                    "title": t.title,
                    "estimate_hours": t.estimate_hours,
                    "assignee_role": t.assignee_role,
                    "deliverable_id": t.deliverable_id,
                    "status": t.status,
                }
                for t in tasks
            ],
            dependencies=[
                {"from_task_id": d.from_task_id, "to_task_id": d.to_task_id}
                for d in dependencies
            ],
            milestones=[
                {
                    "id": m.id,
                    "title": m.title,
                    "target_date": m.target_date,
                }
                for m in milestones
            ],
            assignments=assignment_map,
        )

        project_snapshot = {
            "id": project.id,
            "title": project.title,
            "goal": goals[0].title if goals else project.title,
            "deliverables": [
                {"id": d.id, "title": d.title, "kind": d.kind}
                for d in deliverables
            ],
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "estimate_hours": t.estimate_hours,
                    "assignee_role": t.assignee_role,
                    "deliverable_id": t.deliverable_id,
                }
                for t in tasks
            ],
            "risks": [
                {"id": r.id, "title": r.title, "severity": r.severity}
                for r in risks
            ],
            "milestones": [
                {
                    "id": m.id,
                    "title": m.title,
                    "target_date": m.target_date,
                }
                for m in milestones
            ],
            "constraints": [
                {"id": c.id, "kind": c.kind, "content": c.content}
                for c in constraints
            ],
        }
        return snapshot, project_snapshot

    async def _backfill_explanations(
        self,
        *,
        project_id: str,
        rows: list[ConflictRow],
        project_snapshot: dict,
        trace_id: str | None,
    ) -> None:
        """Run the explanation agent for each row and persist results.

        Errors on a single row don't abort the batch — the others get their
        summaries. A final WS frame publishes the fresh list so the UI
        re-renders.
        """
        for row in rows:
            try:
                outcome = await self._agent.explain(
                    rule=row.rule,
                    severity=row.severity,
                    detail=dict(row.detail or {}),
                    project=project_snapshot,
                    targets=list(row.targets or []),
                )
            except Exception:
                _log.exception(
                    "conflict explanation raised",
                    extra={"conflict_id": row.id, "rule": row.rule},
                )
                continue

            explanation = outcome.explanation
            async with session_scope(self._sessionmaker) as session:
                await ConflictRepository(session).attach_explanation(
                    row.id,
                    summary=explanation.summary,
                    options=[o.model_dump() for o in explanation.options],
                    prompt_version=self._agent.prompt_version,
                    outcome=outcome.outcome,
                )
                await AgentRunLogRepository(session).append(
                    agent="conflict_explanation",
                    prompt_version=self._agent.prompt_version,
                    project_id=project_id,
                    trace_id=trace_id,
                    outcome=outcome.outcome,
                    attempts=outcome.attempts,
                    latency_ms=outcome.result.latency_ms,
                    prompt_tokens=outcome.result.prompt_tokens,
                    completion_tokens=outcome.result.completion_tokens,
                    cache_read_tokens=outcome.result.cache_read_tokens,
                    error=outcome.error,
                )

        async with session_scope(self._sessionmaker) as session:
            open_rows = await ConflictRepository(session).list_for_project(project_id)
        payload = {
            "conflicts": [self._row_payload(r) for r in self._sorted(open_rows)],
            "summary": self._summarize(open_rows),
        }
        await self._hub.publish(
            project_id, {"type": "conflicts", "payload": payload}
        )

    def _sorted(self, rows: list[ConflictRow]) -> list[ConflictRow]:
        return sorted(
            rows,
            key=lambda r: (
                _SEVERITY_RANK.get(r.severity, 9),
                -(r.created_at.timestamp() if r.created_at else 0),
            ),
        )

    def _summarize(self, rows: list[ConflictRow]) -> dict[str, int]:
        open_rows = [r for r in rows if r.status == "open"]
        counts = {"open": len(open_rows)}
        for sev in ("critical", "high", "medium", "low"):
            counts[sev] = sum(1 for r in open_rows if r.severity == sev)
        return counts

    def _row_payload(self, row: ConflictRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "rule": row.rule,
            "severity": row.severity,
            "status": row.status,
            "targets": row.targets or [],
            "detail": row.detail or {},
            "summary": row.summary,
            "options": row.options or [],
            "explanation_outcome": row.explanation_outcome,
            "explanation_prompt_version": row.explanation_prompt_version,
            "resolved_option_index": row.resolved_option_index,
            "resolved_by": row.resolved_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }


__all__ = ["ConflictService"]
