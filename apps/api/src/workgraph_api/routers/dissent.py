"""Dissent router — Phase 2.A.

Endpoints:
  * POST /api/projects/{project_id}/decisions/{decision_id}/dissents
      body { stance_text } — authenticated member only; upserts on
      (decision_id, dissenter_user_id).
  * GET  /api/projects/{project_id}/decisions/{decision_id}/dissents
      list all dissents on a decision.
  * GET  /api/projects/{project_id}/users/{user_id}/dissents
      list a member's dissents across the project (self or owner only).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    ProjectService,
)
from workgraph_api.services.dissent import (
    MAX_STANCE_CHARS,
    DissentService,
)

router = APIRouter(tags=["dissent"])


class RecordDissentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stance_text: str = Field(min_length=1, max_length=MAX_STANCE_CHARS)


_ERROR_STATUS: dict[str, int] = {
    "stance_empty": 400,
    "stance_too_long": 400,
    "not_a_member": 403,
    "forbidden": 403,
    "decision_not_in_project": 404,
}


def _handle(result: dict) -> dict:
    if not result.get("ok"):
        err = result.get("error") or "unknown"
        raise HTTPException(
            status_code=_ERROR_STATUS.get(err, 400), detail=err
        )
    return result


@router.post(
    "/api/projects/{project_id}/decisions/{decision_id}/dissents"
)
async def post_record_dissent(
    project_id: str,
    decision_id: str,
    body: RecordDissentRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    service: DissentService = request.app.state.dissent_service
    return _handle(
        await service.record(
            project_id=project_id,
            decision_id=decision_id,
            dissenter_user_id=user.id,
            stance_text=body.stance_text,
        )
    )


@router.get(
    "/api/projects/{project_id}/decisions/{decision_id}/dissents"
)
async def get_decision_dissents(
    project_id: str,
    decision_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    service: DissentService = request.app.state.dissent_service
    return _handle(
        await service.list_for_decision(
            project_id=project_id, decision_id=decision_id
        )
    )


@router.get(
    "/api/projects/{project_id}/users/{user_id}/dissents"
)
async def get_user_dissents(
    project_id: str,
    user_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service: DissentService = request.app.state.dissent_service
    return _handle(
        await service.list_for_user_in_project(
            project_id=project_id,
            user_id=user_id,
            viewer_user_id=user.id,
        )
    )
