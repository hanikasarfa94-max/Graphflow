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
    ProjectMemberRepository,
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


class RequirementBudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # None clears the budget. ge=1 because zero would silently disable
    # the membrane's overflow check while pretending it was set.
    budget_hours: int | None = Field(default=None, ge=1, le=100000)


class MemberSkillsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Free-form strings; we lowercase + dedup at write time. The
    # vocabulary draws from TaskRow.assignee_role values
    # (pm/frontend/backend/qa/design/business/approver) but we don't
    # enforce — projects can introduce niche tags as needed.
    skill_tags: list[str] = Field(default_factory=list, max_length=32)


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


@router.patch("/{project_id}/members/{user_id}/skills")
async def patch_member_skills(
    project_id: str,
    user_id: str,
    body: MemberSkillsUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Self-edit OR owner-edit a project member's functional skill tags.

    Used by the membrane's task_promote review for assignee-coverage
    advisories: a task tagged role='backend' with no project member
    declaring 'backend' surfaces a warning.

    Vocabulary tracks TaskRow.assignee_role
    (pm/frontend/backend/qa/design/business/approver/unknown) but we
    accept any string so projects can introduce niche tags.
    """
    service: ProjectService = request.app.state.project_service
    members = await service.members(project_id)
    me = next((m for m in members if m["user_id"] == user.id), None)
    if me is None:
        raise HTTPException(status_code=403, detail="not a project member")
    if user.id != user_id and me.get("role") != "owner":
        # Self-edit is always allowed; cross-edit is owner-only.
        raise HTTPException(status_code=403, detail="owner_or_self_only")

    target = next((m for m in members if m["user_id"] == user_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="member_not_found")

    # Normalize: lowercase, strip, dedup, drop empties. Cap each tag
    # length so we don't store essays.
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in body.skill_tags:
        tag = (raw or "").strip().lower()[:32]
        if not tag or tag in seen:
            continue
        seen.add(tag)
        cleaned.append(tag)

    async with session_scope(request.app.state.sessionmaker) as session:
        updated = await ProjectMemberRepository(session).set_skill_tags(
            project_id=project_id, user_id=user_id, skill_tags=cleaned
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="member_not_found")
        return {
            "ok": True,
            "user_id": user_id,
            "skill_tags": list(updated.skill_tags or []),
        }


@router.patch("/{project_id}/requirements/{requirement_id}/budget")
async def patch_requirement_budget(
    project_id: str,
    requirement_id: str,
    body: RequirementBudgetUpdate,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Owner-only — set/clear the requirement's declared budget in hours.

    Used by the membrane's task_promote review for the
    estimate-overflow advisory check. LLM intake never writes this
    field; it lives behind a manual UI control so capacity is an
    explicit owner decision, not an LLM guess.
    """
    service: ProjectService = request.app.state.project_service
    members = await service.members(project_id)
    me = next((m for m in members if m["user_id"] == user.id), None)
    if me is None:
        raise HTTPException(status_code=403, detail="not a project member")
    if me.get("role") != "owner":
        raise HTTPException(status_code=403, detail="owner_only")

    async with session_scope(request.app.state.sessionmaker) as session:
        req = await RequirementRepository(session).get(requirement_id)
        if req is None or req.project_id != project_id:
            raise HTTPException(status_code=404, detail="requirement_not_found")
        req.budget_hours = body.budget_hours
        await session.flush()
        return {
            "ok": True,
            "requirement_id": req.id,
            "budget_hours": req.budget_hours,
        }


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
        requirement_id: str | None = None
        budget_hours: int | None = None
        parse_outcome = None
        if req is not None:
            requirement_version = req.version
            requirement_id = req.id
            budget_hours = req.budget_hours
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

    # License-scoped view. `full` sees everything; `task_scoped`
    # narrows to the viewer's assigned subgraph; `observer` is the
    # external-auditor tier — a subgraph slice restricted to the
    # nodes the viewer has an explicit link to (assigned tasks,
    # decisions they resolved). Write-side enforcement for observer
    # lives in collab.py (`observer_cannot_post`).
    viewer_tier = "full"
    for m in members:
        if m.get("user_id") == user.id:
            viewer_tier = str(m.get("license_tier") or "full")
            break

    if viewer_tier == "task_scoped":
        graph, plan, assignments, commitments = _apply_task_scope(
            viewer_user_id=user.id,
            graph=graph,
            plan=plan,
            assignments=assignments,
            commitments=commitments,
        )
    elif viewer_tier == "observer":
        (
            graph,
            plan,
            assignments,
            commitments,
            decisions,
            members,
        ) = _apply_observer_scope(
            viewer_user_id=user.id,
            graph=graph,
            plan=plan,
            assignments=assignments,
            commitments=commitments,
            decisions=decisions,
            members=members,
        )

    return {
        "project": {"id": project.id, "title": project.title},
        "requirement_version": requirement_version,
        "requirement_id": requirement_id,
        "budget_hours": budget_hours,
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
        "viewer_license_tier": viewer_tier,
    }


def _apply_task_scope(
    *,
    viewer_user_id: str,
    graph: dict[str, Any],
    plan: dict[str, Any],
    assignments: list[dict[str, Any]],
    commitments: list[dict[str, Any]],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Filter the /state payload to the subgraph a task_scoped member
    is allowed to see. Keeps goals/risks/constraints (environmental
    context that every contributor benefits from) and decisions
    (audit), drops tasks + deliverables + dependencies + commitments
    that don't anchor to the viewer's assigned work.

    Rules:
      * Tasks: only those assigned to the viewer (AssignmentRow.active).
      * Deliverables: only those referenced by visible tasks, plus any
        that the viewer's own assigned tasks belong to.
      * Dependencies: only edges where both endpoints are visible.
      * Milestones: keep all (top-level dates are non-sensitive).
      * Assignments: only the viewer's own.
      * Commitments: only those with no scope_ref OR scope_ref anchors
        at a visible entity (task/deliverable/goal).

    v1 leaves decisions/conflicts untouched — they're audit rows
    that a task_scoped contractor still needs to see to understand
    why the plan looks the way it does. v2 may tighten this.
    """
    visible_task_ids = {
        a["task_id"]
        for a in assignments
        if a.get("user_id") == viewer_user_id
        and bool(a.get("active", True))
    }
    visible_tasks = [
        t for t in plan.get("tasks", []) if t["id"] in visible_task_ids
    ]
    visible_deliverable_ids = {
        t["deliverable_id"]
        for t in visible_tasks
        if t.get("deliverable_id")
    }
    visible_goal_ids = {g["id"] for g in graph.get("goals", [])}
    visible_dependencies = [
        d
        for d in plan.get("dependencies", [])
        if d["from_task_id"] in visible_task_ids
        and d["to_task_id"] in visible_task_ids
    ]
    visible_deliverables = [
        d
        for d in graph.get("deliverables", [])
        if d["id"] in visible_deliverable_ids
    ]
    # Viewer's own assignments only.
    visible_assignments = [
        a for a in assignments if a.get("user_id") == viewer_user_id
    ]
    # Commitments: unscoped + anchored-to-visible.
    anchored_visible_ids = (
        visible_task_ids | visible_deliverable_ids | visible_goal_ids
    )
    visible_commitments = [
        c
        for c in commitments
        if c.get("scope_ref_id") is None
        or c.get("scope_ref_id") in anchored_visible_ids
    ]

    filtered_graph = {
        **graph,
        "deliverables": visible_deliverables,
    }
    filtered_plan = {
        **plan,
        "tasks": visible_tasks,
        "dependencies": visible_dependencies,
    }
    return (
        filtered_graph,
        filtered_plan,
        visible_assignments,
        visible_commitments,
    )


def _apply_observer_scope(
    *,
    viewer_user_id: str,
    graph: dict[str, Any],
    plan: dict[str, Any],
    assignments: list[dict[str, Any]],
    commitments: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    members: list[dict[str, Any]],
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Subgraph slice for external-auditor (observer) tier.

    Observers see ONLY nodes they have an explicit link to. Unlike
    task_scoped (which keeps environmental goals/risks as context),
    observer hides everything unlinked so an auditor engaged for one
    deliverable cannot enumerate the wider plan.

    Rules:
      * Tasks: only those with an active assignment to the viewer.
      * Dependencies: only edges where both endpoints are visible.
      * Deliverables / goals / constraints / risks / milestones:
        empty — the ORM has no viewer-link field on these (RiskRow
        has no owner_user_id, goals/deliverables have no assignee),
        so an observer sees none of them by default.
      * Decisions: only those where `resolver_id == viewer`. The
        ORM stores resolver as the single human participation field
        on DecisionRow; there is no separate "participant" join.
      * Assignments: viewer's own only.
      * Commitments: empty — no direct-link field.
      * Members: full list preserved so the auditor can see the
        org context, with the viewer's own row flagged.
    """
    visible_task_ids = {
        a["task_id"]
        for a in assignments
        if a.get("user_id") == viewer_user_id
        and bool(a.get("active", True))
    }
    visible_tasks = [
        t for t in plan.get("tasks", []) if t["id"] in visible_task_ids
    ]
    visible_dependencies = [
        d
        for d in plan.get("dependencies", [])
        if d["from_task_id"] in visible_task_ids
        and d["to_task_id"] in visible_task_ids
    ]
    visible_assignments = [
        a for a in assignments if a.get("user_id") == viewer_user_id
    ]
    visible_decisions = [
        d for d in decisions if d.get("resolver_id") == viewer_user_id
    ]
    annotated_members = [
        {**m, "is_viewer": m.get("user_id") == viewer_user_id}
        for m in members
    ]

    filtered_graph = {
        **graph,
        "goals": [],
        "deliverables": [],
        "constraints": [],
        "risks": [],
    }
    filtered_plan = {
        **plan,
        "tasks": visible_tasks,
        "dependencies": visible_dependencies,
        "milestones": [],
    }
    return (
        filtered_graph,
        filtered_plan,
        visible_assignments,
        [],
        visible_decisions,
        annotated_members,
    )
