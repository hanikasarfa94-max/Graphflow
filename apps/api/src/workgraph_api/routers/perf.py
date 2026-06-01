"""Team performance router — observable performance management (§10.5).

One endpoint: `GET /api/projects/{project_id}/team/perf`. Project-admin
(owner + full tier) only; every other role gets 403 with a stable
detail string the frontend can render inline.

The panel is intentionally project-scoped. There is no org layer yet,
so there's nothing to aggregate across. See docs/north-star.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser
from workgraph_api.services.perf_aggregation import PerfAggregationService

router = APIRouter(tags=["perf"])


# ---- response shapes (C1-C) -----------------------------------------------
# Mirror the per-member record assembled in PerfAggregationService.team_perf.
# No FE consumer — pure additive contract. The {count, ids} shape recurs 5x →
# one reusable CountWithIds. quality_index is float | None (null when total==0).


class CountWithIds(BaseModel):
    count: int
    ids: list[str]


class TaskQuality(BaseModel):
    good: int
    ok: int
    needs_work: int
    total: int
    quality_index: float | None = None


class SkillsValidated(BaseModel):
    declared: int
    observed: int
    overlap: int


class DissentAccuracy(BaseModel):
    total: int
    supported: int
    refuted: int
    still_open: int


class ActivityLast30d(BaseModel):
    messages: int
    last_active_at: str | None = None


class TeamMemberPerf(BaseModel):
    user_id: str
    display_name: str
    username: str
    role_in_project: str
    license_tier: str
    decisions_made: CountWithIds
    routings_answered: CountWithIds
    risks_owned: CountWithIds
    tasks_completed: CountWithIds
    task_quality: TaskQuality
    skills_validated: SkillsValidated
    dissent_accuracy: DissentAccuracy
    silent_consensus_ratified: CountWithIds
    activity_last_30d: ActivityLast30d


@router.get(
    "/api/projects/{project_id}/team/perf",
    response_model=list[TeamMemberPerf],
)
async def get_team_perf(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> list[dict]:
    service: PerfAggregationService = request.app.state.perf_service
    if not await service.is_project_admin(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(
            status_code=403, detail="project admin access required"
        )
    return await service.team_perf(project_id=project_id)
