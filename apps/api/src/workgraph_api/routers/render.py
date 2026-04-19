"""Phase R — Render endpoints.

Routes:
  GET  /api/projects/{id}/renders/postmortem                 — cached or first-gen
  POST /api/projects/{id}/renders/postmortem/regenerate      — force regenerate
  GET  /api/projects/{id}/renders/handoff/{user_id}          — cached or first-gen
  POST /api/projects/{id}/renders/handoff/{user_id}/regenerate

Membership is enforced via ProjectService. Handoff docs for another user
are viewable by any project member — the whole point is the successor
reading the departing user's slice — but non-members always 403.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, ProjectService
from workgraph_api.services.render import RenderError, RenderService

router = APIRouter(prefix="/api/projects", tags=["renders"])


async def _assert_member(request: Request, project_id: str, user_id: str) -> None:
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user_id):
        raise HTTPException(status_code=403, detail="not a project member")


@router.get("/{project_id}/renders/postmortem")
async def get_postmortem(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _assert_member(request, project_id, user.id)
    service: RenderService = request.app.state.render_service
    try:
        return await service.render_postmortem(project_id=project_id)
    except RenderError as e:
        raise HTTPException(status_code=e.status, detail=e.code)


@router.post("/{project_id}/renders/postmortem/regenerate")
async def regenerate_postmortem(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _assert_member(request, project_id, user.id)
    service: RenderService = request.app.state.render_service
    try:
        return await service.regenerate_postmortem(project_id=project_id)
    except RenderError as e:
        raise HTTPException(status_code=e.status, detail=e.code)


@router.get("/{project_id}/renders/handoff/{target_user_id}")
async def get_handoff(
    project_id: str,
    target_user_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _assert_member(request, project_id, user.id)
    # The handoff's target must also be a project member — successors
    # reading a non-member's "handoff" would be a nonsense doc.
    await _assert_member(request, project_id, target_user_id)
    service: RenderService = request.app.state.render_service
    try:
        return await service.render_handoff(
            project_id=project_id, user_id=target_user_id
        )
    except RenderError as e:
        raise HTTPException(status_code=e.status, detail=e.code)


@router.post("/{project_id}/renders/handoff/{target_user_id}/regenerate")
async def regenerate_handoff(
    project_id: str,
    target_user_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _assert_member(request, project_id, user.id)
    await _assert_member(request, project_id, target_user_id)
    service: RenderService = request.app.state.render_service
    try:
        return await service.regenerate_handoff(
            project_id=project_id, user_id=target_user_id
        )
    except RenderError as e:
        raise HTTPException(status_code=e.status, detail=e.code)
