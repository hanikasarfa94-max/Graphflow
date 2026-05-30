"""License-tier scoping policy for the project `/state` read model.

The single shared path for "what each license tier may see" in the human-read
composite snapshot (audit H6). Previously these were router-local helpers in
`routers/projects.py`; moving them into the service layer gives the read model
one policy home that `ProjectStateService` applies. Pure functions — no I/O —
so they unit-test directly (see test_license_scope.py / test_observer_scope.py).

NOTE: LLM-context scoping still lives separately in `LicenseContextService`.
Unifying the two scope definitions is a deeper follow-up (different payload
shapes); flagged in ARCHITECTURE-AUDIT-2026-05-30.md H6.
"""

from __future__ import annotations

from typing import Any


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
