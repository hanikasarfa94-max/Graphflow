"""Team performance router — observable performance management (§10.5).

One endpoint: `GET /api/projects/{project_id}/team/perf`. Project-admin
(owner + full tier) only; every other role gets 403 with a stable
detail string the frontend can render inline.

The panel is intentionally project-scoped. There is no org layer yet,
so there's nothing to aggregate across. See docs/north-star.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser
from workgraph_api.services.perf_aggregation import PerfAggregationService

router = APIRouter(tags=["perf"])


@router.get("/api/projects/{project_id}/team/perf")
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
