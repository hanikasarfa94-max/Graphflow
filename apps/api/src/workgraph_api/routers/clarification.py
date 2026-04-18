from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_persistence import project_stage, session_scope

from workgraph_api.deps import get_clarification_service
from workgraph_api.services import (
    ClarificationQuestionNotFound,
    ClarificationService,
    ProjectNotFound,
)

router = APIRouter(prefix="/api/projects", tags=["clarification"])


@router.get("/{project_id}/stage")
async def get_stage(project_id: str, request: Request) -> dict[str, Any]:
    """Graph-derived stage (decision 1E) — no `current_stage` column exists."""
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        info = await project_stage(session, project_id)
    if info.stage == "unknown":
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    return asdict(info)


@router.post("/{project_id}/clarify")
async def post_clarify(
    project_id: str,
    service: ClarificationService = Depends(get_clarification_service),
) -> dict[str, Any]:
    try:
        return await service.generate(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")


class ClarifyReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(min_length=1)
    answer: str = Field(min_length=1, max_length=4000)


@router.post("/{project_id}/clarify-reply")
async def post_clarify_reply(
    project_id: str,
    body: ClarifyReplyRequest,
    service: ClarificationService = Depends(get_clarification_service),
) -> dict[str, Any]:
    try:
        return await service.answer(
            project_id=project_id,
            question_id=body.question_id,
            answer=body.answer,
        )
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    except ClarificationQuestionNotFound:
        raise HTTPException(
            status_code=404, detail=f"question not found: {body.question_id}"
        )
