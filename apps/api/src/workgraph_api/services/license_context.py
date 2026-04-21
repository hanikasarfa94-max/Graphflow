"""LicenseContextService — Phase 1.A scoped-context builder.

North-star §"Scoped license model": every cross-user context payload the
sub-agents consume must be filtered by the tightest applicable license
tier. `full` members see everything; `task_scoped` members see only the
subgraph anchored to their assigned work; `observer` members see only
nodes with an explicit link (assigned tasks, decisions they resolved).

This service is the single choke point. Two producers call `build_slice`:
  * prompt-assembly sites (services/collab.py, services/routing.py,
    services/pre_answer.py) — generate agent context
  * outbound lint (services/routing.py reply path) — verify cited node IDs
    fall inside the recipient's view

Slice shape mirrors `GET /api/projects/{id}/state`. Logic for the two
tier filters (`task_scoped`, `observer`) is reused from the local router
helpers by importing them — the slice builder simply composes them with
the DB read. If the viewer/audience pair resolves to `full`, the slice
is unfiltered.

When `audience_user_id` is given and differs from `viewer_user_id`, the
tighter of the two tiers wins. Rationale: the message is routed to the
audience, so their license is the ceiling regardless of who drafted it.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    AssignmentRepository,
    CommitmentRepository,
    DecisionRepository,
    PlanRepository,
    ProjectGraphRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRepository,
    session_scope,
)


# Tightness ordering — the bigger number wins when comparing two tiers.
_TIER_TIGHTNESS = {"full": 0, "task_scoped": 1, "observer": 2}


def tighter_tier(a: str, b: str) -> str:
    """Return whichever tier is more restrictive. Falls back to `full`
    for unknown inputs (fail-open is wrong here, but we don't have a
    sane alternative when the DB returns a bogus tier — the filter
    still runs and gates what the 'full' path serves)."""
    ra = _TIER_TIGHTNESS.get(a, 0)
    rb = _TIER_TIGHTNESS.get(b, 0)
    return a if ra >= rb else b


class LicenseContextService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def _member_tier(
        self, *, project_id: str, user_id: str
    ) -> str | None:
        """Return the user's license_tier for this project, or None if
        they are not a project member."""
        async with session_scope(self._sessionmaker) as session:
            rows = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            for r in rows:
                if r.user_id == user_id:
                    return str(r.license_tier or "full")
        return None

    async def resolve_effective_tier(
        self,
        *,
        project_id: str,
        viewer_user_id: str,
        audience_user_id: str | None,
    ) -> str:
        """Pick the tighter of (viewer, audience). Non-member audience
        resolves to `observer` — an outside recipient cannot be given
        anything a full-tier member would see.
        """
        viewer = await self._member_tier(
            project_id=project_id, user_id=viewer_user_id
        )
        if viewer is None:
            # Fall through as observer — caller shouldn't be serving
            # scoped context to a non-member viewer in the first place.
            viewer = "observer"
        if audience_user_id is None or audience_user_id == viewer_user_id:
            return viewer
        audience = await self._member_tier(
            project_id=project_id, user_id=audience_user_id
        )
        if audience is None:
            audience = "observer"
        return tighter_tier(viewer, audience)

    async def _raw_slice(self, project_id: str) -> dict[str, Any]:
        """DB read of the `/state`-shaped payload (pre-filter).

        Shape mirrors routers/projects.py:get_project_state. Kept in sync
        by hand — if that router learns a new section, add it here.
        """
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return {
                    "project": None,
                    "graph": {
                        "goals": [],
                        "deliverables": [],
                        "constraints": [],
                        "risks": [],
                    },
                    "plan": {
                        "tasks": [],
                        "dependencies": [],
                        "milestones": [],
                    },
                    "assignments": [],
                    "decisions": [],
                    "commitments": [],
                    "members": [],
                }

            req = await RequirementRepository(session).latest_for_project(
                project_id
            )
            graph = {
                "goals": [],
                "deliverables": [],
                "constraints": [],
                "risks": [],
            }
            plan = {"tasks": [], "dependencies": [], "milestones": []}
            if req is not None:
                graph_raw = await ProjectGraphRepository(session).list_all(
                    req.id
                )
                graph = {
                    "goals": [
                        {
                            "id": r.id,
                            "title": r.title,
                            "description": r.description,
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

            assignment_rows = await AssignmentRepository(
                session
            ).list_for_project(project_id)
            assignments = [
                {
                    "id": a.id,
                    "task_id": a.task_id,
                    "user_id": a.user_id,
                    "active": a.active,
                }
                for a in assignment_rows
            ]

            decision_rows = await DecisionRepository(session).list_for_project(
                project_id, limit=50
            )
            decisions = [
                {
                    "id": d.id,
                    "project_id": d.project_id,
                    "resolver_id": d.resolver_id,
                    "rationale": d.rationale,
                    "custom_text": d.custom_text,
                }
                for d in decision_rows
            ]

            commitment_rows = await CommitmentRepository(
                session
            ).list_for_project(project_id, limit=200)
            commitments = [
                {
                    "id": c.id,
                    "headline": c.headline,
                    "scope_ref_kind": c.scope_ref_kind,
                    "scope_ref_id": c.scope_ref_id,
                    "owner_user_id": c.owner_user_id,
                    "status": c.status,
                }
                for c in commitment_rows
            ]

            member_rows = await ProjectMemberRepository(
                session
            ).list_for_project(project_id)
            members = [
                {
                    "user_id": m.user_id,
                    "role": m.role,
                    "license_tier": m.license_tier,
                }
                for m in member_rows
            ]

        return {
            "project": {"id": project.id, "title": project.title},
            "graph": graph,
            "plan": plan,
            "assignments": assignments,
            "decisions": decisions,
            "commitments": commitments,
            "members": members,
        }

    async def build_slice(
        self,
        *,
        project_id: str,
        viewer_user_id: str,
        audience_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch the project state filtered by the tighter of (viewer,
        audience). Returns the same shape as `/state` minus the parsed-
        requirement / conflicts / delivery sections that agents don't
        need. Always includes a `license_tier` key naming the effective
        tier used to build the slice.
        """
        # Import locally to avoid a circular import: the router imports
        # services, and LicenseContextService is exported from services.
        from workgraph_api.routers.projects import (
            _apply_observer_scope,
            _apply_task_scope,
        )

        tier = await self.resolve_effective_tier(
            project_id=project_id,
            viewer_user_id=viewer_user_id,
            audience_user_id=audience_user_id,
        )
        raw = await self._raw_slice(project_id)

        # The scope-target user — whose license we are filtering FOR. For
        # cross-user calls (viewer drafting for audience), the filter
        # anchors on the audience; otherwise on the viewer.
        scope_user_id = audience_user_id or viewer_user_id

        graph = raw["graph"]
        plan = raw["plan"]
        assignments = raw["assignments"]
        commitments = raw["commitments"]
        decisions = raw["decisions"]
        members = raw["members"]

        if tier == "task_scoped":
            graph, plan, assignments, commitments = _apply_task_scope(
                viewer_user_id=scope_user_id,
                graph=graph,
                plan=plan,
                assignments=assignments,
                commitments=commitments,
            )
        elif tier == "observer":
            (
                graph,
                plan,
                assignments,
                commitments,
                decisions,
                members,
            ) = _apply_observer_scope(
                viewer_user_id=scope_user_id,
                graph=graph,
                plan=plan,
                assignments=assignments,
                commitments=commitments,
                decisions=decisions,
                members=members,
            )

        return {
            "project": raw["project"],
            "graph": graph,
            "plan": plan,
            "assignments": assignments,
            "decisions": decisions,
            "commitments": commitments,
            "members": members,
            "license_tier": tier,
            "scope_user_id": scope_user_id,
        }

    def collect_visible_node_ids(self, slice_: dict[str, Any]) -> set[str]:
        """Flatten every node id that appears in the sliced payload.

        Used by the outbound-lint path to check whether a cited id
        falls inside the recipient's view.
        """
        ids: set[str] = set()
        graph = slice_.get("graph") or {}
        for key in ("goals", "deliverables", "constraints", "risks"):
            for row in graph.get(key) or []:
                rid = row.get("id")
                if rid:
                    ids.add(str(rid))
        plan = slice_.get("plan") or {}
        for t in plan.get("tasks") or []:
            tid = t.get("id")
            if tid:
                ids.add(str(tid))
        for m in plan.get("milestones") or []:
            mid = m.get("id")
            if mid:
                ids.add(str(mid))
        for d in slice_.get("decisions") or []:
            did = d.get("id")
            if did:
                ids.add(str(did))
        for c in slice_.get("commitments") or []:
            cid = c.get("id")
            if cid:
                ids.add(str(cid))
        return ids


__all__ = ["LicenseContextService", "tighter_tier"]
