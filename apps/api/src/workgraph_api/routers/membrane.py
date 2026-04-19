"""Phase D membrane ingestion endpoints (vision §5.12).

  * POST /api/membranes/ingest                       — auth: project member
  * GET  /api/projects/{project_id}/membranes/recent — auth: project member
  * POST /api/membranes/{signal_id}/approve          — auth: project member

v1 only exposes user-drop / simulated webhook shapes. Actual GitHub OAuth
webhook auth is a v2 concern — v1 trusts that anything hitting `/ingest`
came from an authenticated project member.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_persistence import (
    MembraneSignalRepository,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    MembraneService,
    ProjectService,
)

router = APIRouter(prefix="/api", tags=["membrane"])


_SOURCE_KINDS = {
    "git-commit",
    "git-pr",
    "steam-review",
    "steam-forum",
    "rss",
    "user-drop",
    "webhook",
}


class IngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=64)
    source_kind: str = Field(min_length=1, max_length=32)
    source_identifier: str = Field(min_length=1, max_length=512)
    # Bounded client-side; the service trims server-side as well.
    raw_content: str = Field(min_length=0, max_length=20000)


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]


def _get_service(request: Request) -> MembraneService:
    return request.app.state.membrane_service


@router.post("/membranes/ingest")
async def post_ingest(
    body: IngestRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    if body.source_kind not in _SOURCE_KINDS:
        raise HTTPException(status_code=400, detail="invalid_source_kind")

    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=body.project_id, user_id=user.id
    ):
        raise HTTPException(status_code=403, detail="not_a_project_member")

    service = _get_service(request)
    result = await service.ingest(
        project_id=body.project_id,
        source_kind=body.source_kind,
        source_identifier=body.source_identifier,
        raw_content=body.raw_content,
        ingested_by_user_id=user.id,
    )
    if not result.get("ok"):
        err = result.get("error", "ingest_failed")
        status_map = {
            "project_not_found": 404,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result


@router.get("/projects/{project_id}/membranes/recent")
async def get_recent(
    project_id: str,
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(status_code=403, detail="not_a_project_member")
    service = _get_service(request)
    signals = await service.list_for_project(
        project_id, status=status, limit=limit
    )
    return {"ok": True, "signals": signals}


@router.post("/membranes/{signal_id}/approve")
async def post_approve(
    signal_id: str,
    body: ApproveRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)

    # Read the row first to derive project_id for the membership gate.
    async with session_scope(request.app.state.sessionmaker) as session:
        row = await MembraneSignalRepository(session).get(signal_id)
        if row is None:
            raise HTTPException(status_code=404, detail="signal_not_found")
        project_id = row.project_id

    if project_id is not None:
        project_service: ProjectService = request.app.state.project_service
        if not await project_service.is_member(
            project_id=project_id, user_id=user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_project_member")

    result = await service.approve(
        signal_id=signal_id,
        approver_user_id=user.id,
        decision=body.decision,
    )
    if not result.get("ok"):
        err = result.get("error", "approve_failed")
        status_map = {
            "signal_not_found": 404,
            "already_resolved": 409,
            "invalid_decision": 400,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result
