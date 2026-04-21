"""Observer-tier read-side scope filter tests.

Unit tests on `_apply_observer_scope` — the external-auditor
subgraph slicer. Observers see only nodes with an explicit link
to them (assigned tasks, resolved decisions); everything else is
stripped. `test_license_scope.py` covers the task_scoped filter
and is the regression guard that this change leaves that behavior
untouched.
"""
from __future__ import annotations

from workgraph_api.routers.projects import (
    _apply_observer_scope,
    _apply_task_scope,
)


def _graph() -> dict:
    return {
        "goals": [{"id": "g-1", "title": "Goal"}],
        "deliverables": [
            {"id": "d-1", "title": "Del 1"},
            {"id": "d-2", "title": "Del 2"},
        ],
        "constraints": [{"id": "c-1", "content": "must"}],
        "risks": [{"id": "r-1", "title": "risk"}],
    }


def _plan() -> dict:
    return {
        "tasks": [
            {"id": "t-1", "title": "mine", "deliverable_id": "d-1"},
            {"id": "t-2", "title": "theirs", "deliverable_id": "d-2"},
        ],
        "dependencies": [
            {"id": "dep-1", "from_task_id": "t-1", "to_task_id": "t-2"},
        ],
        "milestones": [{"id": "m-1", "title": "ship"}],
    }


def _members() -> list[dict]:
    return [
        {"user_id": "u-observer", "username": "audit", "role": "member"},
        {"user_id": "u-1", "username": "alice", "role": "member"},
        {"user_id": "u-2", "username": "bob", "role": "member"},
    ]


def test_observer_with_zero_assignments_sees_empty_subgraph_but_members_kept():
    graph, plan, assignments, commitments, decisions, members = (
        _apply_observer_scope(
            viewer_user_id="u-observer",
            graph=_graph(),
            plan=_plan(),
            assignments=[
                {"id": "a-1", "task_id": "t-1", "user_id": "u-1", "active": True},
                {"id": "a-2", "task_id": "t-2", "user_id": "u-2", "active": True},
            ],
            commitments=[
                {"id": "c-1", "scope_ref_id": None},
                {"id": "c-2", "scope_ref_id": "t-1"},
            ],
            decisions=[
                {"id": "dec-1", "resolver_id": "u-1"},
                {"id": "dec-2", "resolver_id": "u-2"},
            ],
            members=_members(),
        )
    )
    assert plan["tasks"] == []
    assert plan["dependencies"] == []
    assert plan["milestones"] == []
    assert graph["goals"] == []
    assert graph["deliverables"] == []
    assert graph["constraints"] == []
    assert graph["risks"] == []
    assert assignments == []
    assert commitments == []
    assert decisions == []
    # Members list stays populated; viewer's own row is flagged.
    assert [m["user_id"] for m in members] == ["u-observer", "u-1", "u-2"]
    viewer_row = next(m for m in members if m["user_id"] == "u-observer")
    assert viewer_row["is_viewer"] is True
    for m in members:
        if m["user_id"] != "u-observer":
            assert m["is_viewer"] is False


def test_observer_with_one_assigned_task_sees_exactly_that_task():
    _, plan, assignments, _, _, _ = _apply_observer_scope(
        viewer_user_id="u-observer",
        graph=_graph(),
        plan=_plan(),
        assignments=[
            {"id": "a-1", "task_id": "t-1", "user_id": "u-observer", "active": True},
            {"id": "a-2", "task_id": "t-2", "user_id": "u-2", "active": True},
        ],
        commitments=[],
        decisions=[],
        members=_members(),
    )
    assert [t["id"] for t in plan["tasks"]] == ["t-1"]
    # Dep t-1 -> t-2 dropped: t-2 is invisible.
    assert plan["dependencies"] == []
    assert [a["id"] for a in assignments] == ["a-1"]


def test_observer_sees_only_decisions_they_resolved():
    _, _, _, _, decisions, _ = _apply_observer_scope(
        viewer_user_id="u-observer",
        graph=_graph(),
        plan=_plan(),
        assignments=[],
        commitments=[],
        decisions=[
            {"id": "dec-1", "resolver_id": "u-observer", "rationale": "mine"},
            {"id": "dec-2", "resolver_id": "u-1", "rationale": "hers"},
            {"id": "dec-3", "resolver_id": None, "rationale": "unresolved"},
        ],
        members=_members(),
    )
    assert [d["id"] for d in decisions] == ["dec-1"]


def test_observer_ignores_inactive_assignments():
    _, plan, _, _, _, _ = _apply_observer_scope(
        viewer_user_id="u-observer",
        graph=_graph(),
        plan=_plan(),
        assignments=[
            {"id": "a-old", "task_id": "t-1", "user_id": "u-observer", "active": False},
        ],
        commitments=[],
        decisions=[],
        members=_members(),
    )
    assert plan["tasks"] == []


def test_task_scoped_filter_unchanged_regression():
    """Regression guard: task_scoped semantics (keeps goals/risks,
    keeps anchored commitments) are untouched by the observer
    addition."""
    viewer = "u-1"
    graph, plan, visible_assignments, visible_commitments = _apply_task_scope(
        viewer_user_id=viewer,
        graph=_graph(),
        plan=_plan(),
        assignments=[
            {"id": "a-1", "task_id": "t-1", "user_id": viewer, "active": True},
            {"id": "a-2", "task_id": "t-2", "user_id": "u-2", "active": True},
        ],
        commitments=[
            {"id": "c-0", "scope_ref_id": None},
            {"id": "c-1", "scope_ref_id": "t-1"},
            {"id": "c-2", "scope_ref_id": "t-2"},
        ],
    )
    assert [t["id"] for t in plan["tasks"]] == ["t-1"]
    assert plan["dependencies"] == []
    assert [d["id"] for d in graph["deliverables"]] == ["d-1"]
    # Goals + risks survive for task_scoped (environmental context).
    assert len(graph["goals"]) == 1
    assert len(graph["risks"]) == 1
    assert [a["id"] for a in visible_assignments] == ["a-1"]
    commitment_ids = [c["id"] for c in visible_commitments]
    assert "c-0" in commitment_ids
    assert "c-1" in commitment_ids
    assert "c-2" not in commitment_ids


def test_full_tier_viewer_is_not_filtered():
    """Full-tier viewers bypass both filters — the /state handler
    only calls a filter when viewer_tier matches. Verify that by
    confirming the filters aren't invoked for 'full' (this is a
    structural assertion: we only wire _apply_*_scope behind tier
    checks, never unconditionally).

    The check is lightweight: read the router source and assert the
    observer branch is tier-gated the same way the task_scoped
    branch is.
    """
    from workgraph_api.routers import projects as projects_module
    import inspect

    source = inspect.getsource(projects_module.get_project_state)
    assert 'if viewer_tier == "task_scoped":' in source
    assert 'elif viewer_tier == "observer":' in source
    # The `full` path has no filter branch, so full-tier sees the
    # unmodified graph/plan/etc. passed into the response dict.
