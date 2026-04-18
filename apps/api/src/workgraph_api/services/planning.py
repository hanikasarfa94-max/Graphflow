from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import (
    ParsedPlan,
    PlannedTask,
    PlanningAgent,
)
from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    AgentRunLogRepository,
    PlanRepository,
    ProjectGraphRepository,
    ProjectRow,
    RequirementRepository,
    session_scope,
)

from .clarification import ProjectNotFound

_log = logging.getLogger("workgraph.api.planning")


class PlanValidationError(Exception):
    """Raised when the LLM plan fails graph-level invariants.

    Code path: caught inside PlanningService and converted into a
    manual_review outcome — the endpoint still returns 200 so the caller
    learns what's wrong without a 500.
    """

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class NotReadyForPlanning(Exception):
    """Raised when the graph isn't available (e.g. parse=manual_review).

    Endpoint returns 409 Conflict with a clear reason.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PlanningService:
    """Phase 6 — produce + persist a delivery plan for the latest requirement.

    Flow:
      1) Read the graph (goal, deliverables, constraints, existing risks).
      2) Call PlanningAgent.plan() with the shaped input.
      3) Validate the plan:
           - every task.deliverable_ref resolves to a provided deliverable.id
           - every dependency endpoint resolves to a known task ref
           - no duplicate edges
           - no cycle (topological reachability)
           - every provided deliverable is covered by at least one task
      4) Persist tasks, dependencies, milestones via PlanRepository. New
         risks from the plan are appended to the existing graph via
         ProjectGraphRepository (they enrich the same requirement version).
      5) Emit `planning.produced` with counts + outcome + trace_id.
      6) Write agent_run_log (2C2).

    Idempotency matches /clarify and /graph: second call returns the
    already-persisted plan unchanged.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        agent: PlanningAgent | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._agent = agent or PlanningAgent()

    async def plan(self, project_id: str) -> dict[str, Any]:
        # 1) Verify project + load latest requirement + graph.
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                raise ProjectNotFound(project_id)

            latest_req = await RequirementRepository(session).latest_for_project(
                project_id
            )
            assert latest_req is not None, "project without requirement"

            plan_repo = PlanRepository(session)
            if await plan_repo.has_plan(latest_req.id):
                existing = await plan_repo.list_all(latest_req.id)
                return {
                    "project_id": project_id,
                    "requirement_id": latest_req.id,
                    "requirement_version": latest_req.version,
                    "outcome": "ok",
                    "regenerated": False,
                    **_serialize_plan(existing),
                }

            # Graph must exist to plan. manual_review parses skip Phase-5
            # build — surface that as a 409, not a silent empty plan.
            graph_repo = ProjectGraphRepository(session)
            graph = await graph_repo.list_all(latest_req.id)
            if not graph["deliverables"]:
                raise NotReadyForPlanning(
                    "no deliverables on latest requirement — run intake / "
                    "clarification to produce a graph first"
                )

            goal = graph["goals"][0].title if graph["goals"] else latest_req.raw_text[:120]
            deliverables_input = [
                {"id": d.id, "title": d.title, "kind": d.kind}
                for d in graph["deliverables"]
            ]
            constraints_input = [
                {
                    "id": c.id,
                    "kind": c.kind,
                    "content": c.content,
                    "severity": c.severity,
                }
                for c in graph["constraints"]
            ]
            existing_risks_input = [
                {"title": r.title, "content": r.content, "severity": r.severity}
                for r in graph["risks"]
            ]
            requirement_version = latest_req.version
            requirement_id = latest_req.id

        # 2) Call agent outside the DB session — network latency shouldn't
        # hold a write transaction open.
        outcome = await self._agent.plan(
            goal=goal,
            deliverables=deliverables_input,
            constraints=constraints_input,
            existing_risks=existing_risks_input,
        )

        # 3) Manual-review path skips validation + write; still emit event + log.
        if outcome.outcome == "manual_review" or len(outcome.plan.tasks) == 0:
            await self._log_run(
                project_id=project_id,
                outcome=outcome,
            )
            await self._event_bus.emit(
                "planning.produced",
                {
                    "project_id": project_id,
                    "requirement_id": requirement_id,
                    "requirement_version": requirement_version,
                    "prompt_version": self._agent.prompt_version,
                    "outcome": outcome.outcome if outcome.outcome == "manual_review" else "empty",
                    "attempts": outcome.attempts,
                    "task_count": 0,
                    "dependency_count": 0,
                    "milestone_count": 0,
                    "risk_count": 0,
                },
            )
            return {
                "project_id": project_id,
                "requirement_id": requirement_id,
                "requirement_version": requirement_version,
                "outcome": outcome.outcome if outcome.outcome == "manual_review" else "empty",
                "regenerated": True,
                "tasks": [],
                "dependencies": [],
                "milestones": [],
                "risks_added": [],
                "error": outcome.error,
            }

        # 4) Validate. Failures become manual_review — never 500.
        deliverable_ids = {d["id"] for d in deliverables_input}
        try:
            _validate_plan(outcome.plan, deliverable_ids)
        except PlanValidationError as e:
            _log.warning(
                "plan validation failed — manual review",
                extra={"project_id": project_id, "kind": e.kind, "detail": e.detail},
            )
            await self._log_run(
                project_id=project_id,
                outcome=outcome,
                override_outcome="manual_review",
                override_error=f"{e.kind}: {e.detail}",
            )
            await self._event_bus.emit(
                "planning.produced",
                {
                    "project_id": project_id,
                    "requirement_id": requirement_id,
                    "requirement_version": requirement_version,
                    "prompt_version": self._agent.prompt_version,
                    "outcome": "manual_review",
                    "reason": e.kind,
                    "attempts": outcome.attempts,
                    "task_count": 0,
                    "dependency_count": 0,
                    "milestone_count": 0,
                    "risk_count": 0,
                },
            )
            return {
                "project_id": project_id,
                "requirement_id": requirement_id,
                "requirement_version": requirement_version,
                "outcome": "manual_review",
                "regenerated": True,
                "error": f"{e.kind}: {e.detail}",
                "tasks": [],
                "dependencies": [],
                "milestones": [],
                "risks_added": [],
            }

        # 5) Persist plan + any new risks.
        tasks_payload = [
            {
                "ref": t.ref,
                "title": t.title,
                "description": t.description,
                "deliverable_id": t.deliverable_ref,
                "assignee_role": t.assignee_role,
                "estimate_hours": t.estimate_hours,
                "acceptance_criteria": t.acceptance_criteria,
            }
            for t in outcome.plan.tasks
        ]
        deps_payload = [
            {"from_ref": d.from_ref, "to_ref": d.to_ref}
            for d in outcome.plan.dependencies
        ]
        milestones_payload = [
            {
                "title": m.title,
                "target_date": m.target_date,
                "related_task_refs": m.related_task_refs,
            }
            for m in outcome.plan.milestones
        ]

        async with session_scope(self._sessionmaker) as session:
            persisted = await PlanRepository(session).append_plan(
                project_id=project_id,
                requirement_id=requirement_id,
                tasks=tasks_payload,
                dependencies=deps_payload,
                milestones=milestones_payload,
            )

            # Append new risks to the Phase-5 graph — they live alongside
            # existing risks on the same requirement version.
            risks_added = []
            if outcome.plan.risks:
                existing_risk_titles = {r["title"].strip().lower() for r in existing_risks_input}
                new_risks = [
                    {
                        "title": r.title,
                        "content": r.content,
                        "severity": r.severity,
                    }
                    for r in outcome.plan.risks
                    if r.title.strip().lower() not in existing_risk_titles
                ]
                if new_risks:
                    graph_repo = ProjectGraphRepository(session)
                    # Can't call append_for_requirement (it's idempotent-skip
                    # if entities exist). Append risks directly via the ORM
                    # keeping sort_order contiguous after existing ones.
                    from workgraph_persistence import RiskRow
                    existing_risk_rows = await graph_repo.list_risks(requirement_id)
                    start = len(existing_risk_rows)
                    for i, r in enumerate(new_risks):
                        row = RiskRow(
                            id=_new_id(),
                            project_id=project_id,
                            requirement_id=requirement_id,
                            sort_order=start + i,
                            title=r["title"],
                            content=r["content"],
                            severity=r["severity"],
                        )
                        session.add(row)
                        risks_added.append(r)
                    await session.flush()

            await AgentRunLogRepository(session).append(
                agent="planning",
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

            snapshot = _serialize_plan(persisted)

        await self._event_bus.emit(
            "planning.produced",
            {
                "project_id": project_id,
                "requirement_id": requirement_id,
                "requirement_version": requirement_version,
                "prompt_version": self._agent.prompt_version,
                "outcome": outcome.outcome,
                "attempts": outcome.attempts,
                "task_count": len(snapshot["tasks"]),
                "dependency_count": len(snapshot["dependencies"]),
                "milestone_count": len(snapshot["milestones"]),
                "risk_count": len(risks_added),
            },
        )

        return {
            "project_id": project_id,
            "requirement_id": requirement_id,
            "requirement_version": requirement_version,
            "outcome": outcome.outcome,
            "regenerated": True,
            "risks_added": risks_added,
            **snapshot,
        }

    async def _log_run(
        self,
        *,
        project_id: str,
        outcome,
        override_outcome: str | None = None,
        override_error: str | None = None,
    ) -> None:
        async with session_scope(self._sessionmaker) as session:
            await AgentRunLogRepository(session).append(
                agent="planning",
                prompt_version=self._agent.prompt_version,
                project_id=project_id,
                trace_id=get_trace_id(),
                outcome=override_outcome or outcome.outcome,
                attempts=outcome.attempts,
                latency_ms=outcome.result.latency_ms,
                prompt_tokens=outcome.result.prompt_tokens,
                completion_tokens=outcome.result.completion_tokens,
                cache_read_tokens=outcome.result.cache_read_tokens,
                error=override_error or outcome.error,
            )


# ---------- validation helpers --------------------------------------------


def _validate_plan(plan: ParsedPlan, deliverable_ids: set[str]) -> None:
    refs = {t.ref for t in plan.tasks}

    # Orphan-task: every task.deliverable_ref (if set) must map to a real deliverable.
    for t in plan.tasks:
        if t.deliverable_ref is not None and t.deliverable_ref not in deliverable_ids:
            raise PlanValidationError(
                "unknown_deliverable",
                f"task {t.ref} references deliverable {t.deliverable_ref} "
                f"which is not in the graph",
            )

    # Orphan-deliverable: every provided deliverable must be covered by at
    # least one task. This matches the prompt's hard rule.
    covered = {t.deliverable_ref for t in plan.tasks if t.deliverable_ref is not None}
    missing = deliverable_ids - covered
    if missing:
        raise PlanValidationError(
            "uncovered_deliverable",
            f"deliverables not covered by any task: {sorted(missing)}",
        )

    # Dependency endpoints must exist as task refs.
    for d in plan.dependencies:
        if d.from_ref not in refs:
            raise PlanValidationError(
                "unknown_task_ref",
                f"dependency from '{d.from_ref}' → '{d.to_ref}' uses unknown task",
            )
        if d.to_ref not in refs:
            raise PlanValidationError(
                "unknown_task_ref",
                f"dependency from '{d.from_ref}' → '{d.to_ref}' uses unknown task",
            )
        if d.from_ref == d.to_ref:
            raise PlanValidationError(
                "self_loop",
                f"dependency cannot point a task at itself: {d.from_ref}",
            )

    # Duplicate edges.
    seen_edges: set[tuple[str, str]] = set()
    for d in plan.dependencies:
        e = (d.from_ref, d.to_ref)
        if e in seen_edges:
            raise PlanValidationError(
                "duplicate_edge",
                f"duplicate dependency {d.from_ref} → {d.to_ref}",
            )
        seen_edges.add(e)

    # Cycle detection (Kahn's algorithm — if we can't remove every node, there's a cycle).
    adj: dict[str, list[str]] = {ref: [] for ref in refs}
    indeg: dict[str, int] = {ref: 0 for ref in refs}
    for d in plan.dependencies:
        adj[d.from_ref].append(d.to_ref)
        indeg[d.to_ref] += 1
    queue = [r for r, v in indeg.items() if v == 0]
    visited = 0
    while queue:
        n = queue.pop()
        visited += 1
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    if visited != len(refs):
        raise PlanValidationError(
            "cycle",
            "dependencies form a cycle; cannot determine execution order",
        )


def _serialize_plan(rows: dict[str, list]) -> dict[str, list]:
    return {
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "deliverable_id": t.deliverable_id,
                "assignee_role": t.assignee_role,
                "estimate_hours": t.estimate_hours,
                "acceptance_criteria": t.acceptance_criteria,
                "status": t.status,
                "sort_order": t.sort_order,
            }
            for t in rows["tasks"]
        ],
        "dependencies": [
            {"id": d.id, "from_task_id": d.from_task_id, "to_task_id": d.to_task_id}
            for d in rows["dependencies"]
        ],
        "milestones": [
            {
                "id": m.id,
                "title": m.title,
                "target_date": m.target_date,
                "related_task_ids": m.related_task_ids or [],
                "status": m.status,
                "sort_order": m.sort_order,
            }
            for m in rows["milestones"]
        ],
    }


def _new_id() -> str:
    from uuid import uuid4

    return str(uuid4())
