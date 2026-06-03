"""Phase L — sub-agent routing endpoints.

North-star §"Sub-agent and routing architecture". Endpoints are thin
wrappers around RoutingService; the heavy lifting (dispatch, reply,
stream mirroring, DM log) lives in the service.

Routes (all require auth):
  * POST /api/routing/dispatch          — source creates a routed signal
  * POST /api/routing/{signal_id}/reply — target replies with pick/custom
  * GET  /api/routing/inbox             — signals targeted at me
  * GET  /api/routing/outbox            — signals I sent
  * GET  /api/routing/{signal_id}       — full signal (caller must be
                                          source or target)
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    PersonalStreamService,
    RoutingService,
)

router = APIRouter(prefix="/api/routing", tags=["routing"])


class BackgroundSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=32)
    snippet: str = Field(min_length=1, max_length=4000)
    reference_id: str | None = Field(default=None, max_length=64)


class OptionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=256)
    kind: str = Field(default="action", max_length=32)
    background: str = Field(default="", max_length=4000)
    reason: str = Field(default="", max_length=2000)
    tradeoff: str = Field(default="", max_length=2000)
    weight: float = Field(default=0.5, ge=0.0, le=1.0)


class DispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)
    framing: str = Field(min_length=1, max_length=4000)
    background: list[BackgroundSnippet] = Field(default_factory=list)
    options: list[OptionSpec] = Field(default_factory=list, max_length=10)


class ReplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str | None = Field(default=None, max_length=64)
    custom_text: str | None = Field(default=None, max_length=4000)


class ConfirmProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_user_id: str = Field(min_length=1, max_length=64)
    # Optional refined B-facing framing the user edited in the slim send
    # surface (the disclosure gate). When present it overrides the
    # proposal's stored framing so the routed signal carries an A→B-voice
    # ask. Empty / null = use the original proposal framing.
    refined_framing: str | None = Field(default=None, max_length=4000)


# ---- response shapes (C1-C) -----------------------------------------------
# Mirror RoutingService._shape. background/options are free-form JSON columns
# (list of arbitrary snippet/option dicts) → list[dict]; reply is a nullable
# JSON dict. trace_id/project_id/reply/responded_at nullable per RoutedSignalRow.


class RoutingSignal(BaseModel):
    id: str
    trace_id: str | None = None
    source_user_id: str
    target_user_id: str
    source_stream_id: str
    target_stream_id: str
    project_id: str | None = None
    framing: str
    background: list[dict[str, Any]] = Field(default_factory=list)
    options: list[dict[str, Any]] = Field(default_factory=list)
    status: str
    reply: dict[str, Any] | None = None
    created_at: str | None = None
    responded_at: str | None = None


class RoutingSignalListResponse(BaseModel):
    signals: list[RoutingSignal]


class RoutingSignalDetailResponse(BaseModel):
    ok: bool
    signal: RoutingSignal


def _get_service(request: Request) -> RoutingService:
    return request.app.state.routing_service


def _get_personal_service(request: Request) -> PersonalStreamService:
    return request.app.state.personal_service


@router.post("/dispatch")
async def post_dispatch(
    body: DispatchRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    result = await service.dispatch(
        source_user_id=user.id,
        target_user_id=body.target_user_id,
        framing=body.framing,
        background=[b.model_dump() for b in body.background],
        options=[o.model_dump() for o in body.options],
        project_id=body.project_id,
    )
    if not result.get("ok"):
        err = result.get("error", "dispatch_failed")
        # R2 — grounding rejection. 422 Unprocessable Entity, JSON body
        # includes `alternatives` so the caller can re-prompt with a
        # grounded target. We bypass HTTPException for this code so the
        # alternatives don't get stringified by the global error handler.
        if err == "target_not_grounded":
            return JSONResponse(
                status_code=422,
                content={
                    "ok": False,
                    "error": "target_not_grounded",
                    "alternatives": result.get("alternatives", []),
                },
            )
        status_map = {
            "cannot_route_to_self": 400,
            "target_not_found": 404,
            "source_not_project_member": 403,
            "target_not_project_member": 400,
        }
        raise HTTPException(
            status_code=status_map.get(err, 400), detail=err
        )
    return result


@router.post("/proposals/{proposal_id}/confirm")
async def post_confirm_proposal(
    proposal_id: str,
    body: ConfirmProposalRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Canonical "Route to X" confirm for a discovery route-proposal.

    Phase B.2: the slim My-AI send surface posts here when the user
    accepts the edge agent's route proposal. Reuses the existing
    PersonalStreamService.confirm_route logic unchanged — proposal
    ownership + target validation, server-generated recipient reply
    options, dispatch to a RoutingSignal, the refined_framing disclosure
    gate, and the ambient "✓ asked X" turn. Replaced the older
    POST /api/personal/route/{proposal_id}/confirm (removed in B.2).
    """
    service = _get_personal_service(request)
    result = await service.confirm_route(
        proposal_id=proposal_id,
        source_user_id=user.id,
        target_user_id=body.target_user_id,
        refined_framing=body.refined_framing,
    )
    if not result.get("ok"):
        err = result.get("error", "confirm_failed")
        status_map = {
            "proposal_not_found": 404,
            "proposal_not_ours": 403,
            "target_not_in_proposal": 400,
            "cannot_route_to_self": 400,
            "target_not_found": 404,
            "source_not_project_member": 403,
            "target_not_project_member": 400,
            "option_generation_failed": 502,
        }
        raise HTTPException(status_code=status_map.get(err, 400), detail=err)
    return result


@router.post("/{signal_id}/reply")
async def post_reply(
    signal_id: str,
    body: ReplyRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Record a target's reply.

    Wired through `PersonalStreamService.handle_reply` (not
    `RoutingService.reply` directly) so the source's sub-agent frames the
    reply into their personal stream as an `edge-reply-frame` card in the
    same request. This closes the signal-chain loop the north-star
    describes in §"The canonical interaction" step 6.

    `handle_reply` itself calls `routing_service.reply` internally, so the
    reply persistence + DM mirror + `routed-reply` message all still
    happen; the only addition is the frame card.

    On frame-agent errors we still return `ok: true` because the reply is
    already persisted — the UI can poll/ws-refresh to pick it up. See
    PersonalStreamService.handle_reply for the fall-through behavior.
    """
    personal_service = _get_personal_service(request)
    result = await personal_service.handle_reply(
        signal_id=signal_id,
        replier_user_id=user.id,
        option_id=body.option_id,
        custom_text=body.custom_text,
    )
    if not result.get("ok"):
        err = result.get("error", "reply_failed")
        status_map = {
            "signal_not_found": 404,
            "not_the_target": 403,
            "already_replied": 409,
            "empty_reply": 400,
        }
        raise HTTPException(
            status_code=status_map.get(err, 400), detail=err
        )
    return result


@router.post("/{signal_id}/accept")
async def post_accept(
    signal_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Source-side acknowledgment that closes a replied signal.

    Persists `status='accepted'` so a refresh after the click does NOT
    reopen the Accept button. Only the source can accept; the signal
    must already be in `replied`. Re-accept is a no-op (idempotent).
    """
    service = _get_service(request)
    result = await service.accept(
        signal_id=signal_id, accepter_user_id=user.id
    )
    if not result.get("ok"):
        err = result.get("error", "accept_failed")
        status_map = {
            "signal_not_found": 404,
            "not_the_source": 403,
            "not_accepted_state": 409,
        }
        raise HTTPException(
            status_code=status_map.get(err, 400), detail=err
        )
    return result


@router.get("/inbox", response_model=RoutingSignalListResponse)
async def get_inbox(
    request: Request,
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    items = await service.get_for_user(
        user.id, kind="inbound", status=status, limit=limit
    )
    return {"signals": items}


@router.get("/outbox", response_model=RoutingSignalListResponse)
async def get_outbox(
    request: Request,
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    items = await service.get_for_user(
        user.id, kind="outbound", status=status, limit=limit
    )
    return {"signals": items}


@router.get("/{signal_id}", response_model=RoutingSignalDetailResponse)
async def get_signal(
    signal_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    result = await service.get(signal_id, viewer_id=user.id)
    if not result.get("ok"):
        err = result.get("error", "not_found")
        status_map = {
            "signal_not_found": 404,
            "not_a_participant": 403,
        }
        raise HTTPException(
            status_code=status_map.get(err, 400), detail=err
        )
    return result
