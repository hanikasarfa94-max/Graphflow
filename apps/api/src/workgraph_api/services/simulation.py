"""Simulation service — counterfactual "what if?" on the graph.

The product bet: decisions are the atomic unit, and the graph is the
group's shared modal substrate. Slack / Lark / Wukong render what IS
(messages, docs) and at best what WAS (retrieval). Simulation renders
what COULD BE — the blast radius of a hypothetical mutation —
without committing the mutation.

v1 supports one scenario: `drop_task`. Given a task_id, compute:

  * `orphan_tasks`   — tasks whose only upstream path ran through the
                       dropped task (transitive close of TaskDependency
                       graph). These would lose their entry-point if
                       the drop happened.
  * `slipping_milestones` — milestones whose related_task_ids include
                       the dropped task or any orphaned task.
  * `exposed_deliverables` — deliverables the dropped task anchored
                       to whose remaining task coverage would be the
                       empty set. (If a deliverable has 5 tasks and
                       we drop 1, it's not exposed; if we drop the
                       only task, it is.)
  * `at_risk_commitments` — commitments whose scope_ref points at any
                       affected entity (orphaned task, exposed
                       deliverable, slipping milestone). The
                       commitment isn't automatically broken — it
                       just becomes harder to believe.

The response is a pure read: no writes, no event emissions. The
frontend uses it to render a dim-and-highlight overlay on the live
graph. To commit the mutation the user goes through the normal write
paths (IM accept, decision apply). v2 adds more scenarios
(reassign_owner, delay_milestone_by_N_days).

Scope boundary deliberately narrow: we do NOT simulate risk-opening,
LLM re-planning, or budget recomputation. Keep the computation
cheap + deterministic so the frontend can invoke on every hover
without blowing token budgets.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    CommitmentRepository,
    DeliverableRow,
    MilestoneRow,
    PlanRepository,
    RequirementRepository,
    TaskDependencyRow,
    TaskRow,
    session_scope,
)

_log = logging.getLogger("workgraph.api.simulation")


SimKind = Literal["drop_task"]


@dataclass(frozen=True)
class Affected:
    id: str
    kind: str
    title: str
    # Free-form "why was this affected" for the card. Kept short.
    reason: str


@dataclass(frozen=True)
class SimulationResult:
    kind: SimKind
    entity_kind: str
    entity_id: str
    # `dropped` is the entity itself. Always a list of 1 for drop_task;
    # kept as a list for forward-compat with multi-entity scenarios.
    dropped: list[Affected]
    orphan_tasks: list[Affected] = field(default_factory=list)
    slipping_milestones: list[Affected] = field(default_factory=list)
    exposed_deliverables: list[Affected] = field(default_factory=list)
    at_risk_commitments: list[Affected] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "entity_kind": self.entity_kind,
            "entity_id": self.entity_id,
            "dropped": [self._ser(a) for a in self.dropped],
            "orphan_tasks": [self._ser(a) for a in self.orphan_tasks],
            "slipping_milestones": [self._ser(a) for a in self.slipping_milestones],
            "exposed_deliverables": [self._ser(a) for a in self.exposed_deliverables],
            "at_risk_commitments": [self._ser(a) for a in self.at_risk_commitments],
            "total_blast_radius": (
                len(self.orphan_tasks)
                + len(self.slipping_milestones)
                + len(self.exposed_deliverables)
                + len(self.at_risk_commitments)
            ),
        }

    @staticmethod
    def _ser(a: Affected) -> dict[str, Any]:
        return {
            "id": a.id,
            "kind": a.kind,
            "title": a.title,
            "reason": a.reason,
        }


class SimulationError(Exception):
    """Raised when the simulation input is semantically invalid (unknown
    kind, entity not in project, etc.). Routers translate to HTTP 422."""


class SimulationService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def simulate(
        self,
        *,
        project_id: str,
        kind: str,
        entity_kind: str,
        entity_id: str,
    ) -> SimulationResult:
        if kind != "drop_task":
            raise SimulationError(
                f"unknown simulation kind: {kind!r} (expected drop_task)"
            )
        if entity_kind != "task":
            raise SimulationError(
                f"drop_task only supports entity_kind='task', got {entity_kind!r}"
            )

        async with session_scope(self._sessionmaker) as session:
            # Resolve the task + its project membership in one hop.
            task = (
                await session.execute(
                    select(TaskRow).where(
                        TaskRow.id == entity_id,
                        TaskRow.project_id == project_id,
                    )
                )
            ).scalar_one_or_none()
            if task is None:
                raise SimulationError(
                    "task not found in this project"
                )

            # Fetch the whole plan + graph once — iterating them in
            # Python beats N round-trips for the traversal below.
            req_repo = RequirementRepository(session)
            req = await req_repo.latest_for_project(project_id)
            if req is None:
                # No requirement = empty plan; trivial simulation.
                return SimulationResult(
                    kind="drop_task",
                    entity_kind="task",
                    entity_id=entity_id,
                    dropped=[
                        Affected(
                            id=task.id,
                            kind="task",
                            title=task.title or "",
                            reason="dropped",
                        )
                    ],
                )
            plan_data = await PlanRepository(session).list_all(req.id)
            all_tasks: list[TaskRow] = plan_data.get("tasks", [])
            all_deps: list[TaskDependencyRow] = plan_data.get(
                "dependencies", []
            )
            all_milestones: list[MilestoneRow] = plan_data.get(
                "milestones", []
            )

            # Build an adjacency for transitive-downstream traversal.
            # `down[x]` = direct successors (from_task_id=x → to_task_id).
            down: dict[str, set[str]] = {}
            for dep in all_deps:
                down.setdefault(dep.from_task_id, set()).add(dep.to_task_id)
            # Reverse for the "only-path-through-X" check: a task Y is
            # orphaned iff every predecessor of Y is transitively
            # downstream of (or equal to) the dropped task X.
            up: dict[str, set[str]] = {}
            for dep in all_deps:
                up.setdefault(dep.to_task_id, set()).add(dep.from_task_id)

            # Transitive close: tasks reachable from `entity_id`.
            reachable: set[str] = set()
            stack = [entity_id]
            while stack:
                cur = stack.pop()
                for succ in down.get(cur, ()):
                    if succ not in reachable:
                        reachable.add(succ)
                        stack.append(succ)

            # An orphan is a reachable task whose every predecessor is
            # itself in reachable ∪ {dropped}. If any predecessor lies
            # outside, it still has a live upstream path and doesn't
            # orphan.
            orphan_ids: set[str] = set()
            dropped_set = {entity_id}
            for tid in reachable:
                preds = up.get(tid, set())
                if preds and preds.issubset(reachable | dropped_set):
                    orphan_ids.add(tid)

            task_by_id = {t.id: t for t in all_tasks}

            # Deliverables: exposed only when the dropped + orphan
            # tasks together comprise the entire task set anchored to
            # that deliverable (i.e., the deliverable loses 100%
            # coverage).
            deliverable_tasks: dict[str, list[TaskRow]] = {}
            for t in all_tasks:
                if t.deliverable_id:
                    deliverable_tasks.setdefault(
                        t.deliverable_id, []
                    ).append(t)
            exposed_deliverable_ids: set[str] = set()
            removed = dropped_set | orphan_ids
            for del_id, ts in deliverable_tasks.items():
                if not ts:
                    continue
                if all(t.id in removed for t in ts):
                    exposed_deliverable_ids.add(del_id)

            exposed_deliverables_rows: list[DeliverableRow] = []
            if exposed_deliverable_ids:
                exposed_deliverables_rows = list(
                    (
                        await session.execute(
                            select(DeliverableRow).where(
                                DeliverableRow.id.in_(exposed_deliverable_ids)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

            # Milestones: slip when any of their related_task_ids is in
            # `removed`. related_task_ids is JSON + nullable — handle
            # both.
            slipping_milestones: list[MilestoneRow] = []
            for m in all_milestones:
                related = m.related_task_ids or []
                if any(tid in removed for tid in related):
                    slipping_milestones.append(m)

            # Commitments: anchored to any affected entity.
            affected_scope_ids = (
                removed | exposed_deliverable_ids
                | {m.id for m in slipping_milestones}
            )
            cm_rows = await CommitmentRepository(session).list_for_project(
                project_id, status="open", limit=200
            )
            at_risk_commitments = [
                c
                for c in cm_rows
                if c.scope_ref_id and c.scope_ref_id in affected_scope_ids
            ]

        dropped = [
            Affected(
                id=task.id,
                kind="task",
                title=task.title or "",
                reason="dropped",
            )
        ]
        orphan_tasks = [
            Affected(
                id=task_by_id[tid].id,
                kind="task",
                title=task_by_id[tid].title or "",
                reason="lost upstream path",
            )
            for tid in sorted(orphan_ids)
            if tid in task_by_id
        ]
        exposed = [
            Affected(
                id=d.id,
                kind="deliverable",
                title=d.title or "",
                reason="no remaining task coverage",
            )
            for d in exposed_deliverables_rows
        ]
        slipping = [
            Affected(
                id=m.id,
                kind="milestone",
                title=m.title or "",
                reason="milestone's tasks dropped / orphaned",
            )
            for m in slipping_milestones
        ]
        at_risk = [
            Affected(
                id=c.id,
                kind="commitment",
                title=c.headline or "",
                reason=f"scope anchor ({c.scope_ref_kind}) affected",
            )
            for c in at_risk_commitments
        ]
        return SimulationResult(
            kind="drop_task",
            entity_kind="task",
            entity_id=entity_id,
            dropped=dropped,
            orphan_tasks=orphan_tasks,
            slipping_milestones=slipping,
            exposed_deliverables=exposed,
            at_risk_commitments=at_risk,
        )


__all__ = ["SimulationService", "SimulationError", "SimulationResult"]
