"""Flow Packets — projection read endpoint (Slice A of flow-packets-spec.md).

Single endpoint:
  * GET /api/projects/{project_id}/flows
        → list[FlowPacket] derived from existing rows.

The router is intentionally thin per CLAUDE.md invariant — pydantic
validation → membership gate → service call → status. Domain dispatch
for actions ships in Slice C via FlowActionService.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    FlowProjectionService,
    ProjectService,
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
    packets = await service.list_for_project(
        project_id=project_id,
        viewer_user_id=user.id,
        status=status,
        bucket=bucket,
        recipe=recipe,
        limit=limit,
    )
    return {"packets": packets}
