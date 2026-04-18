"""Phase 10 — Delivery summary generation.

Flow:
  1. gather — pull the latest requirement + graph + plan + decisions +
     conflicts + assignments.
  2. QA pre-check — build a coverage map (scope_item → task_ids that
     mention it). If any scope item has NO coverage AND no decision
     deferring it, mark the whole run `manual_review`. The service
     still records the summary (so the UI has something to show) but
     flags `qa_report.uncovered_items` so callers can 409 if they
     want a strict gate.
  3. agent — invoke DeliveryAgent with the gathered context.
  4. persist — create DeliverySummaryRow snapshot.
  5. emit — `delivery.generated` (always) and, if QA flagged,
     `delivery.qa_failed`. Publish WS `delivery` frame.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import DeliveryAgent, DeliverySummaryDoc
from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    AgentRunLogRepository,
    AssignmentRepository,
    ConflictRepository,
    DecisionRepository,
    DeliverySummaryRepository,
    DeliverySummaryRow,
    PlanRepository,
    ProjectGraphRepository,
    ProjectRow,
    RequirementRepository,
    UserRepository,
    session_scope,
)

from .collab_hub import CollabHub

_log = logging.getLogger("workgraph.api.delivery")


class DeliveryError(Exception):
    """Raised for validation failures — mapped to 4xx by the router."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class DeliveryService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
        agent: DeliveryAgent,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub
        self._agent = agent

    async def generate(
        self,
        *,
        project_id: str,
        actor_id: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        context = await self._gather(project_id)
        if context is None:
            raise DeliveryError("project_not_ready", status=409)

        coverage = _build_coverage_map(
            scope_items=context["requirement"].get("scope_items") or [],
            tasks=context["plan"].get("tasks") or [],
        )
        deferred_decision_ids = _deferred_scope_items(
            decisions=context["decisions"],
            scope_items=context["requirement"].get("scope_items") or [],
        )
        uncovered = [
            item
            for item in (context["requirement"].get("scope_items") or [])
            if not coverage.get(item) and item not in deferred_decision_ids
        ]

        outcome = await self._agent.generate(
            requirement=context["requirement"],
            graph=context["graph"],
            plan=context["plan"],
            assignments=context["assignments"],
            decisions=context["decisions"],
            conflicts=context["conflicts"],
            covered_refs=coverage,
        )

        # QA verdict. An LLM-produced manual_review means the agent
        # bailed; an uncovered-items verdict means the graph is
        # incomplete. Either case marks the summary as manual_review.
        parse_outcome = outcome.outcome
        if uncovered and parse_outcome == "ok":
            parse_outcome = "manual_review"

        qa_report: dict[str, Any] = {
            "scope_items": context["requirement"].get("scope_items") or [],
            "covered": {k: v for k, v in coverage.items() if v},
            "uncovered": uncovered,
            "deferred_via_decision": sorted(deferred_decision_ids),
            "agent_outcome": outcome.outcome,
            "agent_attempts": outcome.attempts,
            "agent_error": outcome.error,
        }

        effective_trace_id = trace_id or get_trace_id()
        async with session_scope(self._sessionmaker) as session:
            row = await DeliverySummaryRepository(session).create(
                project_id=project_id,
                requirement_version=context["requirement_version"],
                content_json=outcome.doc.model_dump(mode="json"),
                parse_outcome=parse_outcome,
                qa_report=qa_report,
                prompt_version=self._agent.prompt_version,
                trace_id=effective_trace_id,
                created_by=actor_id,
            )
            payload = self._row_payload(row)

        async with session_scope(self._sessionmaker) as session:
            await AgentRunLogRepository(session).append(
                agent="delivery",
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

        await self._event_bus.emit(
            "delivery.generated",
            {
                "delivery_id": row.id,
                "project_id": project_id,
                "requirement_version": context["requirement_version"],
                "parse_outcome": parse_outcome,
                "covered": len(qa_report["covered"]),
                "uncovered": len(uncovered),
                "trace_id": effective_trace_id,
            },
        )
        if uncovered:
            await self._event_bus.emit(
                "delivery.qa_failed",
                {
                    "delivery_id": row.id,
                    "project_id": project_id,
                    "uncovered": uncovered,
                    "trace_id": effective_trace_id,
                },
            )
        await self._hub.publish(
            project_id, {"type": "delivery", "payload": payload}
        )
        return {"ok": True, "delivery": payload}

    async def latest_for_project(
        self, project_id: str
    ) -> dict[str, Any] | None:
        async with session_scope(self._sessionmaker) as session:
            row = await DeliverySummaryRepository(session).latest_for_project(
                project_id
            )
            return self._row_payload(row) if row is not None else None

    async def list_for_project(
        self, project_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            rows = await DeliverySummaryRepository(session).list_for_project(
                project_id, limit=limit
            )
            return [self._row_payload(r) for r in rows]

    # ---- internals ------------------------------------------------------

    async def _gather(self, project_id: str) -> dict[str, Any] | None:
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
                return None

            graph_repo = ProjectGraphRepository(session)
            goals = await graph_repo.list_goals(req.id)
            deliverables = await graph_repo.list_deliverables(req.id)
            constraints = await graph_repo.list_constraints(req.id)
            risks = await graph_repo.list_risks(req.id)

            plan_repo = PlanRepository(session)
            tasks = await plan_repo.list_tasks(req.id)
            dependencies = await plan_repo.list_dependencies(req.id)
            milestones = await plan_repo.list_milestones(req.id)

            assignments = await AssignmentRepository(session).list_for_project(
                project_id
            )
            user_ids = {a.user_id for a in assignments}
            user_map: dict[str, str] = {}
            if user_ids:
                user_repo = UserRepository(session)
                for uid in user_ids:
                    u = await user_repo.get(uid)
                    if u is not None:
                        user_map[uid] = u.display_name or u.username

            decisions = await DecisionRepository(session).list_for_project(
                project_id, limit=200
            )
            conflicts = await ConflictRepository(session).list_for_project(
                project_id, include_closed=True
            )

        return {
            "project": {"id": project.id, "title": project.title},
            "requirement_version": req.version,
            "requirement": dict(req.parsed_json or {}),
            "graph": {
                "goals": [{"id": g.id, "title": g.title} for g in goals],
                "deliverables": [
                    {
                        "id": d.id,
                        "title": d.title,
                        "kind": d.kind,
                        "status": d.status,
                    }
                    for d in deliverables
                ],
                "constraints": [
                    {
                        "id": c.id,
                        "kind": c.kind,
                        "content": c.content,
                        "severity": c.severity,
                        "status": c.status,
                    }
                    for c in constraints
                ],
                "risks": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "content": r.content,
                        "severity": r.severity,
                        "status": r.status,
                    }
                    for r in risks
                ],
            },
            "plan": {
                "tasks": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "description": t.description,
                        "deliverable_id": t.deliverable_id,
                        "status": t.status,
                        "acceptance_criteria": t.acceptance_criteria or [],
                    }
                    for t in tasks
                ],
                "dependencies": [
                    {
                        "id": d.id,
                        "from_task_id": d.from_task_id,
                        "to_task_id": d.to_task_id,
                    }
                    for d in dependencies
                ],
                "milestones": [
                    {
                        "id": m.id,
                        "title": m.title,
                        "target_date": m.target_date,
                        "related_task_ids": m.related_task_ids or [],
                        "status": m.status,
                    }
                    for m in milestones
                ],
            },
            "assignments": [
                {
                    "task_id": a.task_id,
                    "user_id": a.user_id,
                    "display_name": user_map.get(a.user_id, a.user_id),
                }
                for a in assignments
            ],
            "decisions": [
                {
                    "id": d.id,
                    "conflict_id": d.conflict_id,
                    "option_index": d.option_index,
                    "custom_text": d.custom_text,
                    "rationale": d.rationale,
                    "apply_outcome": d.apply_outcome,
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                }
                for d in decisions
            ],
            "conflicts": [
                {
                    "id": c.id,
                    "rule": c.rule,
                    "severity": c.severity,
                    "status": c.status,
                    "targets": list(c.targets or []),
                    "summary": c.summary or "",
                }
                for c in conflicts
            ],
        }

    def _row_payload(self, row: DeliverySummaryRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "requirement_version": row.requirement_version,
            "content": row.content_json or {},
            "parse_outcome": row.parse_outcome,
            "qa_report": row.qa_report or {},
            "prompt_version": row.prompt_version,
            "trace_id": row.trace_id,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


# ---- coverage helpers --------------------------------------------------


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 3}


def _build_coverage_map(
    *, scope_items: list[str], tasks: list[dict[str, Any]]
) -> dict[str, list[str]]:
    """Map each scope_item → task_ids whose title/description/AC covers it.

    Heuristic: a task "covers" a scope item if at least 50% of the
    meaningful tokens (len≥3, alphanumeric) in the scope_item appear in
    the task's title + description + acceptance_criteria. This is the
    pragmatic QA pre-check — tight enough to catch obviously-missing
    scope, loose enough to survive paraphrased task titles.
    """
    coverage: dict[str, list[str]] = {}
    for item in scope_items:
        item_tokens = _tokens(item)
        if not item_tokens:
            coverage[item] = []
            continue
        matches: list[str] = []
        for t in tasks:
            combined = " ".join(
                [
                    t.get("title") or "",
                    t.get("description") or "",
                    " ".join(t.get("acceptance_criteria") or []),
                ]
            )
            task_tokens = _tokens(combined)
            if not task_tokens:
                continue
            overlap = len(item_tokens & task_tokens)
            if overlap >= max(1, len(item_tokens) // 2):
                matches.append(t["id"])
        coverage[item] = matches
    return coverage


def _deferred_scope_items(
    *, decisions: list[Any], scope_items: list[str]
) -> set[str]:
    """Scope items that appear in a decision's custom_text + defer keyword.

    Treats the decision as the audit trail for conscious cuts. Keeps
    the logic symmetric with the agent's stub so the QA pre-check and
    narrative agree on what's deferred.
    """
    deferred: set[str] = set()
    for d in decisions:
        text = (
            d.custom_text
            if hasattr(d, "custom_text")
            else d.get("custom_text") or ""
        )
        if not text:
            continue
        lower = text.lower()
        if "defer" not in lower and "cut" not in lower and "drop" not in lower:
            continue
        for item in scope_items:
            if item.lower() in lower:
                deferred.add(item)
    return deferred


__all__ = ["DeliveryService", "DeliveryError"]
