"""Gated-proposal router (migration 0014) — Scene 2 routing HTTP surface.

Endpoints:

  POST   /api/projects/{project_id}/gated-proposals
      proposer starts a proposal for a gated decision class. Body:
      { decision_class, proposal_body, apply_actions? }. Response:
      { proposal }. 4xx maps listed in _ERROR_STATUS; 'no_gate_keeper'
      lets the caller fall back to the normal (non-gated) flow.

  GET    /api/projects/{project_id}/gated-proposals
      list proposals on the project. Query: ?status=pending|approved|
      denied|withdrawn. Any project member sees all statuses for audit.

  GET    /api/gated-proposals/pending
      list proposals pending for the CURRENT USER (as gate-keeper).
      Sidebar uses this to show the approval queue across projects.

  GET    /api/projects/{project_id}/gate-keeper-map
      any project member reads the current map.

  PUT    /api/projects/{project_id}/gate-keeper-map
      owner-role member writes the map. Body: { map: {class: user_id} }.
      Validates each class is in VALID_DECISION_CLASSES and each user_id
      is a current project member.

  POST   /api/gated-proposals/{proposal_id}/approve
      gate-keeper-only. Body: { rationale? }. Creates DecisionRow with
      lineage; returns { proposal, decision_id }.

  POST   /api/gated-proposals/{proposal_id}/deny
      gate-keeper-only. Body: { resolution_note? }.

  POST   /api/gated-proposals/{proposal_id}/withdraw
      proposer-only. Rescinds a still-pending proposal.

Permission model matches the service layer — the router is a thin
HTTP shell; 403 / 404 / 409 are mapped from GatedProposalError codes.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    GatedProposalError,
    GatedProposalService,
    VALID_DECISION_CLASSES,
)
from workgraph_persistence import (
    ProjectMemberRepository,
    ProjectRow,
    session_scope,
)


router = APIRouter(tags=["gated_proposals"])


_ERROR_STATUS: dict[str, int] = {
    "empty_proposal_body": 400,
    "invalid_decision_class": 400,
    "invalid_map_entry": 400,
    "project_not_found": 404,
    "proposal_not_found": 404,
    "proposer_not_member": 403,
    "not_gate_keeper": 403,
    "not_proposer": 403,
    "not_owner": 403,
    "no_gate_keeper": 409,
    "proposer_is_gate_keeper": 409,
    "gate_keeper_not_member": 409,
    "already_resolved": 409,
}


def _get_service(request: Request) -> GatedProposalService:
    service = getattr(request.app.state, "gated_proposals_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail="gated_proposals_unavailable"
        )
    return service


def _map_error(exc: GatedProposalError) -> HTTPException:
    status = _ERROR_STATUS.get(exc.code, exc.status)
    return HTTPException(status_code=status, detail=exc.code)


class ProposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_class: str = Field(min_length=1, max_length=32)
    proposal_body: str = Field(min_length=1, max_length=4000)
    apply_actions: list[dict[str, Any]] = Field(default_factory=list)


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rationale: str | None = Field(default=None, max_length=2000)


class DenyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution_note: str | None = Field(default=None, max_length=2000)


class GateKeeperMapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Map keys are decision_class strings; values are user_id strings.
    # Empty values remove a class from the map.
    map: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------- propose


@router.post("/api/projects/{project_id}/gated-proposals")
async def post_propose(
    project_id: str,
    body: ProposeRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _get_service(request)
    try:
        result = await service.propose(
            project_id=project_id,
            proposer_user_id=user.id,
            decision_class=body.decision_class,
            proposal_body=body.proposal_body,
            apply_actions=body.apply_actions,
        )
    except GatedProposalError as exc:
        raise _map_error(exc) from exc
    return result


# --------------------------------------------------------------- listings


@router.get("/api/projects/{project_id}/gated-proposals")
async def list_for_project(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
    status: str | None = None,
) -> dict[str, Any]:
    service = _get_service(request)
    # Membership check — we don't leak proposal metadata outside the
    # project. Owners / admins / members all see the same slice for v0.
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        if not await ProjectMemberRepository(session).is_member(
            project_id, user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_member")
    proposals = await service.list_for_project(
        project_id=project_id, status=status, limit=100
    )
    return {"ok": True, "proposals": proposals}


@router.get("/api/gated-proposals/pending")
async def list_pending_for_me(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _get_service(request)
    proposals = await service.list_pending_for_gate_keeper(
        user_id=user.id, limit=100
    )
    return {"ok": True, "proposals": proposals}


@router.get("/api/gated-proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Single-proposal fetch for the pending-approval and resolved
    cards in the gate-keeper / proposer streams. Visibility: proposer,
    gate-keeper, and any full-tier project member can read (audit).
    """
    service = _get_service(request)
    proposal = await service.get(proposal_id=proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="proposal_not_found")
    # Visibility: proposer + gate-keeper always; other project members
    # allowed so the audit / list flows work from the same endpoint.
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        if not await ProjectMemberRepository(session).is_member(
            proposal["project_id"], user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_member")
    return {"ok": True, "proposal": proposal}


# --------------------------------------------------------------- map CRUD


@router.get("/api/projects/{project_id}/gate-keeper-map")
async def get_gate_keeper_map(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        if not await ProjectMemberRepository(session).is_member(
            project_id, user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_member")
        project = (
            await session.execute(
                select(ProjectRow).where(ProjectRow.id == project_id)
            )
        ).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="project_not_found")
        gate_map = dict(project.gate_keeper_map or {})
    return {
        "ok": True,
        "map": gate_map,
        "valid_classes": sorted(VALID_DECISION_CLASSES),
    }


@router.put("/api/projects/{project_id}/gate-keeper-map")
async def put_gate_keeper_map(
    project_id: str,
    body: GateKeeperMapRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    # Validate classes + types up-front. Empty user_id values are
    # allowed at this stage — they signal "remove this class's mapping"
    # and are filtered out below. Non-string uids are a client bug.
    for cls, uid in body.map.items():
        if cls not in VALID_DECISION_CLASSES:
            raise HTTPException(
                status_code=400, detail="invalid_decision_class"
            )
        if not isinstance(uid, str):
            raise HTTPException(
                status_code=400, detail="invalid_map_entry"
            )

    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        pm_repo = ProjectMemberRepository(session)
        members = await pm_repo.list_for_project(project_id)
        caller_row = next(
            (m for m in members if m.user_id == user.id), None
        )
        if caller_row is None:
            raise HTTPException(status_code=403, detail="not_a_member")
        if (caller_row.role or "").lower() != "owner":
            raise HTTPException(status_code=403, detail="not_owner")

        member_ids = {m.user_id for m in members}
        cleaned: dict[str, str] = {}
        for cls, uid in body.map.items():
            # Empty / whitespace-only value removes the mapping.
            if not uid or not uid.strip():
                continue
            if uid not in member_ids:
                raise HTTPException(
                    status_code=400,
                    detail="gate_keeper_not_member",
                )
            cleaned[cls] = uid

        project = (
            await session.execute(
                select(ProjectRow).where(ProjectRow.id == project_id)
            )
        ).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="project_not_found")
        project.gate_keeper_map = cleaned
        await session.flush()
        stored = dict(project.gate_keeper_map or {})
    return {"ok": True, "map": stored}


# --------------------------------------------------------------- resolve


@router.post("/api/gated-proposals/{proposal_id}/approve")
async def post_approve(
    proposal_id: str,
    body: ResolveRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _get_service(request)
    try:
        return await service.approve(
            proposal_id=proposal_id,
            acting_user_id=user.id,
            rationale=body.rationale,
        )
    except GatedProposalError as exc:
        raise _map_error(exc) from exc


@router.post("/api/gated-proposals/{proposal_id}/deny")
async def post_deny(
    proposal_id: str,
    body: DenyRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _get_service(request)
    try:
        return await service.deny(
            proposal_id=proposal_id,
            acting_user_id=user.id,
            resolution_note=body.resolution_note,
        )
    except GatedProposalError as exc:
        raise _map_error(exc) from exc


@router.post("/api/gated-proposals/{proposal_id}/withdraw")
async def post_withdraw(
    proposal_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _get_service(request)
    try:
        return await service.withdraw(
            proposal_id=proposal_id, acting_user_id=user.id
        )
    except GatedProposalError as exc:
        raise _map_error(exc) from exc
