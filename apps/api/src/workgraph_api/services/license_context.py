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

import logging
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


_log = logging.getLogger("workgraph.api.license_context")

# Tightness ordering — the bigger number wins when comparing two tiers.
# `observer` is the most restrictive; any unknown/corrupt tier value is
# coerced to `observer` at resolution time so the system fails CLOSED.
_TIER_TIGHTNESS = {"full": 0, "task_scoped": 1, "observer": 2}
_MOST_RESTRICTIVE_TIER = "observer"
KNOWN_TIERS: frozenset[str] = frozenset(_TIER_TIGHTNESS.keys())


def _coerce_known_tier(value: str | None, *, context: str) -> str:
    """Normalize a tier string to one of the known tiers.

    Unknown/None/empty values collapse to the most-restrictive tier
    (`observer`) and emit a warning so ops can notice schema drift,
    test-injected bogus values, or forward-compat tiers that the code
    does not yet understand. This is the explicit fail-CLOSED policy
    for license-tier resolution.
    """
    if value in KNOWN_TIERS:
        return value  # type: ignore[return-value]
    _log.warning(
        "license tier %r is not in known set %s (context=%s); "
        "coercing to most-restrictive tier %r",
        value,
        sorted(KNOWN_TIERS),
        context,
        _MOST_RESTRICTIVE_TIER,
    )
    return _MOST_RESTRICTIVE_TIER


def tighter_tier(a: str, b: str) -> str:
    """Return whichever tier is more restrictive.

    Any unrecognized tier (None, empty, typo, future tier value, test
    injection) is coerced to the most-restrictive tier (`observer`)
    before comparison — i.e. fail CLOSED. A warning is logged so the
    drift is visible."""
    a_safe = _coerce_known_tier(a, context="tighter_tier.a")
    b_safe = _coerce_known_tier(b, context="tighter_tier.b")
    ra = _TIER_TIGHTNESS[a_safe]
    rb = _TIER_TIGHTNESS[b_safe]
    return a_safe if ra >= rb else b_safe


# ScopeTierPills (frontend) wire format. Each pill toggle maps to one
# of these strings; `group` is the legacy schema value for "Cell" scope
# (PLAN-Next §"Schema decisions"). Persisted KbItemRow.scope uses the
# same vocabulary, so the intersection happens in one namespace.
VALID_SCOPE_TIERS: frozenset[str] = frozenset(
    {"personal", "group", "department", "enterprise"}
)

# Which scope tiers each license tier is allowed to request.
#
#   * `full`        — sees every scope tier
#   * `task_scoped` — sees the cell + cross-cell context their task
#                     anchors require, plus their own personal items;
#                     no broader department/enterprise sweep
#   * `observer`    — only the cell-shared canon; no personal items,
#                     no broader sweep
#
# `personal` always means "the viewer's OWN personal items" (other
# users' personal items never appear in any tier's allowed set —
# scope filtering at the row level enforces that elsewhere). The
# pill simply controls whether the viewer wants their own personal
# notes mixed into the agent's context for this turn.
_TIER_TO_ALLOWED_SCOPES: dict[str, frozenset[str]] = {
    "full": frozenset({"personal", "group", "department", "enterprise"}),
    "task_scoped": frozenset({"personal", "group"}),
    "observer": frozenset({"group"}),
}


class LicenseContextService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def _member_tier(
        self, *, project_id: str, user_id: str
    ) -> str | None:
        """Return the user's license_tier for this project, or None if
        they are not a project member.

        Any non-null tier value that isn't in the known-tier set is
        coerced to the most-restrictive tier and a warning is logged
        (see `_coerce_known_tier`). Returning `None` here is still
        meaningful: it signals non-membership so the caller can apply
        observer semantics at the audience boundary."""
        async with session_scope(self._sessionmaker) as session:
            rows = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            for r in rows:
                if r.user_id == user_id:
                    raw = r.license_tier
                    if raw is None:
                        # NULL → unknown → fail closed. Persisted schema
                        # defaults to "full" at INSERT, so this branch
                        # only fires if the column was explicitly nulled
                        # or loaded from legacy data.
                        return _coerce_known_tier(
                            None,
                            context=(
                                f"_member_tier(project={project_id},"
                                f"user={user_id}):null"
                            ),
                        )
                    return _coerce_known_tier(
                        str(raw),
                        context=(
                            f"_member_tier(project={project_id},"
                            f"user={user_id})"
                        ),
                    )
        return None

    async def allowed_scopes(
        self,
        *,
        project_id: str,
        user_id: str,
        requested_tiers: dict[str, bool] | None = None,
    ) -> frozenset[str]:
        """Intersect (what the user is licensed to see) ∩ (which pills
        they have toggled on).

        `requested_tiers` is the ScopeTierPills wire shape from the
        frontend: `{"personal": bool, "group": bool, "department": bool,
        "enterprise": bool}`. Unknown keys are ignored; missing keys
        default to ON (matches the frontend's all-on default).

        Returns the FROZENSET of scope strings the caller should pass
        to retrieval / context-assembly filters. Empty set is a
        meaningful signal — the user toggled every pill OFF or has no
        license for any tier — and downstream consumers should treat
        it as "show nothing scope-tier-keyed."

        `requested_tiers=None` (legacy callers pre-N.2) skips the pill
        intersection — equivalent to "all four pills on" so existing
        behavior is preserved.

        Fails CLOSED on every ambiguity:
          * Non-member user → no scopes (empty set).
          * Unknown license tier → coerced to `observer` (group only).
          * Garbage key in requested_tiers → ignored.
        """
        # Resolve viewer's license tier; non-member returns None.
        viewer_tier = await self._member_tier(
            project_id=project_id, user_id=user_id
        )
        if viewer_tier is None:
            return frozenset()
        licensed = _TIER_TO_ALLOWED_SCOPES.get(viewer_tier, frozenset({"group"}))

        # Default behavior when no pill state was sent: equivalent to
        # all-on. This preserves slice-5c's pre-pickup-7 behavior for
        # any callsite that hasn't migrated to pass scope_tiers yet.
        if requested_tiers is None:
            return licensed

        requested: set[str] = set()
        for key, on in requested_tiers.items():
            if not isinstance(key, str):
                continue
            if key not in VALID_SCOPE_TIERS:
                continue
            if on:
                requested.add(key)

        return licensed & frozenset(requested)

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
            # Resolve resolver display names so DecisionsPanel doesn't
            # have to render UUIDs. Single bulk SELECT keyed by id;
            # missing rows tolerated (resolver_id is SET NULL on user
            # delete, so a deleted user just shows as their UUID).
            from workgraph_persistence.orm import UserRow

            resolver_ids = list(
                {d.resolver_id for d in decision_rows if d.resolver_id}
            )
            resolver_lookup: dict[str, UserRow] = {}
            if resolver_ids:
                rows = (
                    await session.execute(
                        select(UserRow).where(UserRow.id.in_(resolver_ids))
                    )
                ).scalars().all()
                resolver_lookup = {u.id: u for u in rows}

            def _resolver_display(rid: str | None) -> str | None:
                if not rid:
                    return None
                u = resolver_lookup.get(rid)
                if u is None:
                    return None
                return u.display_name or u.username

            decisions = [
                {
                    "id": d.id,
                    "project_id": d.project_id,
                    "resolver_id": d.resolver_id,
                    "resolver_display_name": _resolver_display(d.resolver_id),
                    "rationale": d.rationale,
                    "custom_text": d.custom_text,
                    # Provenance fields the DecisionsPanel needs to
                    # render "how this decision was made". Stripped
                    # historically; restored 2026-04-25 after a QA
                    # report that the dashboard hides these.
                    "conflict_id": d.conflict_id,
                    "source_suggestion_id": d.source_suggestion_id,
                    "gated_via_proposal_id": d.gated_via_proposal_id,
                    "decision_class": d.decision_class,
                    "apply_outcome": d.apply_outcome,
                    "option_index": d.option_index,
                    "created_at": (
                        d.created_at.isoformat() if d.created_at else None
                    ),
                    "applied_at": (
                        d.applied_at.isoformat() if d.applied_at else None
                    ),
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
            # Resolve display_name + username so downstream renderers
            # (onboarding tour, render templates) don't have to fall
            # back to raw UUIDs ("teammate 4f9b3353"). Single bulk
            # SELECT keyed by id; missing rows are tolerated.
            from workgraph_persistence.orm import UserRow

            member_user_ids = [m.user_id for m in member_rows if m.user_id]
            user_lookup: dict[str, UserRow] = {}
            if member_user_ids:
                rows = (
                    await session.execute(
                        select(UserRow).where(UserRow.id.in_(member_user_ids))
                    )
                ).scalars().all()
                user_lookup = {u.id: u for u in rows}
            members = []
            for m in member_rows:
                u = user_lookup.get(m.user_id)
                members.append(
                    {
                        "user_id": m.user_id,
                        "role": m.role,
                        "license_tier": m.license_tier,
                        "display_name": (u.display_name or u.username) if u else None,
                        "username": u.username if u else None,
                    }
                )

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
