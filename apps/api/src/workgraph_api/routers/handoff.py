"""Handoff router — Stage 3 skill succession.

Endpoints:
  * POST /api/projects/{project_id}/handoff/prepare      — owner-only
  * POST /api/handoff/{handoff_id}/finalize              — owner-only
  * GET  /api/projects/{project_id}/handoffs             — list
  * GET  /api/projects/{project_id}/handoffs/for/{user}  — successor fetch
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    HandoffService,
    ProjectService,
)

router = APIRouter(tags=["handoff"])


class PrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_user_id: str = Field(min_length=1)
    to_user_id: str = Field(min_length=1)


_ERROR_STATUS: dict[str, int] = {
    "same_user": 400,
    "not_owner": 403,
    "from_not_member": 400,
    "to_not_member": 400,
    "not_found": 404,
}


def _handle(result: dict) -> dict:
    if not result.get("ok"):
        err = result.get("error") or "unknown"
        raise HTTPException(
            status_code=_ERROR_STATUS.get(err, 400), detail=err
        )
    return result


@router.post("/api/projects/{project_id}/handoff/prepare")
async def post_handoff_prepare(
    project_id: str,
    body: PrepareRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    service: HandoffService = request.app.state.handoff_service
    return _handle(
        await service.prepare(
            project_id=project_id,
            from_user_id=body.from_user_id,
            to_user_id=body.to_user_id,
            viewer_user_id=user.id,
        )
    )


@router.post("/api/handoff/{handoff_id}/finalize")
async def post_handoff_finalize(
    handoff_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service: HandoffService = request.app.state.handoff_service
    return _handle(
        await service.finalize(
            handoff_id=handoff_id, viewer_user_id=user.id
        )
    )


@router.get("/api/projects/{project_id}/handoffs")
async def get_project_handoffs(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    service: HandoffService = request.app.state.handoff_service
    return await service.list_for_project(
        project_id=project_id, viewer_user_id=user.id
    )


@router.get("/api/projects/{project_id}/handoffs/for/{user_id}")
async def get_handoffs_for_successor(
    project_id: str,
    user_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    # A member may only inspect their own inherited routines unless
    # they are the project owner. Keeps the surface minimal.
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    if user.id != user_id:
        # Owner check
        service: HandoffService = request.app.state.handoff_service
        if not await service._is_owner(
            project_id=project_id, user_id=user.id
        ):
            raise HTTPException(
                status_code=403, detail="can only view own inherited routines"
            )
    service: HandoffService = request.app.state.handoff_service
    return await service.for_successor(
        project_id=project_id, user_id=user_id
    )
