from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from workgraph_persistence import (
    PlanRepository,
    ProjectGraphRepository,
    ProjectRow,
    RequirementRepository,
    session_scope,
)
from sqlalchemy import select

from workgraph_api.deps import get_planning_service
from workgraph_api.services import (
    ConflictService,
    NotReadyForPlanning,
    PlanningService,
    ProjectNotFound,
)

router = APIRouter(prefix="/api/projects", tags=["planning"])


@router.post("/{project_id}/plan")
async def post_plan(
    project_id: str,
    request: Request,
    service: PlanningService = Depends(get_planning_service),
) -> dict[str, Any]:
    try:
        result = await service.plan(project_id)
    except ProjectNotFound:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    except NotReadyForPlanning as e:
        raise HTTPException(status_code=409, detail=e.reason)

    # Fire-and-forget conflict recheck now that tasks + deps exist. The UI
    # gets a WS `conflicts` frame when detection + explanation finish.
    from workgraph_observability import get_trace_id

    conflict_service: ConflictService = request.app.state.conflict_service
    conflict_service.kick_recheck(project_id, trace_id=get_trace_id())
    return result


@router.get("/{project_id}/plan")
async def get_plan(project_id: str, request: Request) -> dict[str, Any]:
    """Return the persisted plan bound to the latest requirement version.

    Empty arrays when no plan exists yet — callers use the /stage endpoint
    to learn whether planning has run.
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
                "tasks": [],
                "dependencies": [],
                "milestones": [],
                "risks": [],
            }

        plan_rows = await PlanRepository(session).list_all(latest_req.id)
        risks = await ProjectGraphRepository(session).list_risks(latest_req.id)

    return {
        "project_id": project_id,
        "requirement_id": latest_req.id,
        "requirement_version": latest_req.version,
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "deliverable_id": t.deliverable_id,
                "assignee_role": t.assignee_role,
                "estimate_hours": t.estimate_hours,
                "acceptance_criteria": t.acceptance_criteria,
                "status": t.status,
                "sort_order": t.sort_order,
            }
            for t in plan_rows["tasks"]
        ],
        "dependencies": [
            {"id": d.id, "from_task_id": d.from_task_id, "to_task_id": d.to_task_id}
            for d in plan_rows["dependencies"]
        ],
        "milestones": [
            {
                "id": m.id,
                "title": m.title,
                "target_date": m.target_date,
                "related_task_ids": m.related_task_ids or [],
                "status": m.status,
                "sort_order": m.sort_order,
            }
            for m in plan_rows["milestones"]
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
            for r in risks
        ],
    }
