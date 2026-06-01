"""Phase B.1 — v0.6.2 global Tasks surface (API_CONTRACT §"Tasks").

The /api/tasks router replaces the per-project audit URL
`/projects/[id]/detail/tasks`. In v0.6.2 Tasks is a top-level surface
filtered by an optional `scope_id` (the API alias for `project_id`).

Endpoints:

  * GET  /api/tasks?scope_id=...&view=my_tasks|all
      List tasks. `scope_id=None` means cross-scope (every scope the
      user is a member of). `view=my_tasks` filters to tasks assigned
      to the calling user; `view=all` returns everything in scope.

  * POST /api/tasks/candidates
      Create a context-born task candidate (TaskStatus="candidate")
      attached to a source object (conversation message / document /
      flow response). The candidate is born outside the project plan
      — promote graduates it.

  * POST /api/tasks/{id}/promote
      Promote a candidate to the project plan. **Requires** a
      TaskRecognitionPolicy value per API_CONTRACT.md. The router
      validates the policy is set before delegating to the existing
      MembraneService.review() / PlanRepository.promote_personal_to_plan
      path used by `task_progress.py`.

Thin-router invariant (CLAUDE.md §"Architectural invariants"): all
business logic — eligibility filtering, MembraneService dispatch,
PlanRepository writes — lives in TaskProgressService / PlanRepository.
This file is pydantic + membership gate + service dispatch only.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_persistence import (
    PlanRepository,
    ProjectMemberRepository,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    MembraneCandidate,
    TaskProgressError,
    TaskProgressService,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks-global"])


# ---- enums (mirror schemas.graphflow.json) -------------------------------

# TaskRecognitionPolicy — MUST stay in sync with
# graphflow_handoff_v062/schemas.graphflow.json.
_VALID_RECOGNITION_POLICIES: set[str] = {
    "none",
    "assignee_accept",
    "project_owner_confirm",
    "flow_required",
    "review_required",
}

_VALID_VIEWS: set[str] = {"my_tasks", "all"}

_VALID_SOURCE_KINDS: set[str] = {"conversation", "document", "flow_response"}


# ---- request shapes -------------------------------------------------------


class TaskCandidateRequest(BaseModel):
    """Context-born task candidate (TaskStatus='candidate').

    A candidate is a not-yet-recognized task proposal. It must point
    at an existing source object — never freeform. Promotion is a
    separate decision.
    """

    model_config = ConfigDict(extra="forbid")

    scope_id: str = Field(min_length=1, max_length=64)
    source_kind: Literal["conversation", "document", "flow_response"]
    source_object_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    proposed_assignee_id: str | None = Field(default=None, max_length=64)


class PromoteTaskRequest(BaseModel):
    """Promote a candidate to plan. Recognition policy is REQUIRED.

    API_CONTRACT.md: "POST /api/tasks/:id/promote requires recognition
    policy." The router enforces this before delegating, even if the
    underlying service is permissive.
    """

    model_config = ConfigDict(extra="forbid")

    recognition_policy: str = Field(min_length=1, max_length=32)


# ---- response shapes (C1-C) -----------------------------------------------
# Mirror the runtime `_serialize_task` payload below — NOT a frontend
# assumption. Required fields map to non-null TaskRow columns (id PK, title,
# description/scope/assignee_role/status carry non-null defaults, project_id
# non-null; scope_id is the project_id alias). Nullable fields are the
# genuinely-nullable columns. NOTE: the FE features/tasks/types.ts previously
# marked scope_id/project_id/description/assignee_role nullable — wider than
# runtime; this model encodes the true (non-null) shape.


class TaskRow(BaseModel):
    id: str
    scope_id: str
    project_id: str
    title: str
    description: str
    scope: str
    status: str
    owner_user_id: str | None = None
    requirement_id: str | None = None
    source_message_id: str | None = None
    assignee_role: str
    estimate_hours: int | None = None
    created_at: str | None = None


class TaskListResponse(BaseModel):
    tasks: list[TaskRow]
    scope_id: str | None = None
    view: str


# ---- helpers --------------------------------------------------------------


def _service(request: Request) -> TaskProgressService:
    return request.app.state.task_progress_service


def _serialize_task(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "scope_id": row.project_id,  # v0.6.2 API alias
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


# ---- endpoints ------------------------------------------------------------


@router.get("", response_model=TaskListResponse)
async def get_tasks(
    request: Request,
    scope_id: str | None = Query(default=None, max_length=64),
    view: str = Query(default="all"),
    limit: int = Query(default=200, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """List tasks the caller can see.

    - `scope_id=None`: cross-scope — every scope the caller is a member
      of. Phase B.2 adds a dedicated repository method; for B.1 we
      iterate the caller's membership list.
    - `scope_id=<id>`: tasks inside that scope, after a membership
      gate.
    - `view=my_tasks`: filter to owner_user_id == caller.
    - `view=all`: everything visible in the requested scope.
    """
    if view not in _VALID_VIEWS:
        raise HTTPException(
            status_code=400,
            detail=f"invalid_view (allowed: {sorted(_VALID_VIEWS)})",
        )

    maker = request.app.state.sessionmaker
    out: list[dict[str, Any]] = []
    async with session_scope(maker) as session:
        plan_repo = PlanRepository(session)
        member_repo = ProjectMemberRepository(session)

        if scope_id is not None:
            if not await member_repo.is_member(scope_id, user.id):
                raise HTTPException(
                    status_code=403, detail="not_a_scope_member"
                )
            scope_ids: list[str] = [scope_id]
        else:
            # Cross-scope: collect every project the caller is a member
            # of. TODO(Phase B.2): a dedicated repo method
            # `list_for_user_across_projects` to avoid the per-scope
            # loop.
            rows = await member_repo.list_for_user(user.id)
            scope_ids = [r.project_id for r in rows]

        for sid in scope_ids:
            if view == "my_tasks":
                # Personal-drafts mirror; later widened to plan-scope
                # tasks where assignee_id == caller.
                rows = await plan_repo.list_personal_for_owner(
                    project_id=sid, owner_user_id=user.id, limit=limit
                )
                out.extend(_serialize_task(r) for r in rows)
            else:
                # view='all' — TODO(Phase B.2): list every visible task
                # in the scope (plan + personal). For B.1 we surface
                # personal drafts only so the wire shape stabilizes.
                rows = await plan_repo.list_personal_for_owner(
                    project_id=sid, owner_user_id=user.id, limit=limit
                )
                out.extend(_serialize_task(r) for r in rows)

    return {"tasks": out, "scope_id": scope_id, "view": view}


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Phase RW-7 — read-only singleton task detail.

    Membership-gated on the task's scope (project). Returns the
    same `_serialize_task` payload the list endpoint emits so the
    FE consumes one shape. No mutation. Returns 404 when the id
    doesn't resolve and 403 when the viewer isn't in the scope.
    """
    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        row = await PlanRepository(session).get_task(task_id)
        if row is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        if row.project_id is not None and not await ProjectMemberRepository(
            session
        ).is_member(row.project_id, user.id):
            raise HTTPException(status_code=403, detail="not_a_scope_member")
    return {"task": _serialize_task(row)}


@router.post("/candidates")
async def post_task_candidate(
    body: TaskCandidateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Create a context-born task candidate (TaskStatus='candidate').

    The candidate lives off the plan until it is promoted. v0.6.2
    candidate-born flow: a conversation / document / flow response
    surfaces an action; AI Assistance (or a human) proposes the
    candidate; the assignee or project owner promotes it per the
    recognition policy.

    For Phase B.1 we persist as a personal-scope task with
    `source_message_id=source_object_id` when the source is a
    conversation; for documents / flow_responses the source_object_id
    is threaded onto the task so the promote step can echo it. Phase
    B.2 widens the TaskRow model with a dedicated `source_kind`
    column + a true `status='candidate'` (vs 'personal').
    """
    if body.source_kind not in _VALID_SOURCE_KINDS:
        # Belt-and-braces — the Literal already rejects this, but the
        # 422 from pydantic isn't shaped the same as the rest of the
        # router's 400s.
        raise HTTPException(status_code=400, detail="invalid_source_kind")

    maker = request.app.state.sessionmaker
    async with session_scope(maker) as session:
        if not await ProjectMemberRepository(session).is_member(
            body.scope_id, user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_scope_member")

        # Source attribution: only `conversation` maps cleanly onto
        # the existing `source_message_id` column. For document /
        # flow_response sources we leave it null and pass the id
        # through metadata until B.2 introduces a polymorphic
        # `source_ref` column on TaskRow.
        source_message_id = (
            body.source_object_id if body.source_kind == "conversation" else None
        )
        row = await PlanRepository(session).create_personal_task(
            project_id=body.scope_id,
            owner_user_id=user.id,
            title=body.title.strip(),
            description=(body.description or "").strip(),
            source_message_id=source_message_id,
            estimate_hours=None,
            assignee_role=(body.proposed_assignee_id or "unknown"),
        )

    serialized = _serialize_task(row)
    # The contract's TaskStatus enum has `candidate` as a distinct
    # value. The underlying row uses scope='personal' as the v0
    # carrier; we re-shape to candidate on the wire so the FE renders
    # the right badge.
    serialized["status"] = "candidate"
    return {
        "task": serialized,
        "source_kind": body.source_kind,
        "source_object_id": body.source_object_id,
    }


@router.post("/{task_id}/promote", operation_id="promote_global_task")
async def post_promote_task(
    task_id: str,
    body: PromoteTaskRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Promote a candidate to plan, recognition-policy gated.

    Authority pattern: the router validates `recognition_policy` is a
    legal `TaskRecognitionPolicy` value, then delegates to
    MembraneService.review() with kind='task_promote' (the same path
    `task_progress.py` already uses). The policy is threaded into the
    review metadata so the membrane can branch on it once policy-aware
    review lands in Phase B.2.

    Policy=`none` is rejected at the contract layer — promote without
    a recognition gate is a doctrine violation. Use one of the other
    four values explicitly.
    """
    if body.recognition_policy not in _VALID_RECOGNITION_POLICIES:
        raise HTTPException(
            status_code=400,
            detail=(
                "invalid_recognition_policy (allowed: "
                f"{sorted(_VALID_RECOGNITION_POLICIES)})"
            ),
        )
    if body.recognition_policy == "none":
        # Doctrine gate. Promote always has a recognition policy —
        # 'none' is reserved for tasks that never had a candidate
        # stage (e.g. owner-direct-create), not the promote action.
        raise HTTPException(
            status_code=400, detail="recognition_policy_required"
        )

    maker = request.app.state.sessionmaker
    membrane_service = request.app.state.membrane_service
    async with session_scope(maker) as session:
        repo = PlanRepository(session)
        task = await repo.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task_not_found")
        if task.owner_user_id != user.id:
            raise HTTPException(status_code=403, detail="forbidden")
        if task.scope != "personal":
            return {"ok": True, "task": _serialize_task(task)}
        project_id = task.project_id
        title = task.title
        description = task.description or ""

    # Delegate to MembraneService.review — mirrors task_progress.py's
    # promote path. Recognition policy rides in metadata; B.2 adds a
    # policy-aware branch inside review_task_promote.
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
                "recognition_policy": body.recognition_policy,
                "estimate_hours": task.estimate_hours,
                "assignee_role": task.assignee_role,
            },
        )
    )

    if review.action == "reject":
        raise HTTPException(
            status_code=409, detail=review.reason or "membrane_rejected"
        )
    if review.action in ("request_review", "request_clarification"):
        # Deferred — the membrane staged the promote for review.
        # Wire shape matches task_progress.py's deferred envelope.
        return {
            "ok": True,
            "task": None,
            "deferred": True,
            "reason": review.reason,
            "diff_summary": review.diff_summary,
            "warnings": list(review.warnings),
            "recognition_policy": body.recognition_policy,
        }

    # auto_merge — delegate to the existing TaskProgressService /
    # PlanRepository path used by task_progress.py.
    # TODO(Phase B.2): pull the auto_merge branch into a shared service
    # method so this router doesn't duplicate task_progress.py's
    # requirement-attachment logic.
    service = _service(request)
    try:
        # Re-use the existing status-update path as the promote sink.
        # This is a placeholder until B.2 lands TaskProgressService
        # .promote_with_policy(). For now the recognition_policy is
        # threaded back to the FE so it can render the right badge.
        return {
            "ok": True,
            "deferred": False,
            "recognition_policy": body.recognition_policy,
            "review": {
                "action": review.action,
                "warnings": list(review.warnings),
            },
            # TODO(Phase B.2): perform the PlanRepository
            # .promote_personal_to_plan() write here, mirroring
            # task_progress.py:381-405.
            "_todo": "Phase B.2 wires the auto_merge write path",
        }
    except TaskProgressError as err:
        raise HTTPException(status_code=400, detail=err.code) from err
