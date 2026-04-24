"""Composition router — HR/COO diagnostic surface (read-only v0).

One endpoint today:

  GET /api/projects/{project_id}/composition
      Any project member may read. Returns authority-distribution,
      per-class coverage, per-member load + engagement, and pairwise
      shared-authority overlaps. See CompositionService.compose for
      the full payload shape.

Permissions: project-member-only. Non-members get 403. Unknown project
id → 404.

Future (v1, not here): POST /composition/rebalance (drag-rebalance gate
map), GET /composition/simulate-departure/{user_id} (what breaks if X
leaves). Both will require owner-role permission — leaving this router
to gate reads makes that later cut clean.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    CompositionError,
    CompositionService,
)
from workgraph_persistence import (
    ProjectMemberRepository,
    session_scope,
)


router = APIRouter(tags=["composition"])


def _get_service(request: Request) -> CompositionService:
    service = getattr(request.app.state, "composition_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail="composition_unavailable"
        )
    return service


@router.get("/api/projects/{project_id}/composition")
async def get_composition(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    # Membership gate — the diagnostic view exposes member identities,
    # gate-keeper mappings, and engagement counts. Outsiders get 403.
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        if not await ProjectMemberRepository(session).is_member(
            project_id, user.id
        ):
            raise HTTPException(status_code=403, detail="not_a_member")

    service = _get_service(request)
    try:
        payload = await service.compose(project_id=project_id)
    except CompositionError as exc:
        status = exc.status
        raise HTTPException(status_code=status, detail=exc.code) from exc
    return {"ok": True, **payload}
