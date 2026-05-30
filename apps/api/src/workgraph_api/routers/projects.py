"""Project list + membership endpoints (Phase 7').

`GET /api/projects` lists projects the current user is a member of.
`POST /api/projects/{id}/invite` invites by username.
`GET /api/projects/{id}/members` lists members.
`GET /api/projects/{id}/state` returns the composite graph+plan snapshot
    for the project detail page (one fetch, no N+1 round-trips).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_persistence import (
    RequirementRepository,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, ProjectService

router = APIRouter(prefix="/api/projects", tags=["projects"])


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=32)


class RequirementBudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None clears the budget. ge=1 because zero would silently disable
    # the membrane's overflow check while pretending it was set.
    budget_hours: int | None = Field(default=None, ge=1, le=100000)


class MemberSkillsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Free-form strings; we lowercase + dedup at write time. The
    # vocabulary draws from TaskRow.assignee_role values
    # (pm/frontend/backend/qa/design/business/approver) but we don't
    # enforce — projects can introduce niche tags as needed.
    skill_tags: list[str] = Field(default_factory=list, max_length=32)


@router.get("")
async def list_projects(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> list[dict[str, Any]]:
    service: ProjectService = request.app.state.project_service
    return await service.list_for_user(user.id)


@router.post("/{project_id}/invite")
async def invite_member(
    project_id: str,
    body: InviteRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service: ProjectService = request.app.state.project_service
    is_member = await service.is_member(project_id=project_id, user_id=user.id)
    if not is_member:
        raise HTTPException(status_code=403, detail="not a project member")
    result = await service.add_member(
        project_id=project_id, username=body.username, invited_by=user.id
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "invite_failed"))
    return result


@router.get("/{project_id}/members")
async def list_members(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> list[dict[str, Any]]:
    service: ProjectService = request.app.state.project_service
    is_member = await service.is_member(project_id=project_id, user_id=user.id)
    if not is_member:
        raise HTTPException(status_code=403, detail="not a project member")
    return await service.members(project_id)


@router.patch("/{project_id}/members/{user_id}/skills")
async def patch_member_skills(
    project_id: str,
    user_id: str,
    body: MemberSkillsUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Self-edit OR owner-edit a project member's functional skill tags.

    Used by the membrane's task_promote review for assignee-coverage
    advisories: a task tagged role='backend' with no project member
    declaring 'backend' surfaces a warning.

    Vocabulary tracks TaskRow.assignee_role
    (pm/frontend/backend/qa/design/business/approver/unknown) but we
    accept any string so projects can introduce niche tags.
    """
    service: ProjectService = request.app.state.project_service
    members = await service.members(project_id)
    me = next((m for m in members if m["user_id"] == user.id), None)
    if me is None:
        raise HTTPException(status_code=403, detail="not a project member")
    if user.id != user_id and me.get("role") != "owner":
        # Self-edit is always allowed; cross-edit is owner-only.
        raise HTTPException(status_code=403, detail="owner_or_self_only")

    target = next((m for m in members if m["user_id"] == user_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="member_not_found")

    # M5.1 — call through the gated service method. Owner edits
    # auto_merge; non-owner edits (self or cross) defer into an
    # IMSuggestion(membrane_review, candidate_kind=manual_skill_change)
    # for owner approval. Cross-edit-by-non-owner still 403s.
    result = await service.set_member_skill_tags(
        project_id=project_id,
        actor_user_id=user.id,
        target_user_id=user_id,
        skill_tags=body.skill_tags,
    )
    if not result.get("ok"):
        err = result.get("error", "set_skill_tags_failed")
        if err == "owner_or_self_only":
            raise HTTPException(status_code=403, detail=err)
        if err == "not_a_project_member":
            raise HTTPException(status_code=403, detail=err)
        if err == "member_not_found":
            raise HTTPException(status_code=404, detail=err)
        raise HTTPException(status_code=400, detail=err)
    return result


@router.patch("/{project_id}/requirements/{requirement_id}/budget")
async def patch_requirement_budget(
    project_id: str,
    requirement_id: str,
    body: RequirementBudgetUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Owner-only — set/clear the requirement's declared budget in hours.

    Used by the membrane's task_promote review for the
    estimate-overflow advisory check. LLM intake never writes this
    field; it lives behind a manual UI control so capacity is an
    explicit owner decision, not an LLM guess.
    """
    service: ProjectService = request.app.state.project_service
    members = await service.members(project_id)
    me = next((m for m in members if m["user_id"] == user.id), None)
    if me is None:
        raise HTTPException(status_code=403, detail="not a project member")
    if me.get("role") != "owner":
        raise HTTPException(status_code=403, detail="owner_only")

    async with session_scope(request.app.state.sessionmaker) as session:
        req = await RequirementRepository(session).get(requirement_id)
        if req is None or req.project_id != project_id:
            raise HTTPException(status_code=404, detail="requirement_not_found")
        req.budget_hours = body.budget_hours
        await session.flush()
        return {
            "ok": True,
            "requirement_id": req.id,
            "budget_hours": req.budget_hours,
        }


@router.get("/{project_id}/state")
async def get_project_state(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    # Thin router (audit H1): membership gate, then the service read model.
    service: ProjectService = request.app.state.project_service
    if not await service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    state = await request.app.state.project_state_service.build_state(
        project_id, user.id
    )
    if state is None:
        raise HTTPException(status_code=404, detail="project not found")
    return state
