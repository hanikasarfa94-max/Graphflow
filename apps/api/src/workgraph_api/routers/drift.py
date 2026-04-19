"""Drift detection endpoints — vision.md §5.8.

Routes:
  POST /api/projects/{project_id}/drift/check    — trigger a drift check.
                                                   Returns
                                                   {alerts_posted: N, ...}.
  GET  /api/projects/{project_id}/drift/recent   — last 5 drift alerts
                                                   across users for the
                                                   project.

Both require membership. The POST is intended for manual trigger (admin
or cron-style external call). Auto-schedule is v2.5 — v1 is manual.

Rate-limiting lives in DriftService (60s per-project lockout). The
router translates rate_limited into HTTP 429 so the frontend can back
off.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    DriftService,
    ProjectService,
)

router = APIRouter(prefix="/api/projects", tags=["drift"])


def _get_service(request: Request) -> DriftService:
    return request.app.state.drift_service


@router.post("/{project_id}/drift/check")
async def post_drift_check(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    from workgraph_observability import get_trace_id

    service = _get_service(request)
    result = await service.check_project(
        project_id=project_id, trace_id=get_trace_id()
    )
    if not result.get("ok"):
        err = result.get("error", "check_failed")
        if err == "rate_limited":
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "rate_limited",
                    "retry_after_s": result.get("retry_after_s", 0),
                },
            )
        status_map = {
            "project_not_found": 404,
            "requirement_not_ready": 409,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result


@router.get("/{project_id}/drift/recent")
async def get_drift_recent(
    project_id: str,
    request: Request,
    limit: int = Query(default=5, ge=1, le=50),
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service = _get_service(request)
    alerts = await service.recent_for_project(project_id, limit=limit)
    return {"alerts": alerts}
