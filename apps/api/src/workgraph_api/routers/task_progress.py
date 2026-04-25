"""Task progress endpoints — Phase U.

  POST /api/tasks/{task_id}/status
      Owner-or-assignee transitions task status. Body: {new_status, note?}.

  POST /api/tasks/{task_id}/score
      Project-owner scores a done task. Body: {quality, feedback?}.

  GET  /api/tasks/{task_id}/history
      Status timeline + score (if any). Project-member-only.

  POST /api/projects/{project_id}/tasks  — Phase T (manual create)
      Create a personal-scope task. Always allowed for project members.

  POST /api/tasks/{task_id}/promote  — Phase T
      Personal → plan via MembraneService.review (mirrors KB promote).

Permissions live in the service layer; this router translates
TaskProgressError codes into HTTP statuses.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_persistence import (
    PlanRepository,
    ProjectMemberRepository,
    RequirementRepository,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    MembraneCandidate,
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


# ---- Phase T: manual task create + promote ----------------------------


class CreatePersonalTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=4000)
    source_message_id: str | None = Field(default=None, max_length=64)


def _serialize_task(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "description": row.description,
        "scope": row.scope,
        "status": row.status,
        "owner_user_id": row.owner_user_id,
        "requirement_id": row.requirement_id,
        "source_message_id": row.source_message_id,
        "assignee_role": row.assignee_role,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/api/projects/{project_id}/tasks")
async def post_create_task(
    project_id: str,
    body: CreatePersonalTaskRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Create a personal-scope task. Any project member; no review.

    Mirrors the KB pattern: personal-scope writes are forks (always
    allowed, owner-only visibility). Promote-to-plan goes through
    MembraneService.review separately. Source attribution via
    optional source_message_id (analog of save-as-kb).
    """
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        if not await ProjectMemberRepository(session).is_member(
            project_id, user.id
        ):
            raise HTTPException(
                status_code=403, detail="not a project member"
            )
        row = await PlanRepository(session).create_personal_task(
            project_id=project_id,
            owner_user_id=user.id,
            title=body.title.strip(),
            description=body.description.strip(),
            source_message_id=body.source_message_id,
        )
        return {"ok": True, "task": _serialize_task(row)}


@router.post("/api/tasks/{task_id}/promote")
async def post_promote_task(
    task_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Personal → plan via MembraneService.review.

    Membrane action mapping:
      auto_merge          → flips scope to 'plan', attaches to latest
                            requirement, sort_order = end of plan
      reject              → 409 with reason
      request_review      → kept as personal-scope draft for now;
      request_clarification stage-T+1 will route through the same
                            IMSuggestion(kind='membrane_review') path
                            kb_item_group uses
    """
    sessionmaker = request.app.state.sessionmaker
    membrane_service = request.app.state.membrane_service
    async with session_scope(sessionmaker) as session:
        repo = PlanRepository(session)
        task = await repo.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        if task.scope != "personal":
            return {"ok": True, "task": _serialize_task(task)}
        # Only the owner can promote their own personal task. Project
        # owners can override via direct DB edit; we don't expose a
        # cross-user promote since it'd let any owner ship arbitrary
        # personal todos as group plan items.
        if task.owner_user_id != user.id:
            raise HTTPException(status_code=403, detail="forbidden")
        project_id = task.project_id
        title = task.title
        description = task.description or ""

    review = await membrane_service.review(
        MembraneCandidate(
            kind="kb_item_group",  # reuse the same review handler for now;
            # stage T+1 adds a dedicated 'task_promote' kind so the
            # membrane can apply task-specific rules (e.g., title-dup
            # against existing plan tasks, not KB items).
            project_id=project_id,
            proposer_user_id=user.id,
            title=title,
            content=description,
            metadata={"source": "task_promote", "task_id": task_id},
        )
    )
    if review.action == "reject":
        raise HTTPException(
            status_code=409,
            detail=review.reason or "membrane_rejected",
        )
    if review.action in ("request_review", "request_clarification"):
        # Stage 4 inbox enqueue not yet wired for tasks; for now just
        # tell the caller it's deferred and leave the personal task
        # as-is. Owner can resolve manually.
        return {
            "ok": True,
            "task": None,
            "deferred": True,
            "reason": review.reason,
            "diff_summary": review.diff_summary,
        }

    # auto_merge — attach to latest requirement, slot at end of plan.
    async with session_scope(sessionmaker) as session:
        req = await RequirementRepository(session).latest_for_project(
            project_id
        )
        if req is None:
            raise HTTPException(
                status_code=400,
                detail="no_requirement_to_attach_to",
            )
        existing = await PlanRepository(session).list_tasks(req.id)
        next_sort = (
            max((t.sort_order or 0) for t in existing) + 1 if existing else 0
        )
        promoted = await PlanRepository(session).promote_personal_to_plan(
            task_id=task_id,
            requirement_id=req.id,
            sort_order=next_sort,
        )
        if promoted is None:
            raise HTTPException(status_code=409, detail="promote_failed")
        return {"ok": True, "task": _serialize_task(promoted)}
