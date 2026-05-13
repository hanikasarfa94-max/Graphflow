"""Memory Candidate / Membrane endpoints — v0.6.2 contract surface.

Wraps `MembraneService` in the API shape defined by
`graphflow_handoff_v062/API_CONTRACT.md §"Memory Candidate / Membrane"`.

Doctrine (DESIGN_LOCK.md): AI may propose memory. Authority accepts
memory. The Membrane enforces whether acceptance is automatic,
delegated, or review-required. Server computes authority — frontend
renders allowed actions.

Thin-router invariant (CLAUDE.md §"Architectural invariants"):

  pydantic validation
    → membership gate (ProjectMemberRepository.is_member, via
      MembraneService.get_candidate_full_detail return shape)
    → service call
    → service-error → HTTP status

No business logic in this file. All compression-analysis shaping,
authority computation, and lineage assembly lives in
`services/membrane.py`.

Endpoints:
  * GET   /api/memory-candidates/{candidate_id}
  * POST  /api/memory-candidates/{candidate_id}/accept
  * POST  /api/memory-candidates/{candidate_id}/defer
  * POST  /api/memory-candidates/{candidate_id}/reopen
  * POST  /api/memory-candidates/{candidate_id}/reject
  * GET   /api/memory-atoms/{atom_id}/citations
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, MembraneService

router = APIRouter(prefix="/api", tags=["memory-candidates"])


def _get_service(request: Request) -> MembraneService:
    return request.app.state.membrane_service


class _EmptyBody(BaseModel):
    """All four mutation endpoints take no body in the v0.6.2 contract;
    pydantic still validates the JSON envelope is empty / object-shaped.
    """

    model_config = ConfigDict(extra="forbid")


def _raise_for_error(result: dict) -> None:
    """Translate MembraneService dict errors → HTTPException with the
    contract-defined envelope.

    `authority_required` carries the role envelope that the
    Authority-enforcement invariant test expects. Everything else maps
    to a single `error` string. 4xx/5xx selection mirrors the existing
    router conventions in `streams.py` / `membrane.py`.
    """
    err = result.get("error", "request_failed")
    if err == "authority_required":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "authority_required",
                "required_roles": result.get("required_roles", []),
                "user_roles": result.get("user_roles", []),
                "allowed_actions": result.get("allowed_actions", []),
            },
        )
    status_map = {
        "not_found": 404,
        "not_a_member": 403,
        "already_resolved": 409,
        "not_reopenable": 409,
        "invalid_status": 400,
    }
    raise HTTPException(status_code=status_map.get(err, 400), detail=err)


@router.get("/memory-candidates/{candidate_id}")
async def get_memory_candidate(
    candidate_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Return the full v0.6.2 Memory Candidate detail.

    Response shape — every field is contract-required:
      candidate_id, status, verbatim_source, ai_extracted_claim,
      compression_analysis (with `caveat` containing
      'does not guarantee'), compression_warnings,
      proposed_memory_atom, authority_check, affected_objects,
      lifecycle_events.

    Authority is computed server-side against the viewing user; the
    frontend renders `allowed_actions` and never infers.
    """
    service = _get_service(request)
    result = await service.get_candidate_full_detail(
        candidate_id=candidate_id, viewer_user_id=user.id
    )
    if not result.get("ok"):
        _raise_for_error(result)
    # Drop the internal `ok` flag — the contract returns the candidate
    # envelope directly.
    result.pop("ok", None)
    return result


@router.post("/memory-candidates/{candidate_id}/accept")
async def post_accept_memory_candidate(
    candidate_id: str,
    request: Request,
    _body: _EmptyBody | None = None,
    user: AuthenticatedUser = Depends(require_user),
):
    """Accept a memory candidate. Authority-gated server-side.

    On success returns `{memory_atom_id, lineage}` per
    INVARIANT_TESTS.md §"Memory lineage required" — three ids on
    `lineage` are guaranteed defined: verbatim_source_id,
    ai_distillation_id, accepted_by.

    On authority failure returns 403 with the
    `{error, required_roles, user_roles, allowed_actions}` envelope
    per INVARIANT_TESTS.md §"Authority enforcement".
    """
    service = _get_service(request)
    result = await service.accept_candidate(
        candidate_id=candidate_id, accepter_user_id=user.id
    )
    if not result.get("ok"):
        _raise_for_error(result)
    result.pop("ok", None)
    return result


@router.post("/memory-candidates/{candidate_id}/defer")
async def post_defer_memory_candidate(
    candidate_id: str,
    request: Request,
    _body: _EmptyBody | None = None,
    user: AuthenticatedUser = Depends(require_user),
):
    """Move a candidate to `deferred` — the user wants to decide later."""
    service = _get_service(request)
    result = await service.set_candidate_status(
        candidate_id=candidate_id,
        new_status="deferred",
        actor_user_id=user.id,
    )
    if not result.get("ok"):
        _raise_for_error(result)
    result.pop("ok", None)
    return result


@router.post("/memory-candidates/{candidate_id}/reopen")
async def post_reopen_memory_candidate(
    candidate_id: str,
    request: Request,
    _body: _EmptyBody | None = None,
    user: AuthenticatedUser = Depends(require_user),
):
    """Reopen a deferred / rejected candidate so it re-enters review."""
    service = _get_service(request)
    result = await service.set_candidate_status(
        candidate_id=candidate_id,
        new_status="reopened",
        actor_user_id=user.id,
    )
    if not result.get("ok"):
        _raise_for_error(result)
    result.pop("ok", None)
    return result


@router.post("/memory-candidates/{candidate_id}/reject")
async def post_reject_memory_candidate(
    candidate_id: str,
    request: Request,
    _body: _EmptyBody | None = None,
    user: AuthenticatedUser = Depends(require_user),
):
    """Reject a candidate. Surfaces as MemoryCandidateStatus='rejected'."""
    service = _get_service(request)
    result = await service.set_candidate_status(
        candidate_id=candidate_id,
        new_status="rejected",
        actor_user_id=user.id,
    )
    if not result.get("ok"):
        _raise_for_error(result)
    result.pop("ok", None)
    return result


# ---------------------------------------------------------------------------
# Outbound lineage — what cites this memory atom?
# ---------------------------------------------------------------------------


@router.get("/memory-atoms/{atom_id}/citations")
async def get_memory_atom_citations(
    atom_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Return `cited_by` + `downstream_dependencies` for a published atom.

    TODO(Phase B.2): real citation tracking through DecisionRow,
    TaskRow.evidence_refs, and KbItemRow.parent_id. v0 returns empty
    arrays so the FE renders without 500ing.
    """
    service = _get_service(request)
    result = await service.get_memory_atom_citations(
        atom_id=atom_id, viewer_user_id=user.id
    )
    if not result.get("ok"):
        _raise_for_error(result)
    result.pop("ok", None)
    return result
