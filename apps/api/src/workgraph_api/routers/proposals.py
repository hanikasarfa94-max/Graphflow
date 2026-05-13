"""Phase B.1 — v0.6.2 generic Proposal surface (API_CONTRACT §"Proposal APIs").

Replaces today's per-kind suggestion endpoints with a single
ProposalType-routed handler. Per BUILD-v062.md §"Phase B":

    proposals.py — generic GET/POST /api/proposals/:id/{accept,
    dismiss,mark-stale} (replaces today's per-kind suggestion
    endpoints; routes by ProposalType)

ProposalType enum (schemas.graphflow.json):
  - routing_suggestion        → wraps IMService accept/dismiss
                                (today's IMSuggestionRow path)
  - task_candidate            → Phase B.2 stub
  - document_draft            → Phase B.2 stub
  - topic_suggestion          → Phase B.2 stub
  - memory_candidate          → forwards to /api/memory-candidates/*
                                in B.2; stubbed for B.1
  - impact_analysis           → Phase B.2 stub
  - capability_explanation    → Phase B.2 stub
  - topic_closure             → Phase B.2 stub

Endpoints:
  * GET   /api/proposals/{id}
  * POST  /api/proposals/{id}/accept
  * POST  /api/proposals/{id}/dismiss
  * POST  /api/proposals/{id}/mark-stale

Dispatch strategy: the proposal id encodes (or, in B.2, we look up)
the ProposalType, then the router fans out to the right backing
service. For B.1 we support the routing_suggestion case end-to-end
because IMSuggestionRow exists today; everything else returns a
501-with-context envelope so the FE can render a clean
"feature wiring in progress" state.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, IMService, ProjectService

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


# ---- enums (mirror schemas.graphflow.json) -------------------------------

ProposalTypeT = Literal[
    "routing_suggestion",
    "task_candidate",
    "document_draft",
    "topic_suggestion",
    "memory_candidate",
    "impact_analysis",
    "capability_explanation",
    "topic_closure",
]

_VALID_PROPOSAL_TYPES: set[str] = {
    "routing_suggestion",
    "task_candidate",
    "document_draft",
    "topic_suggestion",
    "memory_candidate",
    "impact_analysis",
    "capability_explanation",
    "topic_closure",
}

# Kinds we have a backing service for in B.1.
_B1_LIVE_KINDS: set[str] = {"routing_suggestion"}


# ---- request shapes -------------------------------------------------------


class _EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- dispatch -------------------------------------------------------------


async def _classify_proposal(
    proposal_id: str, request: Request
) -> tuple[str, dict[str, Any] | None]:
    """Resolve a proposal_id to its ProposalType + a backing record.

    Phase B.1 heuristic:
      - If IMService.get_suggestion(id) returns a row, it's a
        `routing_suggestion`.
      - Otherwise, we treat it as an unknown / unwired ProposalType
        and fall through to the stub path.

    Phase B.2 introduces a real ProposalRow table with an explicit
    `type` column; this function will become a single DB read.
    """
    im_service: IMService = request.app.state.im_service
    suggestion = await im_service.get_suggestion(proposal_id)
    if suggestion is not None:
        return "routing_suggestion", suggestion
    # TODO(Phase B.2): query ProposalRow for the canonical type. For
    # B.1 unknown ids are 404'd by the caller.
    return "unknown", None


def _ensure_known_type(kind: str) -> None:
    if kind == "unknown":
        raise HTTPException(status_code=404, detail="proposal_not_found")
    if kind not in _VALID_PROPOSAL_TYPES:
        raise HTTPException(status_code=400, detail="invalid_proposal_type")


def _stub_for_kind(kind: str) -> HTTPException:
    """Consistent 501 envelope for ProposalTypes B.1 doesn't wire yet."""
    return HTTPException(
        status_code=501,
        detail=f"Phase B.2 wires {kind} dispatch",
    )


# ---- endpoints ------------------------------------------------------------


@router.get("/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Return a proposal envelope.

    Always returns `{id, type, payload, mutates_state: false}`. Per
    API_CONTRACT.md: proposals never mutate state on read.
    """
    kind, record = await _classify_proposal(proposal_id, request)
    _ensure_known_type(kind)

    if kind == "routing_suggestion":
        # Membership gate before exposing the backing row.
        project_service: ProjectService = request.app.state.project_service
        assert record is not None
        if not await project_service.is_member(
            project_id=record["project_id"], user_id=user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_member")
        return {
            "id": proposal_id,
            "type": "routing_suggestion",
            "payload": record,
            "mutates_state": False,
        }

    # Other kinds: known type, but no backing record yet.
    raise _stub_for_kind(kind)


@router.post("/{proposal_id}/accept")
async def post_accept_proposal(
    proposal_id: str,
    request: Request,
    _body: _EmptyBody | None = None,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Accept a proposal. Dispatches by ProposalType.

    B.1: routing_suggestion → IMService.accept. Everything else 501.
    """
    kind, record = await _classify_proposal(proposal_id, request)
    _ensure_known_type(kind)

    if kind == "routing_suggestion":
        assert record is not None
        project_service: ProjectService = request.app.state.project_service
        if not await project_service.is_member(
            project_id=record["project_id"], user_id=user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_member")
        im_service: IMService = request.app.state.im_service
        result = await im_service.accept(
            suggestion_id=proposal_id, actor_id=user.id
        )
        if not result.get("ok"):
            err = result.get("error", "accept_failed")
            status = 403 if err == "owner_only" else 409
            raise HTTPException(status_code=status, detail=err)
        return {"proposal_id": proposal_id, "type": kind, "result": result}

    raise _stub_for_kind(kind)


@router.post("/{proposal_id}/dismiss")
async def post_dismiss_proposal(
    proposal_id: str,
    request: Request,
    _body: _EmptyBody | None = None,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Dismiss a proposal. Dispatches by ProposalType."""
    kind, record = await _classify_proposal(proposal_id, request)
    _ensure_known_type(kind)

    if kind == "routing_suggestion":
        assert record is not None
        project_service: ProjectService = request.app.state.project_service
        if not await project_service.is_member(
            project_id=record["project_id"], user_id=user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_member")
        im_service: IMService = request.app.state.im_service
        result = await im_service.dismiss(
            suggestion_id=proposal_id, actor_id=user.id
        )
        if not result.get("ok"):
            raise HTTPException(
                status_code=409, detail=result.get("error", "dismiss_failed")
            )
        return {"proposal_id": proposal_id, "type": kind, "result": result}

    raise _stub_for_kind(kind)


@router.post("/{proposal_id}/mark-stale")
async def post_mark_stale_proposal(
    proposal_id: str,
    request: Request,
    _body: _EmptyBody | None = None,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Mark a proposal stale. Distinct from dismiss — stale means "the
    underlying context drifted; this proposal no longer applies",
    not "I considered and rejected it".

    For routing_suggestion we route through IMService.dismiss with a
    `stale` flag for now. Phase B.2 introduces a dedicated
    `mark_stale` service method so the wire shape captures the
    distinction.
    """
    kind, record = await _classify_proposal(proposal_id, request)
    _ensure_known_type(kind)

    if kind == "routing_suggestion":
        assert record is not None
        project_service: ProjectService = request.app.state.project_service
        if not await project_service.is_member(
            project_id=record["project_id"], user_id=user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_member")
        # TODO(Phase B.2): IMService.mark_stale — distinct from
        # dismiss in the lifecycle log. For B.1 we treat stale as a
        # tagged dismiss so the row exits the open inbox.
        im_service: IMService = request.app.state.im_service
        result = await im_service.dismiss(
            suggestion_id=proposal_id, actor_id=user.id
        )
        if not result.get("ok"):
            raise HTTPException(
                status_code=409,
                detail=result.get("error", "mark_stale_failed"),
            )
        return {
            "proposal_id": proposal_id,
            "type": kind,
            "result": result,
            "reason": "stale",
        }

    raise _stub_for_kind(kind)
