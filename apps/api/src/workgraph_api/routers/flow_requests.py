"""Phase B.1 — v0.6.2 Flow Requests surface (API_CONTRACT §"Flow Requests").

Wraps the existing `flows.py` projection + action surface as the v0.6.2
Flow Request lifecycle. The underlying domain rows are unchanged; this
router re-shapes the contract to:

    draft → attach → send → respond → (optional) generate-memory-candidate

Endpoints:

  * POST  /api/flow-requests/draft
  * PATCH /api/flow-requests/{id}/attachments
  * POST  /api/flow-requests/{id}/send
  * POST  /api/flow-requests/{id}/respond
  * POST  /api/flow-responses/{id}/generate-memory-candidate

Load-bearing invariants (INVARIANT_TESTS.md):

  * Flow response memory decoupling — `respond` returns
    `memory_candidate_prompt.actions = ["review", "skip", "later"]` and
    NEVER `memory_auto_accepted: true`. Flow acceptance and memory
    acceptance are independent state transitions; the user always opts
    in to memory writes after the flow closes.

  * Skip reversible — `generate-memory-candidate` regenerates a
    candidate after a user skipped, so the FE can offer reopen.

Phase B.1 wires contract shape only. The full draft → send pipeline
lands in Phase B.3 once FlowActionService grows a `draft / send / reply`
surface alongside today's source-side `accept / counter_back / ...`.
For now: stub envelopes with TODO punts; the wire shape is what the
invariant tests check.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    FlowProjectionService,
    PersonalStreamService,
    ProjectService,
)
from workgraph_api.services.flow_projection import (
    FlowSingletonForbidden,
    FlowSingletonKindUnsupported,
    FlowSingletonNotFound,
)

router = APIRouter(tags=["flow-requests"])


# ---- enums (mirror schemas.graphflow.json) -------------------------------

# Mirrored here, not imported, so the router declares its own wire
# contract — same pattern as flows.py (_Bucket, _Recipe).
FlowRequestType = Literal[
    "confirm",
    "feedback",
    "review",
    "clarification",
    "handoff",
    "accept_task",
    "delegate",
    "approval",
]

# AllowedAction subset for memory candidate prompts. The full enum is in
# schemas.graphflow.json AllowedAction; here we lock the three the
# memory-decoupling invariant pins.
_MEMORY_PROMPT_ACTIONS: list[str] = ["review", "skip", "later"]


# ---- error envelope ------------------------------------------------------

# Service-error → HTTP status. Same shape as flow_actions.ERROR_HTTP_STATUS.
# B.3 grows real codes when FlowActionService gains draft/send/respond
# methods; B.1 only ships shape so this map stays minimal.
_STATUS_MAP: dict[str, int] = {
    "flow_request_not_found": 404,
    "flow_response_not_found": 404,
    "not_a_scope_member": 403,
    "not_supported_yet": 422,
    "not_respondable_yet": 422,
    "not_the_target": 403,
    "already_replied": 409,
    "empty_response": 422,
    "signal_not_found": 404,
    "lint_paused": 409,
    "validation_error": 422,
    "draft_send_failed": 502,
}


def _raise_service_error(code: str, *, detail: str | None = None) -> None:
    raise HTTPException(
        status_code=_STATUS_MAP.get(code, 400),
        detail=detail or code,
    )


# ---- request shapes ------------------------------------------------------


class FlowRequestDraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_id: str = Field(min_length=1, max_length=64)
    kind: FlowRequestType
    title: str = Field(min_length=1, max_length=400)
    body: str = Field(min_length=1, max_length=8000)
    target_user_id: str | None = Field(default=None, max_length=64)
    target_role: str | None = Field(default=None, max_length=64)
    # Caller can pre-attach evidence in the draft call; otherwise PATCH
    # /attachments grows the list before /send.
    attachments: list[str] = Field(default_factory=list)


class FlowRequestAttachmentsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Full replacement set per PATCH semantics — caller sends the
    # desired state, server reconciles. Add/remove deltas can ride a
    # different endpoint if needed.
    attachments: list[str] = Field(default_factory=list)


class FlowRequestSendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Optional override; defaults to whatever was set at draft time.
    note: str | None = Field(default=None, max_length=2000)


class FlowRequestRespondBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # RW-9 (2026-05-13). The respond body is now a discriminated union
    # on `kind`. Only `direct_response` is wired — a text reply that
    # the target sends back to the source. Other response shapes
    # (delegate / approve+note / counter) remain B.3+ work and are
    # NOT accepted here.
    kind: Literal["direct_response"]
    text: str = Field(min_length=1, max_length=4000)


# ---- helpers -------------------------------------------------------------


def _get_project_service(request: Request) -> ProjectService:
    return request.app.state.project_service


async def _gate_scope_membership(
    request: Request, *, scope_id: str, user_id: str
) -> None:
    """Membership gate for any mutation that touches a scope-bound
    object. `scope_id` is the v0.6.2 alias for `project_id`."""
    project_service = _get_project_service(request)
    if not await project_service.is_member(
        project_id=scope_id, user_id=user_id
    ):
        _raise_service_error("not_a_scope_member")


def _get_projection_service(request: Request) -> FlowProjectionService:
    return request.app.state.flow_projection_service


# ---- read endpoint (RW-2.1) ----------------------------------------------


@router.get("/api/flow-requests")
async def list_flow_requests(
    request: Request,
    scope_id: str = Query(min_length=1, max_length=64),
    bucket: Literal[
        "needs_me", "waiting_on_others", "awaiting_membrane", "recent"
    ]
    | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """List flow packets for a scope.

    v0.6.2 alias for the existing `/api/projects/{project_id}/flows`
    surface — `scope_id` is the API name; `project_id` is the DB column.
    Wraps FlowProjectionService.list_for_project. Returns the same
    `{packets, participants}` envelope so the FE doesn't need to relearn
    the wire shape.

    RW-2.1 lands the read path. Mutation endpoints (draft / send /
    respond) below remain Phase B.3 stubs.
    """
    await _gate_scope_membership(request, scope_id=scope_id, user_id=user.id)
    projection = _get_projection_service(request)
    return await projection.list_for_project(
        project_id=scope_id,
        viewer_user_id=user.id,
        status=None,
        bucket=bucket,
        recipe=None,
        limit=limit,
    )


# ---- read endpoint (RW-9.1) — singleton ----------------------------------


@router.get("/api/flow-requests/{flow_request_id}")
async def get_flow_request(
    flow_request_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Singleton fetch for one flow request.

    The id is the synthetic packet id from the projection — currently
    `route:<routed_signal_id>` is the only kind wired for singleton
    read (and the only kind wired for respond). Other packet kinds
    raise 422 not_supported_yet so the FE drawer can render a stable,
    honest "not wired for this kind yet" state.

    Membership is checked inside the service via `_visible_to`, which
    is per-packet — project membership alone does NOT grant access to
    a route between two members the viewer doesn't participate in.
    """
    projection = _get_projection_service(request)
    try:
        return await projection.get_packet(
            flow_id=flow_request_id, viewer_user_id=user.id
        )
    except FlowSingletonNotFound as err:
        raise HTTPException(
            status_code=_STATUS_MAP["flow_request_not_found"],
            detail="flow_request_not_found",
        ) from err
    except FlowSingletonForbidden as err:
        raise HTTPException(
            status_code=_STATUS_MAP["not_a_scope_member"],
            detail="not_a_scope_member",
        ) from err
    except FlowSingletonKindUnsupported as err:
        # 422 with a stable code so the FE can render the right
        # honest-empty drawer state for that kind.
        raise HTTPException(
            status_code=_STATUS_MAP["not_supported_yet"],
            detail=f"not_supported_yet:{err.kind}",
        ) from err


def _empty_memory_candidate_prompt() -> dict[str, Any]:
    """Default `memory_candidate_prompt` envelope when no candidate is
    produced yet. The actions list is the load-bearing piece — even
    with no candidate, the FE expects ["review", "skip", "later"] so
    Skip can be reversed via generate-memory-candidate later.
    """
    return {
        "has_candidate": False,
        "candidate_id": None,
        # Locked by INVARIANT_TESTS.md §"Flow response memory decoupling".
        "actions": list(_MEMORY_PROMPT_ACTIONS),
    }


# ---- endpoints -----------------------------------------------------------


@router.post("/api/flow-requests/draft")
async def draft_flow_request(
    body: FlowRequestDraftBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Create a flow-request draft.

    Membership gate on `scope_id`. Body is held server-side until
    /send. Returns the draft id + initial shape so the FE can wire
    edit-before-send.
    """
    await _gate_scope_membership(
        request, scope_id=body.scope_id, user_id=user.id
    )

    # TODO(Phase B.3): wire to FlowActionService.draft once the
    # surface exists; today flow_actions.py only owns source-side
    # accept / counter_back / escalate / custom_followup on existing
    # routed signals. Draft creation is a new code path.
    return {
        "ok": True,
        "flow_request_id": "flowreq_draft_pending",
        "scope_id": body.scope_id,
        "kind": body.kind,
        "title": body.title,
        "body": body.body,
        "target_user_id": body.target_user_id,
        "target_role": body.target_role,
        "attachments": list(body.attachments),
        "status": "draft",
    }


@router.patch("/api/flow-requests/{flow_request_id}/attachments")
async def patch_flow_request_attachments(
    flow_request_id: str,
    body: FlowRequestAttachmentsBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Replace the attachment set on a draft flow request.

    Membership is checked via the underlying scope of the flow request
    once B.3 wires real lookup; for B.1, the shape is the contract.
    """
    # TODO(Phase B.3): resolve flow_request_id → scope_id and run
    # membership gate against that scope. Today flow drafts don't
    # persist, so there's nothing to look up.
    return {
        "ok": True,
        "flow_request_id": flow_request_id,
        "attachments": list(body.attachments),
    }


@router.post("/api/flow-requests/{flow_request_id}/send")
async def send_flow_request(
    flow_request_id: str,
    body: FlowRequestSendBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Transition a draft to `sent`, addressing it to its target.

    The send transition is what registers the flow request as a Flow
    Packet in the existing `flows.py` projection.
    """
    # TODO(Phase B.3): wire to FlowActionService.send once the surface
    # lands. Today's flow projection assembles packets from existing
    # signal rows; a v0.6.2-native flow_request row is a B.3 schema
    # addition.
    return {
        "ok": True,
        "flow_request_id": flow_request_id,
        "status": "sent",
        "note": body.note,
    }


@router.post("/api/flow-requests/{flow_request_id}/respond")
async def respond_to_flow_request(
    flow_request_id: str,
    body: FlowRequestRespondBody,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Target-side response to a flow request.

    RW-9 (2026-05-13). Now a real endpoint for `route:` packets — the
    text body is recorded as the routed-signal reply (custom_text)
    via PersonalStreamService.handle_reply, which:
      1. flips RoutedSignalRow.status pending → replied
      2. posts an `edge-reply-frame` into the source's personal stream
      3. mirrors a `routed-dm-log` summary into the source↔target DM

    Other packet kinds (kb_review / handoff / decision / manual_*) are
    NOT respondable through this endpoint — they have their own gates
    (Membrane review, handoff acceptance, decision crystallization)
    that live behind dedicated routers. We return 422 here so the FE
    can render an honest "not respondable yet" state.

    Invariant (INVARIANT_TESTS.md §"Flow response memory decoupling"):
    the response envelope carries `memory_candidate_prompt` with the
    locked `["review", "skip", "later"]` action set, and NEVER sets
    `memory_auto_accepted: true`. Memory acceptance is a second,
    independent transition the user takes from the prompt.
    """
    kind, _, ref_id = flow_request_id.partition(":")
    if kind != "route" or not ref_id:
        _raise_service_error(
            "not_respondable_yet",
            detail=f"not_respondable_yet:{kind or 'unknown'}",
        )

    # PersonalStreamService.handle_reply wraps RoutingService.reply +
    # adds the edge-reply-frame card. The frame card is what makes the
    # source's stream show the reply in the source's voice, so we go
    # through personal_service rather than calling routing directly.
    personal_service: PersonalStreamService = (
        request.app.state.personal_service
    )
    result = await personal_service.handle_reply(
        signal_id=ref_id,
        replier_user_id=user.id,
        custom_text=body.text,
    )
    if not result.get("ok"):
        err = result.get("error", "reply_failed")
        # Pass through the routing service's error vocabulary verbatim
        # — it's already part of the public routing surface and stays
        # the same here so the FE can share error copy.
        raise HTTPException(
            status_code=_STATUS_MAP.get(err, 400),
            detail=err,
        )

    return {
        "ok": True,
        "flow_request_id": flow_request_id,
        # `response_kind` echoes the body kind so the FE can route the
        # post-success refresh into the right surface (the source's
        # stream, the routed signal, the flow center list).
        "response_kind": body.kind,
        # Real routed signal payload from RoutingService.reply — the
        # FE can render the recorded reply immediately without a
        # follow-up GET.
        "signal": result.get("signal"),
        # Locked envelope. INVARIANT_TESTS.md §"Flow response memory
        # decoupling" asserts on `.memory_candidate_prompt.actions`
        # containing review/skip/later and on the absence of
        # `memory_auto_accepted: true`. Keep this exact.
        "memory_candidate_prompt": _empty_memory_candidate_prompt(),
    }


@router.post("/api/flow-responses/{flow_response_id}/generate-memory-candidate")
async def generate_memory_candidate(
    flow_response_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Skip-reversal entry point.

    After a user skipped the memory prompt on a flow response, this
    endpoint regenerates a candidate so they can review it. The FE
    surfaces a "Generate memory candidate" affordance in the flow
    response detail until accepted / rejected.

    INVARIANT_TESTS.md §"Skip reversible" depends on this endpoint
    existing and on the underlying response carrying
    `available_actions: [..., "generate_memory_candidate"]`.
    """
    # TODO(Phase B.3): drive real candidate production through
    # MembraneService once flow_response rows persist. For B.1 we
    # emit the prompt envelope so the contract shape is honored.
    return {
        "ok": True,
        "flow_response_id": flow_response_id,
        "memory_candidate_prompt": {
            "has_candidate": True,
            # Stable placeholder id so FE can wire end-to-end against
            # the contract before B.3 produces a real candidate row.
            "candidate_id": f"memcand_pending_{flow_response_id}",
            "actions": list(_MEMORY_PROMPT_ACTIONS),
        },
    }
