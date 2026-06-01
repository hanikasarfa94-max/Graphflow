"""Phase 10 — Delivery summary endpoints.

Routes:
  POST /api/projects/{id}/delivery          — generate a fresh summary
  GET  /api/projects/{id}/delivery          — latest summary (or null)
  GET  /api/projects/{id}/delivery/history  — last N summaries

Membership is enforced via ProjectService. The POST returns the new
snapshot payload so the caller avoids a round-trip.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    DeliveryError,
    DeliveryService,
    ProjectService,
)

router = APIRouter(prefix="/api/projects", tags=["delivery"])


# ---- response shapes (C1-C) -----------------------------------------------
# Mirror DeliveryService._row_payload. content / qa_report are free-form JSON
# blobs (content_json / qa_report columns) → typed dict[str, Any]. prompt_version
# /trace_id/created_by/created_at nullable per DeliverySummaryRow.


class DeliverySummary(BaseModel):
    id: str
    project_id: str
    requirement_version: int
    content: dict[str, Any]
    parse_outcome: str
    qa_report: dict[str, Any]
    prompt_version: str | None = None
    trace_id: str | None = None
    created_by: str | None = None
    created_at: str | None = None


class DeliveryLatestResponse(BaseModel):
    delivery: DeliverySummary | None = None


class DeliveryHistoryResponse(BaseModel):
    deliveries: list[DeliverySummary]


@router.post("/{project_id}/delivery")
async def generate_delivery(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service: DeliveryService = request.app.state.delivery_service
    from workgraph_observability import get_trace_id

    try:
        return await service.generate(
            project_id=project_id,
            actor_id=user.id,
            trace_id=get_trace_id(),
        )
    except DeliveryError as e:
        raise HTTPException(status_code=e.status, detail=e.code)


@router.get("/{project_id}/delivery", response_model=DeliveryLatestResponse)
async def get_latest_delivery(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service: DeliveryService = request.app.state.delivery_service
    latest = await service.latest_for_project(project_id)
    return {"delivery": latest}


@router.get(
    "/{project_id}/delivery/history", response_model=DeliveryHistoryResponse
)
async def list_delivery_history(
    project_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    service: DeliveryService = request.app.state.delivery_service
    rows = await service.list_for_project(project_id, limit=limit)
    return {"deliveries": rows}
