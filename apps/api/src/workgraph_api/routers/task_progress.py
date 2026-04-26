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
    EDGE_AGENT_SYSTEM_USER_ID,
    IMSuggestionRepository,
    MessageRepository,
    PlanRepository,
    ProjectMemberRepository,
    RequirementRepository,
    StreamRepository,
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
    # Optional at create time; passing them gives the membrane's
    # task_promote review enough information to do an
    # estimate-overflow check at promote time. Both are no-ops if
    # omitted (estimate=null, role='unknown').
    estimate_hours: int | None = Field(default=None, ge=1, le=10000)
    assignee_role: str | None = Field(default=None, max_length=32)


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
        "estimate_hours": row.estimate_hours,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/api/projects/{project_id}/personal-tasks")
async def list_personal_tasks(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Personal-scope tasks the current user owns in this project.

    Mirrors the KB tree's "personal items only the owner sees" rule —
    a draft surface so members can promote their own self-set tasks
    without leaking them to peers. Empty list if the user owns none.
    """
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        if not await ProjectMemberRepository(session).is_member(
            project_id, user.id
        ):
            raise HTTPException(
                status_code=403, detail="not a project member"
            )
        rows = await PlanRepository(session).list_personal_for_owner(
            project_id=project_id, owner_user_id=user.id
        )
        return {"ok": True, "tasks": [_serialize_task(r) for r in rows]}


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
            estimate_hours=body.estimate_hours,
            assignee_role=(body.assignee_role or "unknown").strip() or "unknown",
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
        proposed_estimate = task.estimate_hours

    review = await membrane_service.review(
        MembraneCandidate(
            kind="task_promote",
            project_id=project_id,
            proposer_user_id=user.id,
            title=title,
            content=description,
            metadata={
                "source": "task_promote",
                "task_id": task_id,
                # Threaded so the membrane's estimate-overflow check
                # has a typed value to compare against the requirement
                # budget. None passes through harmlessly.
                "estimate_hours": proposed_estimate,
            },
        )
    )
    if review.action == "reject":
        raise HTTPException(
            status_code=409,
            detail=review.reason or "membrane_rejected",
        )
    if review.action == "request_clarification":
        # Stage 5: question goes to the proposer's PERSONAL stream
        # (not team room). Proposer answers + can re-promote — for v0
        # the answer isn't auto-intercepted; the proposer reads the Q
        # and re-runs through the existing endpoint after addressing
        # it. Even without auto-reply the surface is real: today the
        # proposer just sees deferred=true with no actionable detail.
        await membrane_service.notify_clarification(
            candidate=MembraneCandidate(
                kind="task_promote",
                project_id=project_id,
                proposer_user_id=user.id,
                title=title,
                content=description,
                metadata={
                    "source": "task_promote",
                    "task_id": task_id,
                    "estimate_hours": proposed_estimate,
                },
            ),
            review=review,
            linked_id=task_id,
        )
        return {
            "ok": True,
            "task": None,
            "deferred": True,
            "reason": review.reason,
            "diff_summary": review.diff_summary,
            "clarify_question": review.clarify_question,
            "warnings": list(review.warnings),
        }
    if review.action == "request_review":
        # Stage 4 inbox enqueue: post a system message in the team
        # stream and an IMSuggestion(kind='membrane_review') so the
        # owner sees the deferred promote in the same inbox surface
        # used for KB membrane reviews. Mirrors kb_items.py:204-250.
        async with session_scope(sessionmaker) as session:
            team_stream = await StreamRepository(session).get_for_project(
                project_id
            )
            if team_stream is not None:
                body = (
                    f"📥 Membrane staged a personal task for promote review: "
                    f"'{title}'. Reason: {review.reason}."
                )
                if review.diff_summary:
                    body = f"{body}\n{review.diff_summary}"
                msg = await MessageRepository(session).append(
                    project_id=project_id,
                    author_id=EDGE_AGENT_SYSTEM_USER_ID,
                    body=body,
                    stream_id=team_stream.id,
                    kind="membrane-review",
                    linked_id=task_id,
                )
                await IMSuggestionRepository(session).append(
                    project_id=project_id,
                    message_id=msg.id,
                    kind="membrane_review",
                    confidence=1.0,
                    targets=list(review.conflict_with),
                    proposal={
                        "action": "approve_membrane_candidate",
                        "summary": (
                            review.diff_summary
                            or f"Approve '{title}' for the project plan"
                        ),
                        "detail": {
                            "candidate_kind": "task_promote",
                            "task_id": task_id,
                            "diff_summary": review.diff_summary,
                            "conflict_with": list(review.conflict_with),
                        },
                    },
                    reasoning=review.reason or "membrane request_review",
                    prompt_version=None,
                    outcome="ok",
                    attempts=1,
                )
        return {
            "ok": True,
            "task": None,
            "deferred": True,
            "reason": review.reason,
            "diff_summary": review.diff_summary,
            "warnings": list(review.warnings),
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
        return {
            "ok": True,
            "task": _serialize_task(promoted),
            "warnings": list(review.warnings),
        }
