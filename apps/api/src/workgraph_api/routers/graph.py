from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from workgraph_persistence import (
    ProjectGraphRepository,
    ProjectRow,
    RequirementRepository,
    session_scope,
)
from sqlalchemy import select

router = APIRouter(prefix="/api/projects", tags=["graph"])


@router.get("/{project_id}/graph")
async def get_graph(project_id: str, request: Request) -> dict[str, Any]:
    """Return the graph entities bound to the latest requirement version.

    Phase 5 output shape — downstream phases (planning, QA) will extend it
    with enriched fields on existing kinds rather than adding new top-level
    collections.
    """
    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        project = (
            await session.execute(select(ProjectRow).where(ProjectRow.id == project_id))
        ).scalar_one_or_none()
        if project is None:
            raise HTTPException(
                status_code=404, detail=f"project not found: {project_id}"
            )

        latest_req = await RequirementRepository(session).latest_for_project(project_id)
        if latest_req is None:
            return {
                "project_id": project_id,
                "requirement_id": None,
                "requirement_version": 0,
                "goals": [],
                "deliverables": [],
                "constraints": [],
                "risks": [],
            }

        rows = await ProjectGraphRepository(session).list_all(latest_req.id)

    return {
        "project_id": project_id,
        "requirement_id": latest_req.id,
        "requirement_version": latest_req.version,
        "goals": [
            {
                "id": g.id,
                "title": g.title,
                "description": g.description,
                "success_criteria": g.success_criteria,
                "status": g.status,
                "sort_order": g.sort_order,
            }
            for g in rows["goals"]
        ],
        "deliverables": [
            {
                "id": d.id,
                "title": d.title,
                "kind": d.kind,
                "status": d.status,
                "sort_order": d.sort_order,
            }
            for d in rows["deliverables"]
        ],
        "constraints": [
            {
                "id": c.id,
                "kind": c.kind,
                "content": c.content,
                "severity": c.severity,
                "status": c.status,
                "sort_order": c.sort_order,
            }
            for c in rows["constraints"]
        ],
        "risks": [
            {
                "id": r.id,
                "title": r.title,
                "content": r.content,
                "severity": r.severity,
                "status": r.status,
                "sort_order": r.sort_order,
            }
            for r in rows["risks"]
        ],
    }
