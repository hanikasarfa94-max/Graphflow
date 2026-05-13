"""Phase B.1 — v0.6.2 AI Assistance dispatcher (API_CONTRACT §"AI Assistance").

The hardest invariant of the pivot: AI proposes, human commits. Every
call to this endpoint returns:

    {"proposal": {...}, "mutates_state": false}

INVARIANT_TESTS.md §"AI Assistance no-mutation" asserts on both fields.
This router must NEVER touch the accept / crystallize / publish paths;
it dispatches by ProposalType `kind` to read-only proposal producers
inside existing services, and wraps the result in the locked envelope.

Endpoint:

  * POST /api/ai-assistance/run

Phase B.1 wires the contract shape with stub proposals per kind. Phase
B.2 wires the real producer methods:

  * routing_suggestion         → RoutingService (read-only suggestion path)
  * task_candidate             → TaskProgressService (candidate, not promote)
  * document_draft             → RenderService / KbItemService draft
  * topic_suggestion           → IMService topic-proposal path
  * memory_candidate           → MembraneService.propose (NOT review)
  * impact_analysis            → DriftService / GraphBuilderService read
  * capability_explanation     → OrgCapabilityService read
  * topic_closure              → ClarificationService closure proposal

None of these dispatchers may call `accept`, `crystallize`, `promote`,
or `publish` — those are mutation paths owned by their own dedicated
routers under the authority-gated mutation surface.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, ProjectService

router = APIRouter(tags=["ai-assistance"])


# ---- enums (mirror schemas.graphflow.json ProposalType) ------------------

ProposalKind = Literal[
    "routing_suggestion",
    "task_candidate",
    "document_draft",
    "topic_suggestion",
    "memory_candidate",
    "impact_analysis",
    "capability_explanation",
    "topic_closure",
]


# ---- error envelope ------------------------------------------------------

_STATUS_MAP: dict[str, int] = {
    "scope_required": 422,
    "not_a_scope_member": 403,
    "unsupported_kind": 400,
    "producer_error": 502,
}


# ---- request / response shapes -------------------------------------------


class AIAssistanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ProposalKind
    # `scope_id` is the v0.6.2 alias for project_id. Optional because
    # some kinds (e.g. global capability_explanation) don't need a
    # scope; dispatchers that DO require it raise scope_required.
    scope_id: str | None = Field(default=None, max_length=64)
    # Kind-specific input. The dispatcher per `kind` validates the
    # internal shape; keeping it open here so the envelope stays
    # stable as producers evolve.
    context: dict[str, Any] = Field(default_factory=dict)


# ---- helpers -------------------------------------------------------------


def _get_project_service(request: Request) -> ProjectService:
    return request.app.state.project_service


async def _gate_scope_membership_if_present(
    request: Request, *, scope_id: str | None, user_id: str
) -> None:
    """If a scope is given, the caller must be a member. We gate even
    on read-only proposal producers because the underlying context
    (KB items, decisions, drafts) is scope-tier-gated and the
    producers internally re-check, but failing early gives a cleaner
    403 than a downstream license-context filter.
    """
    if scope_id is None:
        return
    project_service = _get_project_service(request)
    if not await project_service.is_member(
        project_id=scope_id, user_id=user_id
    ):
        raise HTTPException(
            status_code=_STATUS_MAP["not_a_scope_member"],
            detail="not_a_scope_member",
        )


def _stub_proposal(
    *,
    kind: ProposalKind,
    scope_id: str | None,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Phase B.1 stub envelope. Phase B.2 replaces each branch with
    real read-only producer calls into the right service.

    The envelope shape (`id`, `kind`, `scope_id`, `summary`, `body`,
    `evidence`, `allowed_actions`) is locked here so the FE can wire
    Proposal rendering against the contract before producers land.
    """
    # `allowed_actions` is the AllowedAction subset the AI thinks the
    # caller can take. Server-side authority gating happens at the
    # corresponding mutation endpoint (POST /api/proposals/:id/accept
    # etc.), which is the load-bearing check — this list is hint-only.
    return {
        # Stable per-kind placeholder id so the FE can wire end-to-end
        # before real proposal rows persist.
        "id": f"proposal_pending_{kind}",
        "kind": kind,
        "scope_id": scope_id,
        "summary": f"[stub] {kind} proposal — Phase B.2 wires the real producer",
        "body": None,
        "evidence": [],
        "allowed_actions": ["accept", "revise", "reject", "defer"],
        # Echo the input so the FE can show debugging context against
        # the stub envelope.
        "context_echo": dict(context),
    }


# ---- endpoint ------------------------------------------------------------


@router.post("/api/ai-assistance/run")
async def run_ai_assistance(
    body: AIAssistanceRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Dispatch to a read-only proposal producer by `kind`.

    Returns the locked envelope `{"proposal": ..., "mutates_state": false}`.
    INVARIANT_TESTS.md §"AI Assistance no-mutation" asserts on both
    fields. This endpoint must NEVER mutate state — every branch in
    the dispatcher below routes only to read methods on services.
    """
    await _gate_scope_membership_if_present(
        request, scope_id=body.scope_id, user_id=user.id
    )

    # TODO(Phase B.2): replace this stub dispatcher with real producer
    # calls. Per kind:
    #   * routing_suggestion → request.app.state.routing_service.suggest(...)
    #   * task_candidate     → request.app.state.task_progress_service.suggest_candidate(...)
    #   * document_draft     → request.app.state.render_service.draft(...)
    #   * topic_suggestion   → request.app.state.im_service.suggest_topic(...)
    #   * memory_candidate   → request.app.state.membrane_service.propose(...)
    #   * impact_analysis    → request.app.state.drift_service.analyze(...)
    #   * capability_explanation → request.app.state.org_capability_service.explain(...)
    #   * topic_closure      → request.app.state.clarification_service.propose_closure(...)
    # NONE of these may call accept / crystallize / promote / publish.
    proposal = _stub_proposal(
        kind=body.kind,
        scope_id=body.scope_id,
        context=body.context,
    )

    # Locked envelope. The literal `False` is load-bearing — the
    # INVARIANT_TESTS contract test reads `res.mutates_state` and
    # rejects any truthy value.
    return {
        "proposal": proposal,
        "mutates_state": False,
    }
