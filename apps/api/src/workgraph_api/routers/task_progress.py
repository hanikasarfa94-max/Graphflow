"""Task progress endpoints — Phase U.

  POST /api/tasks/{task_id}/status
      Owner-or-assignee transitions task status. Body: {new_status, note?}.

  POST /api/tasks/{task_id}/score
      Project-owner scores a done task. Body: {quality, feedback?}.

  GET  /api/tasks/{task_id}/history
      Status timeline + score (if any). Project-member-only.

Permissions live in the service layer; this router translates
TaskProgressError codes into HTTP statuses.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    TaskProgressError,
    TaskProgressService,
)


router = APIRouter(tags=["task-progress"])


_CODE_TO_STATUS: dict[str, int] = {
    "task_not_found": 404,
    "no_assignee": 400,
    "invalid_status": 400,
    "invalid_quality": 400,
    "invalid_transition": 400,
    "not_done": 400,
    "canceled_task": 400,
    "forbidden": 403,
}


def _raise_from(err: TaskProgressError) -> None:
    raise HTTPException(
        status_code=_CODE_TO_STATUS.get(err.code, 400), detail=err.code
    )


def _service(request: Request) -> TaskProgressService:
    return request.app.state.task_progress_service


class StatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_status: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=2000)


class ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quality: str = Field(min_length=1, max_length=16)
    feedback: str | None = Field(default=None, max_length=2000)


@router.post("/api/tasks/{task_id}/status")
async def post_status(
    task_id: str,
    body: StatusRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.update_status(
            task_id=task_id,
            actor_user_id=user.id,
            new_status=body.new_status,
            note=body.note,
        )
    except TaskProgressError as err:
        _raise_from(err)


@router.post("/api/tasks/{task_id}/score")
async def post_score(
    task_id: str,
    body: ScoreRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.score_completion(
            task_id=task_id,
            reviewer_user_id=user.id,
            quality=body.quality,
            feedback=body.feedback,
        )
    except TaskProgressError as err:
        _raise_from(err)


@router.get("/api/tasks/{task_id}/history")
async def get_history(
    task_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.history(task_id=task_id, viewer_user_id=user.id)
    except TaskProgressError as err:
        _raise_from(err)
