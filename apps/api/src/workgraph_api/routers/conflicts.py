"""Phase 8 conflict endpoints.

Routes:
  GET  /api/projects/{id}/conflicts         — list open (and optionally closed) conflicts
  POST /api/projects/{id}/conflicts/recheck — manual recheck; returns fresh list
  POST /api/conflicts/{id}/resolve          — resolve w/ optional option_index
  POST /api/conflicts/{id}/dismiss          — dismiss as false-positive / not-actionable

Membership is enforced via ProjectService. Resolving/dismissing uses the
conflict's project_id for the check so we don't trust client-supplied ids.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    ConflictService,
    DecisionError,
    DecisionService,
    ProjectService,
)
from workgraph_persistence import ConflictRepository, session_scope

router = APIRouter(prefix="/api", tags=["conflicts"])


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_index: int | None = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_index: int | None = None
    custom_text: str | None = Field(default=None, max_length=4000)
    rationale: str = Field(default="", max_length=4000)
    # Structured side-effect hook for `missing_owner` decisions: assigning
    # a project member to the task(s) targeted by the conflict.
    assignee_user_id: str | None = None


@router.get("/projects/{project_id}/conflicts")
async def list_conflicts(
    project_id: str,
    request: Request,
    include_closed: bool = Query(default=False),
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service: ConflictService = request.app.state.conflict_service
    return await service.list_for_project(
        project_id, include_closed=include_closed
    )


@router.post("/projects/{project_id}/conflicts/recheck")
async def recheck_conflicts(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service: ConflictService = request.app.state.conflict_service
    from workgraph_observability import get_trace_id

    result = await service.recheck(project_id, trace_id=get_trace_id())
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("error", "recheck_failed"))
    return result


async def _project_from_conflict(sessionmaker, conflict_id: str) -> str | None:
    async with session_scope(sessionmaker) as session:
        row = await ConflictRepository(session).get(conflict_id)
        return row.project_id if row else None


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: str,
    body: ResolveRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_id = await _project_from_conflict(
        request.app.state.sessionmaker, conflict_id
    )
    if project_id is None:
        raise HTTPException(status_code=404, detail="conflict not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")

    service: ConflictService = request.app.state.conflict_service
    result = await service.resolve(
        conflict_id=conflict_id,
        actor_id=user.id,
        option_index=body.option_index,
    )
    if not result.get("ok"):
        code = 409 if result.get("error") == "already_resolved" else 400
        raise HTTPException(status_code=code, detail=result.get("error", "resolve_failed"))
    return result


@router.post("/conflicts/{conflict_id}/dismiss")
async def dismiss_conflict(
    conflict_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_id = await _project_from_conflict(
        request.app.state.sessionmaker, conflict_id
    )
    if project_id is None:
        raise HTTPException(status_code=404, detail="conflict not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")

    service: ConflictService = request.app.state.conflict_service
    result = await service.dismiss(conflict_id=conflict_id, actor_id=user.id)
    if not result.get("ok"):
        code = 409 if result.get("error") == "already_resolved" else 400
        raise HTTPException(status_code=code, detail=result.get("error", "dismiss_failed"))
    return result


# ---- Phase 9: decision + audit history ------------------------------------


@router.post("/conflicts/{conflict_id}/decision")
async def submit_decision(
    conflict_id: str,
    body: DecisionRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_id = await _project_from_conflict(
        request.app.state.sessionmaker, conflict_id
    )
    if project_id is None:
        raise HTTPException(status_code=404, detail="conflict not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    # Guard: if caller wants to apply an assignment, the proposed assignee
    # must also be a project member (assignment service also checks, but
    # we want a crisp 400 instead of an opaque "assign_failed" rollup).
    if body.assignee_user_id is not None:
        if not await project_service.is_member(
            project_id=project_id, user_id=body.assignee_user_id
        ):
            raise HTTPException(
                status_code=400, detail="assignee_not_a_member"
            )

    service: DecisionService = request.app.state.decision_service
    from workgraph_observability import get_trace_id

    try:
        result = await service.submit(
            conflict_id=conflict_id,
            actor_id=user.id,
            option_index=body.option_index,
            custom_text=body.custom_text,
            rationale=body.rationale,
            assignee_user_id=body.assignee_user_id,
            trace_id=get_trace_id(),
        )
    except DecisionError as e:
        raise HTTPException(status_code=e.status, detail=e.code)
    return result


@router.get("/projects/{project_id}/decisions")
async def list_decisions(
    project_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service: DecisionService = request.app.state.decision_service
    items = await service.list_for_project(project_id, limit=limit)
    return {"decisions": items}


@router.get("/conflicts/{conflict_id}/decisions")
async def list_conflict_decisions(
    conflict_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_id = await _project_from_conflict(
        request.app.state.sessionmaker, conflict_id
    )
    if project_id is None:
        raise HTTPException(status_code=404, detail="conflict not found")
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service: DecisionService = request.app.state.decision_service
    items = await service.list_for_conflict(conflict_id)
    return {"decisions": items}
