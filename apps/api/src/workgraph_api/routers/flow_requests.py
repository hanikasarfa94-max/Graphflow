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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, ProjectService

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
    "validation_error": 422,
    "draft_send_failed": 502,
}


def _raise_service_error(code: str, detail: str | None = None) -> None:
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

    # The flow-level decision. Memory prompt actions are independent
    # (see _MEMORY_PROMPT_ACTIONS).
    action: Literal["accept", "decline", "revise", "needs_more_info"]
    note: str | None = Field(default=None, max_length=4000)
    framing: str | None = Field(default=None, max_length=4000)


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

    Invariant: response NEVER auto-opens or auto-accepts memory. The
    envelope carries `memory_candidate_prompt` with the locked
    `["review", "skip", "later"]` action set. Memory acceptance is a
    second, independent transition the user takes from the prompt.
    """
    # TODO(Phase B.3): wire to FlowActionService.respond and to
    # MembraneService for real candidate production (response body +
    # framing → memory_candidate). Until then we emit the contract
    # shape so the invariant tests on prompt actions and the absence
    # of `memory_auto_accepted` already pass.
    return {
        "ok": True,
        "flow_response_id": f"flowresp_{flow_request_id}",
        "flow_request_id": flow_request_id,
        "action": body.action,
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
