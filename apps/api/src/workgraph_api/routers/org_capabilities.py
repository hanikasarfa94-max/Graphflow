"""Org Graph capability projection — read-only HTTP surface (O2).

  GET /api/projects/{project_id}/capabilities
      Project members only. Returns
      `{ok, capabilities: [{user_id, display_name, capabilities: [...]}, ...]}`.

The Org Graph is internal but transparent: a member can see what
skills the system thinks the team has and what evidence backs each
level. No mutation; the service is read-only by design.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser

router = APIRouter(tags=["org-capabilities"])


@router.get("/api/projects/{project_id}/capabilities")
async def get_project_capabilities(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    from workgraph_persistence import (
        ProjectMemberRepository,
        session_scope,
    )

    async with session_scope(request.app.state.sessionmaker) as session:
        if not await ProjectMemberRepository(session).is_member(
            project_id, user.id
        ):
            raise HTTPException(
                status_code=403, detail="not_a_project_member"
            )

    service = request.app.state.org_capability_service
    capabilities = await service.list_for_project(project_id)
    return {"ok": True, "capabilities": capabilities}
