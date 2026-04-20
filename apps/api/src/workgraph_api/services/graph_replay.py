"""Sprint 1b — Time-cursor reconstruction for `/graph-at?ts=`.

Given a project and a past timestamp, rebuild the graph as it existed at
that moment. The shape mirrors /state closely enough that GraphCanvas
can swap the payload in place without client-side reshaping.

Reconstruction rules per entity kind:

  * Nodes (goal / deliverable / task / risk): include if `created_at <= ts`.
    Status is derived by replaying StatusTransitionRow — the most recent
    transition with `changed_at <= ts` wins. If there are no transitions
    for that entity at `ts`, the current row's status is assumed
    unchanged since creation. This is the pragmatic v1 compromise — we
    don't have a historical backfill of entity-creation statuses, so
    pre-first-transition snapshots reflect "the status as of creation."
    In practice every newly-created entity is 'open' and almost no
    pre-enablement data will ever be scrubbed back to, so this matches
    the demo story.

  * Dependencies (TaskDependencyRow): include if `created_at <= ts`. No
    mutation log needed — dependencies are append-only in v1.

  * Decisions: include if `created_at <= ts`. No historical apply_outcome
    reconstruction — if a decision was applied later, the replay just
    shows it as pending. Close enough for the demo.

  * Conflicts: include if `created_at <= ts`. Status is derived from
    existing timing columns (`resolved_at` + `status`) without touching
    the transition log — ConflictRow was already time-indexed.

  * Milestones / constraints: include if `created_at <= ts`. Status
    replayed same as nodes.

The endpoint is read-only and membership-gated at the router layer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    ClarificationQuestionRepository,
    ConflictRow,
    ConstraintRow,
    DecisionRow,
    DeliverableRow,
    GoalRow,
    MilestoneRow,
    ProjectRow,
    RequirementRepository,
    RiskRow,
    StatusTransitionRepository,
    TaskDependencyRow,
    TaskRow,
    session_scope,
)

_log = logging.getLogger("workgraph.api.graph_replay")


def _aware(dt: datetime | None) -> datetime | None:
    """Coerce a datetime to tz-aware UTC.

    SQLite returns DateTime(timezone=True) columns as naive values (the
    dialect strips the zone on read). Postgres preserves them. We always
    coerce to aware-UTC so Python-level `<=` comparisons with the
    incoming `ts` (always aware via _parse_iso_ts in the router) don't
    raise TypeError.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class GraphReplayService:
    """Read-only historical graph reconstruction.

    Holds no state; each call opens a fresh session. The service doesn't
    live on `app.state` as a dedicated slot because it owns no collaborator
    wiring — instantiate per-request via the router.
    """

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def graph_at(
        self, project_id: str, ts: datetime
    ) -> dict[str, Any] | None:
        """Reconstruct the project's graph as of `ts`.

        Returns a dict with the same top-level keys as `/state` for the
        subset the time-cursor cares about. Unknown project → None.
        """
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return None

            # Status map: entity_id → last new_status at or before ts.
            # Iterate oldest → newest so the last write wins.
            transitions = await StatusTransitionRepository(
                session
            ).list_for_project_up_to(project_id, upto=ts)
            status_at_ts: dict[str, str] = {}
            for tr in transitions:
                status_at_ts[tr.entity_id] = tr.new_status

            # Walk the latest requirement. We don't try to reconstruct
            # "which requirement version was latest at ts" — that would
            # require keeping a requirement-version history index we
            # don't have. For v1 we take the latest requirement and
            # filter its rows by created_at. If a v2 requirement was
            # promoted after ts, its rows simply won't be included.
            requirement_version = 0
            graph: dict[str, list[dict[str, Any]]] = {
                "goals": [],
                "deliverables": [],
                "constraints": [],
                "risks": [],
            }
            plan: dict[str, list[dict[str, Any]]] = {
                "tasks": [],
                "dependencies": [],
                "milestones": [],
            }

            req = await RequirementRepository(session).latest_for_project(
                project_id
            )
            if req is not None and _aware(req.created_at) <= ts:
                requirement_version = req.version
                goals = (
                    await session.execute(
                        select(GoalRow)
                        .where(
                            GoalRow.requirement_id == req.id,
                            GoalRow.created_at <= ts,
                        )
                        .order_by(GoalRow.sort_order)
                    )
                ).scalars().all()
                deliverables = (
                    await session.execute(
                        select(DeliverableRow)
                        .where(
                            DeliverableRow.requirement_id == req.id,
                            DeliverableRow.created_at <= ts,
                        )
                        .order_by(DeliverableRow.sort_order)
                    )
                ).scalars().all()
                constraints = (
                    await session.execute(
                        select(ConstraintRow)
                        .where(
                            ConstraintRow.requirement_id == req.id,
                            ConstraintRow.created_at <= ts,
                        )
                        .order_by(ConstraintRow.sort_order)
                    )
                ).scalars().all()
                risks = (
                    await session.execute(
                        select(RiskRow)
                        .where(
                            RiskRow.requirement_id == req.id,
                            RiskRow.created_at <= ts,
                        )
                        .order_by(RiskRow.sort_order)
                    )
                ).scalars().all()
                tasks = (
                    await session.execute(
                        select(TaskRow)
                        .where(
                            TaskRow.requirement_id == req.id,
                            TaskRow.created_at <= ts,
                        )
                        .order_by(TaskRow.sort_order)
                    )
                ).scalars().all()
                # Dependencies: edge is valid only if both endpoints
                # existed at ts. We filter by edge.created_at first (fast
                # index hit), then cross-check the task set locally.
                task_ids_at_ts = {t.id for t in tasks}
                dep_rows = (
                    await session.execute(
                        select(TaskDependencyRow)
                        .where(
                            TaskDependencyRow.requirement_id == req.id,
                            TaskDependencyRow.created_at <= ts,
                        )
                        .order_by(TaskDependencyRow.created_at)
                    )
                ).scalars().all()
                milestones = (
                    await session.execute(
                        select(MilestoneRow)
                        .where(
                            MilestoneRow.requirement_id == req.id,
                            MilestoneRow.created_at <= ts,
                        )
                        .order_by(MilestoneRow.sort_order)
                    )
                ).scalars().all()

                def historical_status(entity_id: str, current: str) -> str:
                    # If we have a transition at or before ts, use it.
                    # Otherwise fall back to current (pragmatic v1
                    # assumption: pre-first-transition == creation).
                    return status_at_ts.get(entity_id, current)

                graph["goals"] = [
                    {
                        "id": g.id,
                        "title": g.title,
                        "description": g.description,
                        "success_criteria": g.success_criteria,
                        "status": historical_status(g.id, g.status),
                    }
                    for g in goals
                ]
                graph["deliverables"] = [
                    {
                        "id": d.id,
                        "title": d.title,
                        "kind": d.kind,
                        "status": historical_status(d.id, d.status),
                    }
                    for d in deliverables
                ]
                graph["constraints"] = [
                    {
                        "id": c.id,
                        "kind": c.kind,
                        "content": c.content,
                        "severity": c.severity,
                        "status": historical_status(c.id, c.status),
                    }
                    for c in constraints
                ]
                graph["risks"] = [
                    {
                        "id": r.id,
                        "title": r.title,
                        "content": r.content,
                        "severity": r.severity,
                        "status": historical_status(r.id, r.status),
                    }
                    for r in risks
                ]
                plan["tasks"] = [
                    {
                        "id": t.id,
                        "title": t.title,
                        "description": t.description,
                        "deliverable_id": t.deliverable_id,
                        "assignee_role": t.assignee_role,
                        "estimate_hours": t.estimate_hours,
                        "acceptance_criteria": t.acceptance_criteria,
                        "status": historical_status(t.id, t.status),
                    }
                    for t in tasks
                ]
                plan["dependencies"] = [
                    {
                        "id": d.id,
                        "from_task_id": d.from_task_id,
                        "to_task_id": d.to_task_id,
                    }
                    for d in dep_rows
                    if d.from_task_id in task_ids_at_ts
                    and d.to_task_id in task_ids_at_ts
                ]
                plan["milestones"] = [
                    {
                        "id": m.id,
                        "title": m.title,
                        "target_date": m.target_date,
                        "related_task_ids": m.related_task_ids or [],
                        "status": historical_status(m.id, m.status),
                    }
                    for m in milestones
                ]
                clar_rows = await ClarificationQuestionRepository(
                    session
                ).list_for_requirement(req.id)
                clarifications = [
                    {
                        "id": c.id,
                        "position": c.position,
                        "question": c.question,
                        "answer": c.answer,
                    }
                    for c in clar_rows
                    if _aware(c.created_at) <= ts
                ]
            else:
                clarifications = []

            # Decisions: simple `created_at <= ts` slice. apply_outcome
            # isn't replayed — if the decision was applied later than ts,
            # the replay just shows whatever the current row carries. The
            # time-cursor is primarily about node status + existence, not
            # audit fidelity of downstream application.
            decision_rows = (
                await session.execute(
                    select(DecisionRow)
                    .where(
                        DecisionRow.project_id == project_id,
                        DecisionRow.created_at <= ts,
                    )
                    .order_by(DecisionRow.created_at.desc())
                )
            ).scalars().all()
            decisions = [
                {
                    "id": d.id,
                    "conflict_id": d.conflict_id,
                    "source_suggestion_id": d.source_suggestion_id,
                    "project_id": d.project_id,
                    "resolver_id": d.resolver_id,
                    "option_index": d.option_index,
                    "custom_text": d.custom_text,
                    "rationale": d.rationale,
                    "apply_actions": d.apply_actions or [],
                    "apply_outcome": d.apply_outcome,
                    "apply_detail": d.apply_detail or {},
                    "created_at": d.created_at.isoformat()
                    if d.created_at
                    else None,
                    # applied_at shown only if it's also <= ts; otherwise
                    # the decision is still "pending" at that instant.
                    "applied_at": d.applied_at.isoformat()
                    if d.applied_at and _aware(d.applied_at) <= ts
                    else None,
                }
                for d in decision_rows
            ]

            # Conflicts: `created_at <= ts`. If `resolved_at > ts` (or
            # unresolved), treat as open at that moment.
            conflict_rows = (
                await session.execute(
                    select(ConflictRow)
                    .where(
                        ConflictRow.project_id == project_id,
                        ConflictRow.created_at <= ts,
                    )
                    .order_by(ConflictRow.created_at.desc())
                )
            ).scalars().all()
            conflicts = []
            for c in conflict_rows:
                was_resolved_at_ts = (
                    c.resolved_at is not None and _aware(c.resolved_at) <= ts
                )
                status_at = c.status if was_resolved_at_ts else "open"
                conflicts.append(
                    {
                        "id": c.id,
                        "project_id": c.project_id,
                        "rule": c.rule,
                        "severity": c.severity,
                        "status": status_at,
                        "targets": c.targets or [],
                        "detail": c.detail or {},
                        "summary": c.summary,
                        "options": c.options or [],
                        "explanation_outcome": c.explanation_outcome,
                        "explanation_prompt_version": c.explanation_prompt_version,
                        "resolved_option_index": c.resolved_option_index
                        if was_resolved_at_ts
                        else None,
                        "resolved_by": c.resolved_by
                        if was_resolved_at_ts
                        else None,
                        "created_at": c.created_at.isoformat()
                        if c.created_at
                        else None,
                        "updated_at": c.updated_at.isoformat()
                        if c.updated_at
                        else None,
                        "resolved_at": c.resolved_at.isoformat()
                        if was_resolved_at_ts and c.resolved_at
                        else None,
                    }
                )

            # Summary: only open conflicts at ts count toward severity totals.
            summary = {"open": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}
            for c in conflicts:
                if c["status"] == "open":
                    summary["open"] += 1
                    sev = (c["severity"] or "").lower()
                    if sev in summary:
                        summary[sev] += 1

        return {
            "project": {"id": project.id, "title": project.title},
            "requirement_version": requirement_version,
            # `parsed` + `parse_outcome` aren't time-scoped in v1 (the
            # latest requirement's parsed_json is used everywhere). We
            # echo empty values so GraphCanvas doesn't have to branch.
            "parsed": {},
            "parse_outcome": None,
            "graph": graph,
            "plan": plan,
            "clarifications": clarifications,
            # Assignments + members aren't time-scoped in v1 — the
            # timeline cursor is strictly about graph nodes + decisions +
            # conflicts. We echo empty arrays to keep the shape stable.
            "assignments": [],
            "members": [],
            "conflicts": conflicts,
            "conflict_summary": summary,
            "decisions": decisions,
            "delivery": None,
            # Extra field the time-cursor UI can use to label the pill.
            "as_of": ts.isoformat(),
        }


__all__ = ["GraphReplayService"]
