"""Shell v-Next stream-context endpoints (spec §11 E-5).

E-5: AgentFlow's analysisCard "关联任务" needs the related-entity slice
for a given stream — tasks / decisions / risks scoped to the stream's
project. v1 returns project-wide entities; the spec's optional "anchor
message" tighter-slice is deferred until the v-Next shell ships.

  GET /api/vnext/streams/{stream_id}/related
    → { tasks: [{id, title, status, scope}], decisions: [{id, title, status}],
        risks: [{id, title, severity}] }
    Empty lists when the stream has no project (通用 Agent / DM).

Membership gate: the viewer must be a member of the stream (and, for
project-anchored streams, of the project). Returns 403 otherwise. The
gate uses StreamMemberRepository — no new repo methods.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from workgraph_persistence import (
    DecisionRow,
    RiskRow,
    StreamMemberRepository,
    StreamRepository,
    TaskRow,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser

router = APIRouter(prefix="/api/vnext", tags=["vnext-streams"])


def _decision_title(row: DecisionRow) -> str:
    """DecisionRow has either option_index or custom_text. For the
    related-entities card we want a short label — prefer custom_text,
    fall back to a generated label."""
    if row.custom_text:
        return row.custom_text[:120]
    if row.option_index is not None:
        return f"Option {row.option_index + 1}"
    return "Decision"


@router.get("/streams/{stream_id}/related")
async def get_related_for_stream(
    stream_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    user: AuthenticatedUser = Depends(require_user),
) -> dict:
    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        stream_repo = StreamRepository(session)
        member_repo = StreamMemberRepository(session)

        stream = await stream_repo.get(stream_id)
        if stream is None:
            raise HTTPException(status_code=404, detail="stream_not_found")

        is_member = await member_repo.is_member(
            stream_id=stream_id, user_id=user.id
        )
        if not is_member:
            raise HTTPException(status_code=403, detail="not_a_member")

        # 通用 Agent / DM streams have no project context — there's
        # nothing to relate to. Empty payload (not an error) so the FE
        # can render "no analysis" without special-casing the kind.
        if stream.project_id is None:
            return {"tasks": [], "decisions": [], "risks": []}

        # Tasks — both 'plan' (canonical) and 'personal' (the viewer's
        # own self-set tasks). Filter personal to owner=viewer to match
        # the visibility rule used elsewhere.
        task_stmt = (
            select(TaskRow)
            .where(TaskRow.project_id == stream.project_id)
            .where(
                (TaskRow.scope == "plan")
                | (
                    (TaskRow.scope == "personal")
                    & (TaskRow.owner_user_id == user.id)
                )
            )
            .order_by(TaskRow.created_at.desc())
            .limit(limit)
        )
        tasks = list((await session.execute(task_stmt)).scalars().all())

        decision_stmt = (
            select(DecisionRow)
            .where(DecisionRow.project_id == stream.project_id)
            .order_by(DecisionRow.created_at.desc())
            .limit(limit)
        )
        decisions = list((await session.execute(decision_stmt)).scalars().all())

        risk_stmt = (
            select(RiskRow)
            .where(RiskRow.project_id == stream.project_id)
            .order_by(RiskRow.created_at.desc())
            .limit(limit)
        )
        risks = list((await session.execute(risk_stmt)).scalars().all())

        return {
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "scope": t.scope,
                    "assignee_role": t.assignee_role,
                }
                for t in tasks
            ],
            "decisions": [
                {
                    "id": d.id,
                    "title": _decision_title(d),
                    "outcome": d.apply_outcome,
                    "decision_class": d.decision_class,
                }
                for d in decisions
            ],
            "risks": [
                {
                    "id": r.id,
                    "title": r.title,
                    "severity": r.severity,
                    "status": r.status,
                }
                for r in risks
            ],
        }
