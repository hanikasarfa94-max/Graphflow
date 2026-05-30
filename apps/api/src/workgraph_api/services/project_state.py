"""ProjectStateService — the composite `/state` read model.

Extracted from the fat `GET /projects/{id}/state` router handler (audit H1)
so the read model has a service-layer home: testable without HTTP, reusable
by other consumers (e.g. the group-aware agent's read path), and the single
place license/observer scoping is applied (audit H6). The router keeps only
the thin membership gate.

Response shape is byte-for-byte the prior handler output — covered by the
/state HTTP tests (test_collab, test_decisions, test_delivery,
test_decision_votes, test_conflicts) and the scope unit tests.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    ClarificationQuestionRepository,
    PlanRepository,
    ProjectGraphRepository,
    ProjectRow,
    RequirementRepository,
    session_scope,
)

from .license_scope import _apply_observer_scope, _apply_task_scope


class ProjectStateService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        *,
        project_service: Any,
        assignment_service: Any,
        conflict_service: Any,
        decision_service: Any,
        delivery_service: Any,
        commitment_service: Any,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._project_service = project_service
        self._assignment_service = assignment_service
        self._conflict_service = conflict_service
        self._decision_service = decision_service
        self._delivery_service = delivery_service
        self._commitment_service = commitment_service

    async def build_state(
        self, project_id: str, viewer_id: str
    ) -> dict[str, Any] | None:
        """Assemble the composite project snapshot, license-scoped to the
        viewer's tier. Returns None if the project does not exist (the router
        maps that to 404). Membership is gated by the caller.
        """
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return None

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

        assignments = await self._assignment_service.list_for_project(project_id)

        members = await self._project_service.members(project_id)

        conflicts_payload = await self._conflict_service.list_for_project(project_id)

        decisions = await self._decision_service.list_for_project(project_id, limit=50)

        delivery = await self._delivery_service.latest_for_project(project_id)

        commitments = await self._commitment_service.list_for_project(
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
            if m.get("user_id") == viewer_id:
                viewer_tier = str(m.get("license_tier") or "full")
                break

        if viewer_tier == "task_scoped":
            graph, plan, assignments, commitments = _apply_task_scope(
                viewer_user_id=viewer_id,
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
                viewer_user_id=viewer_id,
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
