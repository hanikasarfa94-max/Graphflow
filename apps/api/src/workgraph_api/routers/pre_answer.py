"""Pre-answer routing router.

POST /api/projects/{project_id}/pre-answer
  Body: { target_user_id, question }
  Returns the target's skill-anchored pre-answer so the sender can
  decide whether to still route the question. See
  services/pre_answer.py for full semantics.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, PreAnswerService, ProjectService

router = APIRouter(tags=["pre-answer"])


class PreAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: str = Field(min_length=1)
    question: str = Field(min_length=1, max_length=2000)


_ERROR_STATUS: dict[str, int] = {
    "empty_question": 400,
    "same_user": 400,
    "sender_not_member": 403,
    "target_not_member": 400,
    "target_not_found": 404,
    "rate_limited": 429,
}


@router.post("/api/projects/{project_id}/pre-answer")
async def post_pre_answer(
    project_id: str,
    body: PreAnswerRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    service: PreAnswerService = request.app.state.pre_answer_service
    result = await service.draft_pre_answer(
        project_id=project_id,
        sender_user_id=user.id,
        target_user_id=body.target_user_id,
        question=body.question,
    )
    if not result.get("ok"):
        err = result.get("error") or "unknown"
        raise HTTPException(
            status_code=_ERROR_STATUS.get(err, 400),
            detail=err,
        )
    return result
