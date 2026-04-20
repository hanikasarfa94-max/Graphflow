"""License scope filter tests (Sprint 3c).

Unit tests on `_apply_task_scope` — the pure function that filters
the /state payload to a task_scoped member's subgraph. HTTP-level
coverage lands once the auth-helper pattern for conftest matures;
for v1 the unit tests prove the filter contract.
"""
from __future__ import annotations

from workgraph_api.routers.projects import _apply_task_scope


def _sample_graph(
    goal_id: str = "g-1",
    deliverable_ids: tuple[str, ...] = ("d-1", "d-2"),
    risk_id: str = "r-1",
) -> dict:
    return {
        "goals": [{"id": goal_id, "title": "Goal"}],
        "deliverables": [
            {"id": d, "title": f"Del {d}"} for d in deliverable_ids
        ],
        "constraints": [],
        "risks": [{"id": risk_id, "title": "risk"}],
    }


def _sample_plan(
    tasks: list[dict] | None = None,
    dependencies: list[dict] | None = None,
) -> dict:
    return {
        "tasks": tasks or [],
        "dependencies": dependencies or [],
        "milestones": [],
    }


def test_task_scope_filters_tasks_to_viewer_assignments():
    viewer = "u-1"
    tasks = [
        {"id": "t-1", "title": "mine", "deliverable_id": "d-1"},
        {"id": "t-2", "title": "theirs", "deliverable_id": "d-2"},
    ]
    deps = [
        {"id": "dep-1", "from_task_id": "t-1", "to_task_id": "t-2"},
    ]
    assignments = [
        {"id": "a-1", "task_id": "t-1", "user_id": viewer, "active": True},
        {"id": "a-2", "task_id": "t-2", "user_id": "u-2", "active": True},
    ]
    graph, plan, visible_assignments, _ = _apply_task_scope(
        viewer_user_id=viewer,
        graph=_sample_graph(),
        plan=_sample_plan(tasks=tasks, dependencies=deps),
        assignments=assignments,
        commitments=[],
    )
    assert [t["id"] for t in plan["tasks"]] == ["t-1"]
    # Cross-boundary dep dropped — endpoint t-2 isn't visible.
    assert plan["dependencies"] == []
    # Deliverables filtered to the one the visible task anchors to.
    assert [d["id"] for d in graph["deliverables"]] == ["d-1"]
    # Viewer's own assignments only.
    assert [a["id"] for a in visible_assignments] == ["a-1"]


def test_task_scope_keeps_unanchored_commitments():
    viewer = "u-1"
    commitments = [
        {"id": "c-1", "headline": "unscoped", "scope_ref_id": None},
        {"id": "c-2", "headline": "anchored-visible", "scope_ref_id": "t-1"},
        {"id": "c-3", "headline": "anchored-invisible", "scope_ref_id": "t-2"},
    ]
    assignments = [
        {"id": "a-1", "task_id": "t-1", "user_id": viewer, "active": True},
    ]
    _, _, _, visible_commitments = _apply_task_scope(
        viewer_user_id=viewer,
        graph=_sample_graph(),
        plan=_sample_plan(
            tasks=[
                {"id": "t-1", "title": "mine", "deliverable_id": None},
                {"id": "t-2", "title": "theirs", "deliverable_id": None},
            ],
        ),
        assignments=assignments,
        commitments=commitments,
    )
    ids = [c["id"] for c in visible_commitments]
    assert "c-1" in ids  # unscoped survives
    assert "c-2" in ids  # anchored to visible task
    assert "c-3" not in ids  # anchored to invisible task — dropped


def test_task_scope_inactive_assignment_does_not_grant_visibility():
    viewer = "u-1"
    assignments = [
        {"id": "a-old", "task_id": "t-1", "user_id": viewer, "active": False},
    ]
    _, plan, _, _ = _apply_task_scope(
        viewer_user_id=viewer,
        graph=_sample_graph(),
        plan=_sample_plan(
            tasks=[{"id": "t-1", "title": "was mine", "deliverable_id": None}]
        ),
        assignments=assignments,
        commitments=[],
    )
    assert plan["tasks"] == []


def test_task_scope_keeps_goals_and_risks():
    """Goals + risks are environmental context, not sensitive. They
    survive filtering."""
    viewer = "u-1"
    graph, _, _, _ = _apply_task_scope(
        viewer_user_id=viewer,
        graph=_sample_graph(),
        plan=_sample_plan(),
        assignments=[],
        commitments=[],
    )
    assert len(graph["goals"]) == 1
    assert len(graph["risks"]) == 1


def test_task_scope_keeps_commitment_anchored_to_deliverable():
    viewer = "u-1"
    commitments = [
        {"id": "c-1", "scope_ref_id": "d-1"},
        {"id": "c-2", "scope_ref_id": "d-2"},
    ]
    assignments = [
        {"id": "a-1", "task_id": "t-1", "user_id": viewer, "active": True},
    ]
    _, _, _, visible = _apply_task_scope(
        viewer_user_id=viewer,
        graph=_sample_graph(),
        plan=_sample_plan(
            tasks=[{"id": "t-1", "title": "t", "deliverable_id": "d-1"}]
        ),
        assignments=assignments,
        commitments=commitments,
    )
    ids = [c["id"] for c in visible]
    assert "c-1" in ids  # d-1 is visible
    assert "c-2" not in ids  # d-2 invisible
