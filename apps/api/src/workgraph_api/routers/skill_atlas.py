"""Skill atlas router.

GET /api/projects/{project_id}/skills
  Returns the capability atlas. Owner sees all members + collective
  aggregate; non-owner sees only their own member card + empty
  collective. See services/skill_atlas.py for the full semantics.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    ProjectService,
    SkillAtlasService,
)

router = APIRouter(tags=["skill-atlas"])


@router.get("/api/projects/{project_id}/skills")
async def get_skill_atlas(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    service: SkillAtlasService = request.app.state.skill_atlas_service
    return await service.atlas_for_project(
        project_id=project_id, viewer_user_id=user.id
    )
