"""Flow Packets — projection read + action mutation endpoints.

Endpoints:
  * GET  /api/projects/{project_id}/flows
        → list[FlowPacket] derived from existing rows.
  * POST /api/projects/{project_id}/flows/{flow_id}/actions
        → mutate the underlying domain row via FlowActionService.

The router is intentionally thin per CLAUDE.md invariant — pydantic
validation → membership gate → service call → status. C.1 ships the
action endpoint scoped to ask_with_context + source-side actions only.
See `docs/flow-actions-c1-design.md` for the full contract.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    FlowActionService,
    FlowProjectionService,
    ProjectService,
)
from workgraph_api.services.flow_actions import (
    ERROR_HTTP_STATUS,
    FlowActionError,
)

router = APIRouter(tags=["flows"])

# Mirror the literals in flow_projection.py so the FastAPI typed query
# params reject unknown values at parse time. Keeping them here too
# (instead of importing from the service) preserves the thin-router
# property — the router declares its own contract.
_PacketStatus = Literal["active", "blocked", "completed", "rejected", "expired"]
_Bucket = Literal[
    "needs_me",
    "waiting_on_others",
    "awaiting_membrane",
    "recent",
]
_Recipe = Literal[
    "ask_with_context",
    "promote_to_memory",
    "promote_task_to_plan",
    "crystallize_decision",
    "review",
    "handoff",
    "meeting_metabolism",
]


@router.get("/api/projects/{project_id}/flows")
async def list_flows(
    project_id: str,
    request: Request,
    status: _PacketStatus | None = Query(default=None),
    bucket: _Bucket | None = Query(default=None),
    recipe: _Recipe | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
):
    """List Flow Packets for a project.

    Returns a JSON envelope `{"packets": [...]}` (rather than a bare
    array) so future fields like `next_cursor`, `total`, or
    `bucket_counts` can be added without breaking clients.
    """
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not_a_project_member")

    service: FlowProjectionService = request.app.state.flow_projection_service
    # D.a: list_for_project now returns the full envelope
    # `{packets, participants}` so the FE can resolve user_ids without
    # N+1. Pass through verbatim.
    return await service.list_for_project(
        project_id=project_id,
        viewer_user_id=user.id,
        status=status,
        bucket=bucket,
        recipe=recipe,
        limit=limit,
    )


# ---- C.1 — POST /actions -------------------------------------------------


class _AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept"]
    note: str | None = Field(default=None, max_length=1000)


class _CounterBackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["counter_back"]
    framing: str = Field(min_length=1, max_length=4000)
    note: str | None = Field(default=None, max_length=1000)


class _EscalateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["escalate_to_gate"]
    note: str | None = Field(default=None, max_length=1000)


class _FollowupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["custom_followup"]
    framing: str = Field(min_length=1, max_length=4000)
    note: str | None = Field(default=None, max_length=1000)


# Discriminated union — Pydantic routes on `action` literal at parse
# time. Missing `framing` on counter_back / custom_followup yields a
# 422 with field-level detail before our handler runs.
ActionRequest = Annotated[
    Union[_AcceptBody, _CounterBackBody, _EscalateBody, _FollowupBody],
    Field(discriminator="action"),
]


@router.post("/api/projects/{project_id}/flows/{flow_id}/actions")
async def post_flow_action(
    project_id: str,
    flow_id: str,
    body: ActionRequest = Body(...),
    request: Request = None,  # type: ignore[assignment]
    user: AuthenticatedUser = Depends(require_user),
):
    """Source-side reply symmetry — first mutation endpoint of the
    Flow Packets system. Locked by the C.1 design memo.

    Body is one of four shapes (discriminated on `action`); the router
    delegates to FlowActionService which dispatches to the right
    domain method on RoutingService.
    """
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not_a_project_member")

    service: FlowActionService = request.app.state.flow_action_service
    try:
        # Pydantic parsed `body` already; pull out the action + optional
        # framing / note in a single shape the service signature expects.
        framing = getattr(body, "framing", None)
        result = await service.execute(
            flow_id=flow_id,
            viewer_user_id=user.id,
            action=body.action,
            framing=framing,
            note=body.note,
        )
    except FlowActionError as e:
        # Project convention: HTTPException(detail=...) takes a STRING.
        # The global handler at main.py wraps it as
        # {code, message: str(detail), trace_id}. Tests assert on
        # `r.json()["message"]` containing our error code.
        # Format: "<code>: <detail>" so we can carry sub-detail without
        # breaking the substring assertion.
        if e.detail and e.detail != e.code:
            detail_str = f"{e.code}: {e.detail}"
        else:
            detail_str = e.code
        raise HTTPException(
            status_code=ERROR_HTTP_STATUS.get(e.code, 400),
            detail=detail_str,
        )
    return {"ok": True, **result}
