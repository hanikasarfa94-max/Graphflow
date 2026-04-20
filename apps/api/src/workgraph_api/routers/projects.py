"""Project list + membership endpoints (Phase 7').

`GET /api/projects` lists projects the current user is a member of.
`POST /api/projects/{id}/invite` invites by username.
`GET /api/projects/{id}/members` lists members.
`GET /api/projects/{id}/state` returns the composite graph+plan snapshot
    for the project detail page (one fetch, no N+1 round-trips).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from workgraph_persistence import (
    ClarificationQuestionRepository,
    PlanRepository,
    ProjectGraphRepository,
    ProjectRow,
    RequirementRepository,
    session_scope,
)

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, ProjectService

router = APIRouter(prefix="/api/projects", tags=["projects"])


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=32)


@router.get("")
async def list_projects(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> list[dict[str, Any]]:
    service: ProjectService = request.app.state.project_service
    return await service.list_for_user(user.id)


@router.post("/{project_id}/invite")
async def invite_member(
    project_id: str,
    body: InviteRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service: ProjectService = request.app.state.project_service
    is_member = await service.is_member(project_id=project_id, user_id=user.id)
    if not is_member:
        raise HTTPException(status_code=403, detail="not a project member")
    result = await service.add_member(
        project_id=project_id, username=body.username, invited_by=user.id
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "invite_failed"))
    return result


@router.get("/{project_id}/members")
async def list_members(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> list[dict[str, Any]]:
    service: ProjectService = request.app.state.project_service
    is_member = await service.is_member(project_id=project_id, user_id=user.id)
    if not is_member:
        raise HTTPException(status_code=403, detail="not a project member")
    return await service.members(project_id)


@router.get("/{project_id}/state")
async def get_project_state(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service: ProjectService = request.app.state.project_service
    is_member = await service.is_member(project_id=project_id, user_id=user.id)
    if not is_member:
        raise HTTPException(status_code=403, detail="not a project member")

    sessionmaker = request.app.state.sessionmaker
    async with session_scope(sessionmaker) as session:
        project = (
            await session.execute(
                select(ProjectRow).where(ProjectRow.id == project_id)
            )
        ).scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")

        req = await RequirementRepository(session).latest_for_project(project_id)
        graph = {"goals": [], "deliverables": [], "constraints": [], "risks": []}
        plan = {"tasks": [], "dependencies": [], "milestones": []}
        clarifications: list[dict] = []
        parsed = {}
        requirement_version = 0
        parse_outcome = None
        if req is not None:
            requirement_version = req.version
            parsed = req.parsed_json or {}
            parse_outcome = req.parse_outcome
            graph_raw = await ProjectGraphRepository(session).list_all(req.id)
            graph = {
                "goals": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "description": r.description,
                        "success_criteria": r.success_criteria,
                        "status": r.status,
                    }
                    for r in graph_raw["goals"]
                ],
                "deliverables": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "kind": r.kind,
                        "status": r.status,
                    }
                    for r in graph_raw["deliverables"]
                ],
                "constraints": [
                    {
                        "id": r.id,
                        "kind": r.kind,
                        "content": r.content,
                        "severity": r.severity,
                        "status": r.status,
                    }
                    for r in graph_raw["constraints"]
                ],
                "risks": [
                    {
                        "id": r.id,
                        "title": r.title,
                        "content": r.content,
                        "severity": r.severity,
                        "status": r.status,
                    }
                    for r in graph_raw["risks"]
                ],
            }
            plan_rows = await PlanRepository(session).list_all(req.id)
            plan = {
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
                    }
                    for t in plan_rows["tasks"]
                ],
                "dependencies": [
                    {
                        "id": d.id,
                        "from_task_id": d.from_task_id,
                        "to_task_id": d.to_task_id,
                    }
                    for d in plan_rows["dependencies"]
                ],
                "milestones": [
                    {
                        "id": m.id,
                        "title": m.title,
                        "target_date": m.target_date,
                        "related_task_ids": m.related_task_ids or [],
                        "status": m.status,
                    }
                    for m in plan_rows["milestones"]
                ],
            }
            clar_rows = await ClarificationQuestionRepository(
                session
            ).list_for_requirement(req.id)
            clarifications = [
                {
                    "id": c.id,
                    "position": c.position,
                    "question": c.question,
                    "answer": c.answer,
                }
                for c in clar_rows
            ]

    assignment_service = request.app.state.assignment_service
    assignments = await assignment_service.list_for_project(project_id)

    members = await service.members(project_id)

    conflict_service = request.app.state.conflict_service
    conflicts_payload = await conflict_service.list_for_project(project_id)

    decision_service = request.app.state.decision_service
    decisions = await decision_service.list_for_project(project_id, limit=50)

    delivery_service = request.app.state.delivery_service
    delivery = await delivery_service.latest_for_project(project_id)

    commitment_service = request.app.state.commitment_service
    commitments = await commitment_service.list_for_project(
        project_id=project_id, limit=100
    )

    return {
        "project": {"id": project.id, "title": project.title},
        "requirement_version": requirement_version,
        "parsed": parsed,
        "parse_outcome": parse_outcome,
        "graph": graph,
        "plan": plan,
        "clarifications": clarifications,
        "assignments": assignments,
        "members": members,
        "conflicts": conflicts_payload["conflicts"],
        "conflict_summary": conflicts_payload["summary"],
        "decisions": decisions,
        "delivery": delivery,
        "commitments": commitments,
    }
