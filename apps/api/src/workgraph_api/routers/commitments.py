"""Commitments router — Sprint 2a.

Routes:
  GET  /api/projects/{project_id}/commitments         — list (optional ?status=)
  POST /api/projects/{project_id}/commitments         — create
  PATCH /api/commitments/{commitment_id}/status       — mark met/missed/withdrawn

All routes require project membership. Create + status-change emit
events so Sprint 1c drift auto-trigger (and future Sprint 2b SLA
watchers) can react.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    CommitmentService,
    CommitmentValidationError,
)

router = APIRouter(tags=["commitments"])


class CreateCommitmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=3, max_length=500)
    owner_user_id: str | None = Field(default=None, max_length=36)
    target_date: datetime | None = None
    metric: str | None = Field(default=None, max_length=500)
    scope_ref_kind: (
        Literal["task", "deliverable", "goal", "milestone"] | None
    ) = None
    scope_ref_id: str | None = Field(default=None, max_length=36)
    source_message_id: str | None = Field(default=None, max_length=36)

    @field_validator("scope_ref_id")
    @classmethod
    def _scope_id_requires_kind(
        cls, v: str | None, info
    ) -> str | None:
        # Catches the "id without kind" asymmetry early — service layer
        # checks the reverse direction. Keeps error message clean.
        if v is not None and info.data.get("scope_ref_kind") is None:
            raise ValueError("scope_ref_kind required when scope_ref_id is set")
        return v


class UpdateStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "met", "missed", "withdrawn"]


def _get_service(request: Request) -> CommitmentService:
    return request.app.state.commitment_service


@router.get("/api/projects/{project_id}/commitments")
async def list_commitments(
    project_id: str,
    request: Request,
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    if not await service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    items = await service.list_for_project(
        project_id=project_id, status=status, limit=limit
    )
    return {"commitments": items}


@router.post("/api/projects/{project_id}/commitments")
async def create_commitment(
    project_id: str,
    body: CreateCommitmentRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    if not await service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not a project member")
    try:
        payload = await service.create(
            project_id=project_id,
            actor_user_id=user.id,
            headline=body.headline,
            owner_user_id=body.owner_user_id,
            target_date=body.target_date,
            metric=body.metric,
            scope_ref_kind=body.scope_ref_kind,
            scope_ref_id=body.scope_ref_id,
            source_message_id=body.source_message_id,
        )
    except CommitmentValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"ok": True, "commitment": payload}


@router.patch("/api/commitments/{commitment_id}/status")
async def update_commitment_status(
    commitment_id: str,
    body: UpdateStatusRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    try:
        payload = await service.set_status(
            commitment_id=commitment_id,
            actor_user_id=user.id,
            status=body.status,
        )
    except CommitmentValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if payload is None:
        raise HTTPException(status_code=404, detail="commitment not found")
    # Membership check — after we've loaded the row, we know its project.
    if not await service.is_member(
        project_id=payload["project_id"], user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not a project member")
    return {"ok": True, "commitment": payload}
