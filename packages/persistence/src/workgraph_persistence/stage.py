"""Graph-native stage resolution (decision 1E).

Project stage is DERIVED from the graph state, never written as a column.
This file is the single source of truth for "what stage is this project in?"

Phase-by-phase expansion:
  Phase 4:        intake → clarification → ready_for_planning
  Phase 5 (here): + graph-built signal. ready_for_planning now also requires
                  Goal/Deliverable/Constraint rows on the latest requirement.
                  Graph-absent window after parse is surfaced as graph_building.
  Phase 6+:       + planning → synced → conflict → decided → delivered

The contract: every caller that wants a stage MUST go through `project_stage()`.
Grep `project_stage(` to find consumers; grep `current_stage =` to verify
no code path is writing a denormalized stage field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .orm import (
    ClarificationQuestionRow,
    ConstraintRow,
    DeliverableRow,
    GoalRow,
    MilestoneRow,
    ProjectRow,
    RequirementRow,
    RiskRow,
    TaskDependencyRow,
    TaskRow,
)

Stage = Literal[
    "intake",
    "clarification_pending",
    "clarification_in_progress",
    "graph_building",
    "ready_for_planning",
    "planned",
    "manual_review",
    "unknown",
]


@dataclass(slots=True)
class StageInfo:
    """Derived stage view over a project.

    `stage` is the name. The other fields carry the inputs that produced the
    decision so UI / events / debugging can show WHY we're in this stage.

    Phase 5 addition: `graph_counts` exposes per-kind entity counts on the
    latest requirement version. `ready_for_planning` requires graph_counts
    to be non-zero on goals/deliverables; otherwise the stage is
    `graph_building`.
    """

    project_id: str
    stage: Stage
    requirement_version: int
    parse_outcome: str | None
    total_questions: int
    answered_questions: int
    graph_counts: dict[str, int]
    plan_counts: dict[str, int]


async def project_stage(session: AsyncSession, project_id: str) -> StageInfo:
    """Compute the stage from graph state only. Never reads a stage column."""
    project = (
        await session.execute(select(ProjectRow).where(ProjectRow.id == project_id))
    ).scalar_one_or_none()
    empty_counts = {"goals": 0, "deliverables": 0, "constraints": 0, "risks": 0}
    empty_plan_counts = {"tasks": 0, "dependencies": 0, "milestones": 0}
    if project is None:
        return StageInfo(
            project_id=project_id,
            stage="unknown",
            requirement_version=0,
            parse_outcome=None,
            total_questions=0,
            answered_questions=0,
            graph_counts=empty_counts,
            plan_counts=empty_plan_counts,
        )

    latest_req = (
        await session.execute(
            select(RequirementRow)
            .where(RequirementRow.project_id == project_id)
            .order_by(RequirementRow.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest_req is None:
        # Project exists with no requirement. This should not happen in the
        # current intake flow, but we still return a meaningful stage.
        return StageInfo(
            project_id=project_id,
            stage="intake",
            requirement_version=0,
            parse_outcome=None,
            total_questions=0,
            answered_questions=0,
            graph_counts=empty_counts,
            plan_counts=empty_plan_counts,
        )

    questions = list(
        (
            await session.execute(
                select(ClarificationQuestionRow)
                .where(ClarificationQuestionRow.requirement_id == latest_req.id)
                .order_by(ClarificationQuestionRow.position)
            )
        )
        .scalars()
        .all()
    )
    total = len(questions)
    answered = sum(1 for q in questions if q.answer is not None)

    graph_counts = await _count_graph_entities(session, latest_req.id)
    plan_counts = await _count_plan_entities(session, latest_req.id)
    has_scope_entities = (
        graph_counts["goals"] > 0 and graph_counts["deliverables"] > 0
    )
    has_plan = plan_counts["tasks"] > 0

    if latest_req.parse_outcome == "manual_review":
        stage: Stage = "manual_review"
    elif total == 0:
        # No questions yet. If the requirement has been parsed, the clarifier
        # has not run OR the clarifier returned an empty batch. Either way,
        # planning can proceed — provided the graph has been built.
        if latest_req.parse_outcome is None:
            stage = "intake"
        elif has_plan:
            stage = "planned"
        elif has_scope_entities:
            stage = "ready_for_planning"
        else:
            # Parse ok but graph not yet projected. Inline-builder makes this
            # window near-zero in practice, but we surface it so async builders
            # in later phases can be observed.
            stage = "graph_building"
    elif answered < total:
        stage = (
            "clarification_pending"
            if answered == 0
            else "clarification_in_progress"
        )
    else:
        # All questions answered. The reply-merge flow creates v+1 with its
        # own parse + graph build, so if we reach this branch on v_current the
        # rebuild has not landed yet OR v+1 has zero open questions. Defer to
        # the graph presence to pick the right state.
        if has_plan:
            stage = "planned"
        elif has_scope_entities:
            stage = "ready_for_planning"
        else:
            stage = "graph_building"

    return StageInfo(
        project_id=project_id,
        stage=stage,
        requirement_version=latest_req.version,
        parse_outcome=latest_req.parse_outcome,
        total_questions=total,
        answered_questions=answered,
        graph_counts=graph_counts,
        plan_counts=plan_counts,
    )


async def _count_graph_entities(
    session: AsyncSession, requirement_id: str
) -> dict[str, int]:
    """Count entities bound to the given requirement version. Keeps stage.py
    self-contained without pulling in ProjectGraphRepository (which lives at
    the same layer but doesn't belong inside the stage contract)."""
    from sqlalchemy import func

    async def _count(model) -> int:
        stmt = select(func.count(model.id)).where(
            model.requirement_id == requirement_id
        )
        return int((await session.execute(stmt)).scalar_one())

    return {
        "goals": await _count(GoalRow),
        "deliverables": await _count(DeliverableRow),
        "constraints": await _count(ConstraintRow),
        "risks": await _count(RiskRow),
    }


async def _count_plan_entities(
    session: AsyncSession, requirement_id: str
) -> dict[str, int]:
    """Count plan rows bound to the given requirement version."""
    from sqlalchemy import func

    async def _count(model) -> int:
        stmt = select(func.count(model.id)).where(
            model.requirement_id == requirement_id
        )
        return int((await session.execute(stmt)).scalar_one())

    return {
        "tasks": await _count(TaskRow),
        "dependencies": await _count(TaskDependencyRow),
        "milestones": await _count(MilestoneRow),
    }
