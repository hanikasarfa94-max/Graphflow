"""Phase B.1 — v0.6.2 Right Rail surface (API_CONTRACT §"Right Rail").

Refresh-only endpoint that returns the five RightRailSpine slots for
any primary surface object. Primary object responses
(`/api/tasks/{id}`, `/api/conversations/{id}`, etc.) include an initial
`right_rail` field; this endpoint exists so the FE can re-fetch it
without re-fetching the primary object.

RightRailSpine (schemas.graphflow.json) — fixed order, every surface:
  1. context           — what is this object? who owns it? what's its state?
  2. related_work      — neighbouring objects (signal-chain neighbours)
  3. evidence_sources  — verbatim sources backing the object's claims
  4. ai_assistance     — actions that return proposals (mutates_state=false)
  5. primary_action    — the one button the authority can press

Endpoint:
  * GET /api/right-rail?surface=<surface>&object_id=<id>

Supported surfaces (matches the v0.6.2 surface taxonomy):
  - task
  - conversation
  - document
  - memory_candidate
  - flow_request

Thin-router invariant: the router validates query params, gates on
the object's scope membership where applicable, and dispatches to a
per-surface stub. Phase B.2-D wires each stub to real data sources.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser

router = APIRouter(prefix="/api", tags=["right-rail"])


# ---- enums ----------------------------------------------------------------

SurfaceT = Literal[
    "task",
    "conversation",
    "document",
    "memory_candidate",
    "flow_request",
]

_VALID_SURFACES: set[str] = {
    "task",
    "conversation",
    "document",
    "memory_candidate",
    "flow_request",
}


# ---- response shape (matches RightRailSpine in schemas.graphflow.json) ----


class RightRailSlot(BaseModel):
    """One slot in the right rail. `items` is surface-shaped — the FE
    branches on `kind` to render. Empty items + `loading=false` means
    "no content for this slot on this object."
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    title: str | None = None
    items: list[dict[str, Any]] = []
    loading: bool = False


class RightRailResponse(BaseModel):
    """The five-slot spine. Order is load-bearing — the FE renders in
    array order, never re-sorts. Missing data = empty `items`, never a
    missing key."""

    model_config = ConfigDict(extra="forbid")

    surface: str
    object_id: str
    context: RightRailSlot
    related_work: RightRailSlot
    evidence_sources: RightRailSlot
    ai_assistance: RightRailSlot
    primary_action: RightRailSlot


# ---- helpers --------------------------------------------------------------


def _empty_spine(surface: str, object_id: str) -> RightRailResponse:
    """Default five-slot spine. Used as the B.1 stub for every surface
    until the per-surface wiring lands.

    TODO(Phase B.2-D): each surface's stub gets replaced with a real
    data fetch (see the per-surface comments below).
    """
    return RightRailResponse(
        surface=surface,
        object_id=object_id,
        context=RightRailSlot(kind="context", title=None, items=[]),
        related_work=RightRailSlot(kind="related_work", title=None, items=[]),
        evidence_sources=RightRailSlot(
            kind="evidence_sources", title=None, items=[]
        ),
        ai_assistance=RightRailSlot(
            kind="ai_assistance", title=None, items=[]
        ),
        primary_action=RightRailSlot(
            kind="primary_action", title=None, items=[]
        ),
    )


# ---- endpoint -------------------------------------------------------------


@router.get("/right-rail", response_model=RightRailResponse)
async def get_right_rail(
    request: Request,
    surface: str = Query(min_length=1, max_length=32),
    object_id: str = Query(min_length=1, max_length=64),
    user: AuthenticatedUser = Depends(require_user),
) -> RightRailResponse:
    """Refresh-only right rail for any primary surface.

    Returns all five RightRailSpine slots in a fixed order. Each slot
    is a contract-shaped envelope; B.1 returns empty items so the FE
    renders the skeleton.

    Per-surface TODOs (Phase B.2-D):
      - task: pull from TaskProgressService (status timeline + assignee
        + scoring as context; signal-chain neighbours as related_work;
        evidence_refs as evidence_sources; "promote" / "score" /
        "transition" as ai_assistance + primary_action).
      - conversation: StreamService.surrounding_context — recent
        messages, pinned decisions, open IMSuggestions, "compose" /
        "summarize" as ai_assistance.
      - document: KbItemService.read_with_neighbours — author + status
        as context, citing decisions as related_work, attachments as
        evidence_sources, "publish" / "propose memory" as actions.
      - memory_candidate: MembraneService.get_candidate_full_detail —
        verbatim_source as context + evidence_sources, compression
        analysis as ai_assistance, authority-gated "accept" as primary.
      - flow_request: FlowProjectionService — sender / receiver as
        context, source-of-truth attachments as evidence_sources,
        "accept" / "respond" as actions.
    """
    if surface not in _VALID_SURFACES:
        raise HTTPException(
            status_code=400,
            detail=(
                "invalid_surface (allowed: "
                f"{sorted(_VALID_SURFACES)})"
            ),
        )

    # Per-surface dispatch. B.1 returns the empty spine for every
    # surface; B.2-D replaces each branch with a real data fetch.
    if surface == "task":
        # TODO(Phase D.2): wire TaskProgressService.history + signal
        # chain neighbours + assignment.
        return _empty_spine(surface, object_id)

    if surface == "conversation":
        # TODO(Phase D.1): wire StreamService.surrounding_context.
        return _empty_spine(surface, object_id)

    if surface == "document":
        # TODO(Phase D.3): wire KbItemService.read_with_neighbours.
        return _empty_spine(surface, object_id)

    if surface == "memory_candidate":
        # TODO(Phase C.2): wire MembraneService.get_candidate_full_detail.
        # When this lands, the response carries the full lineage
        # timeline + compression analysis caveat in evidence_sources.
        return _empty_spine(surface, object_id)

    if surface == "flow_request":
        # TODO(Phase C.1): wire FlowProjectionService.for_request.
        return _empty_spine(surface, object_id)

    # Unreachable — validated above.
    raise HTTPException(status_code=400, detail="invalid_surface")
