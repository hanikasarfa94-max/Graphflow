"""Phase D membrane ingestion endpoints (vision §5.12).

  * POST /api/membranes/ingest                       — auth: project member
  * GET  /api/projects/{project_id}/membranes/recent — auth: project member
  * POST /api/membranes/{signal_id}/approve          — auth: project member

Phase 2.A active-side additions (vision §5.12 active membrane):
  * POST   /api/projects/{id}/membrane/paste                    — member
  * POST   /api/projects/{id}/membrane/subscriptions            — owner
  * GET    /api/projects/{id}/membrane/subscriptions            — member
  * DELETE /api/projects/{id}/membrane/subscriptions/{sub_id}   — owner
  * POST   /api/projects/{id}/membrane/scan-now                 — owner

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
    ProjectMemberRepository,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    MembraneIngestService,
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


# ---------------------------------------------------------------------------
# Phase 2.A — active membrane (user paste + subscriptions + scan-now)
# ---------------------------------------------------------------------------


class PasteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2000)
    note: str | None = Field(default=None, max_length=500)


class SubscriptionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["rss", "search_query"]
    url_or_query: str = Field(min_length=1, max_length=1000)


def _get_ingest_service(request: Request) -> MembraneIngestService:
    return request.app.state.membrane_ingest_service


async def _require_member(
    request: Request, project_id: str, user_id: str
) -> None:
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(
        project_id=project_id, user_id=user_id
    ):
        raise HTTPException(status_code=403, detail="not_a_project_member")


async def _require_owner(
    request: Request, project_id: str, user_id: str
) -> None:
    """Owner-only gate for mutation of the active-scan configuration.

    Mirrors the role-check pattern used by silent_consensus / handoff /
    skill_atlas. Any project member can paste a URL (`/paste`); only
    owners configure feeds and trigger manual scans (`/subscriptions`,
    `/scan-now`).
    """
    async with session_scope(request.app.state.sessionmaker) as session:
        rows = await ProjectMemberRepository(session).list_for_project(
            project_id
        )
    for r in rows:
        if r.user_id == user_id and r.role == "owner":
            return
    # If the user isn't even a member, 403 with the standard detail.
    raise HTTPException(status_code=403, detail="not_a_project_owner")


@router.post("/projects/{project_id}/membrane/paste")
async def post_paste(
    project_id: str,
    body: PasteRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_member(request, project_id, user.id)
    service = _get_ingest_service(request)
    result = await service.ingest_url(
        project_id=project_id,
        url=body.url,
        source_user_id=user.id,
        note=body.note,
    )
    if not result.get("ok"):
        err = result.get("error", "ingest_failed")
        status_map = {
            "project_not_found": 404,
            "fetch_failed": 400,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result


@router.post("/projects/{project_id}/membrane/subscriptions")
async def post_subscription(
    project_id: str,
    body: SubscriptionCreateRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_owner(request, project_id, user.id)
    service = _get_ingest_service(request)
    result = await service.create_subscription(
        project_id=project_id,
        kind=body.kind,
        url_or_query=body.url_or_query,
        created_by_user_id=user.id,
    )
    if not result.get("ok"):
        err = result.get("error", "create_failed")
        status_map = {
            "project_not_found": 404,
            "invalid_kind": 400,
            "invalid_rss_url": 400,
            "empty_value": 400,
            "value_too_long": 400,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result


@router.get("/projects/{project_id}/membrane/subscriptions")
async def list_subscriptions(
    project_id: str,
    request: Request,
    active_only: bool = Query(default=True),
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_member(request, project_id, user.id)
    service = _get_ingest_service(request)
    subs = await service.list_subscriptions(project_id, active_only=active_only)
    return {"ok": True, "subscriptions": subs}


@router.delete("/projects/{project_id}/membrane/subscriptions/{sub_id}")
async def delete_subscription(
    project_id: str,
    sub_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    await _require_owner(request, project_id, user.id)
    service = _get_ingest_service(request)
    result = await service.deactivate_subscription(
        project_id=project_id, sub_id=sub_id
    )
    if not result.get("ok"):
        err = result.get("error", "delete_failed")
        status_map = {"not_found": 404}
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result


@router.post("/projects/{project_id}/membrane/scan-now")
async def post_scan_now(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Manual trigger for the active-scan pipeline.

    Production wires this via an external cron (Aliyun / Windows Task
    Scheduler) so the scheduler itself stays infra, not code. See
    services/membrane_ingest.py:MembraneIngestService.run_active_scan
    for the contract.
    """
    await _require_owner(request, project_id, user.id)
    service = _get_ingest_service(request)
    scan = await service.run_active_scan(project_id)
    rss = await service.poll_rss_subscriptions(project_id)
    total_new = int(scan.get("new_signals", 0)) + int(rss.get("new_signals", 0))
    return {
        "ok": True,
        "scan": scan,
        "rss": rss,
        "new_signals": total_new,
    }
