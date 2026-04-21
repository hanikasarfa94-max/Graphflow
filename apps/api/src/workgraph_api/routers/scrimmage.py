"""Scrimmage router — Phase 2.B.

POST /api/projects/{project_id}/scrimmages
  Body: { target_user_id, question_text, routed_signal_id? }
  Runs the agent-vs-agent debate (2–3 turns), persists the transcript,
  and returns the finalized ScrimmageRow shape. On convergence the
  response includes a proposal_json + pending decision id. Only project
  members (specifically the source) may trigger a scrimmage.

GET /api/projects/{project_id}/scrimmages/{scrimmage_id}
  Fetch the persisted transcript. Visibility is enforced on source,
  target, and owner — all other viewers get 403.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    ProjectService,
    ScrimmageError,
    ScrimmageService,
)

router = APIRouter(tags=["scrimmage"])


class ScrimmageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: str = Field(min_length=1)
    question_text: str = Field(min_length=1, max_length=4000)
    routed_signal_id: str | None = None


_ERROR_STATUS: dict[str, int] = {
    "empty_question": 400,
    "same_user": 400,
    "source_not_member": 403,
    "target_not_member": 400,
    "not_found": 404,
    "forbidden": 403,
}


@router.post("/api/projects/{project_id}/scrimmages")
async def post_scrimmage(
    project_id: str,
    body: ScrimmageRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")

    service: ScrimmageService = request.app.state.scrimmage_service
    try:
        return await service.run_scrimmage(
            project_id=project_id,
            source_user_id=user.id,
            target_user_id=body.target_user_id,
            question=body.question_text,
            routed_signal_id=body.routed_signal_id,
        )
    except ScrimmageError as e:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(e.code, e.status),
            detail=e.code,
        ) from e


@router.get("/api/projects/{project_id}/scrimmages/{scrimmage_id}")
async def get_scrimmage(
    project_id: str,
    scrimmage_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")

    service: ScrimmageService = request.app.state.scrimmage_service
    try:
        payload = await service.get_scrimmage(
            scrimmage_id=scrimmage_id,
            viewer_user_id=user.id,
        )
    except ScrimmageError as e:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(e.code, e.status),
            detail=e.code,
        ) from e
    if payload.get("project_id") != project_id:
        # Scrimmage exists but not in the project path the caller used.
        raise HTTPException(status_code=404, detail="not_found")
    return payload
