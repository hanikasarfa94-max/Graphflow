"""Phase T+1 — personal-task promote-via-membrane tests.

Covers:
  * GET /api/projects/{id}/personal-tasks (list endpoint)
  * POST /api/projects/{id}/tasks (create with optional estimate/role)
  * POST /api/tasks/{id}/promote
      - auto_merge path → flips scope, attaches to plan
      - request_review path → inbox enqueue, deferred=true
      - request_clarification path → notify_clarification side-effect
  * Membrane warnings surface in promote response (Stage 6)
  * im.py membrane_review accept handler — task_promote branch
    (regression cover for the bug we just fixed)
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    IMSuggestionRow,
    MessageRow,
    PlanRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRow,
    StreamRow,
    TaskRow,
    session_scope,
)


# ---- helpers ----------------------------------------------------------


async def _register_and_login(client, username: str) -> str:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _login(client, username: str) -> None:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


async def _mk_project_with_requirement(
    maker,
    *,
    owner_id: str,
    extra_member_id: str | None = None,
    budget_hours: int | None = None,
) -> tuple[str, str]:
    """Project + project-stream + requirement (so promote auto-merge has a
    target). Returns (project_id, requirement_id)."""
    pid = str(uuid.uuid4())
    req_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="Promote Test"))
        session.add(StreamRow(id=str(uuid.uuid4()), type="project", project_id=pid))
        session.add(
            RequirementRow(
                id=req_id,
                project_id=pid,
                version=1,
                raw_text="canonical scope",
                budget_hours=budget_hours,
            )
        )
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        if extra_member_id is not None:
            await ProjectMemberRepository(session).add(
                project_id=pid, user_id=extra_member_id, role="member"
            )
    return pid, req_id


# ---- list + create -----------------------------------------------------


@pytest.mark.asyncio
async def test_list_personal_tasks_owner_only(api_env):
    client, maker, *_ = api_env
    a_id = await _register_and_login(client, "pt_a")
    b_id = await _register_and_login(client, "pt_b")
    pid, _ = await _mk_project_with_requirement(
        maker, owner_id=a_id, extra_member_id=b_id
    )

    await _login(client, "pt_a")
    r = await client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "alice draft"},
    )
    assert r.status_code == 200, r.text
    a_task_id = r.json()["task"]["id"]

    # Alice sees her own draft.
    r = await client.get(f"/api/projects/{pid}/personal-tasks")
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()["tasks"]]
    assert "alice draft" in titles

    # Bob doesn't see Alice's draft.
    await _login(client, "pt_b")
    r = await client.get(f"/api/projects/{pid}/personal-tasks")
    assert r.status_code == 200
    assert r.json()["tasks"] == []

    # Non-member is forbidden.
    c_id = await _register_and_login(client, "pt_c")  # noqa: F841
    r = await client.get(f"/api/projects/{pid}/personal-tasks")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_persists_estimate_and_role(api_env):
    client, maker, *_ = api_env
    a_id = await _register_and_login(client, "pt_e_a")
    pid, _ = await _mk_project_with_requirement(maker, owner_id=a_id)

    await _login(client, "pt_e_a")
    r = await client.post(
        f"/api/projects/{pid}/tasks",
        json={
            "title": "with estimate",
            "estimate_hours": 8,
            "assignee_role": "backend",
        },
    )
    assert r.status_code == 200, r.text
    task = r.json()["task"]
    assert task["estimate_hours"] == 8
    assert task["assignee_role"] == "backend"


# ---- promote auto_merge -----------------------------------------------


@pytest.mark.asyncio
async def test_promote_auto_merge_flips_scope_to_plan(api_env):
    client, maker, *_ = api_env
    a_id = await _register_and_login(client, "pt_m_a")
    pid, req_id = await _mk_project_with_requirement(maker, owner_id=a_id)

    await _login(client, "pt_m_a")
    r = await client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "implement search v1"},
    )
    task_id = r.json()["task"]["id"]

    r = await client.post(f"/api/tasks/{task_id}/promote")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task"] is not None
    assert body["task"]["scope"] == "plan"
    assert body["task"]["requirement_id"] == req_id
    assert body.get("warnings") == []


# ---- promote request_review (duplicate title with active plan task) ---


@pytest.mark.asyncio
async def test_promote_duplicate_title_defers_with_inbox_card(api_env):
    """An active plan task with the same normalized title triggers
    request_review → defer + post IMSuggestion(kind='membrane_review')
    in the team stream."""
    client, maker, *_ = api_env
    a_id = await _register_and_login(client, "pt_d_a")
    pid, req_id = await _mk_project_with_requirement(maker, owner_id=a_id)

    # Pre-seed an active plan task with the same title.
    async with session_scope(maker) as session:
        session.add(
            TaskRow(
                id=str(uuid.uuid4()),
                project_id=pid,
                requirement_id=req_id,
                sort_order=0,
                deliverable_id=None,
                title="Implement OAuth",
                description="",
                assignee_role="backend",
                estimate_hours=4,
                acceptance_criteria=None,
                scope="plan",
                owner_user_id=None,
                source_message_id=None,
                status="open",
            )
        )

    await _login(client, "pt_d_a")
    r = await client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "implement oauth"},  # normalized → same
    )
    task_id = r.json()["task"]["id"]

    r = await client.post(f"/api/tasks/{task_id}/promote")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deferred"] is True
    assert body["task"] is None
    assert body["reason"] == "duplicate_title"

    # IMSuggestion(kind='membrane_review') landed in the team stream
    # with detail.candidate_kind='task_promote' so the accept handler
    # routes correctly.
    async with session_scope(maker) as session:
        rows = (
            await session.execute(
                select(IMSuggestionRow).where(
                    IMSuggestionRow.project_id == pid,
                    IMSuggestionRow.kind == "membrane_review",
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    proposal = rows[0].proposal or {}
    detail = proposal.get("detail", {})
    assert detail.get("candidate_kind") == "task_promote"
    assert detail.get("task_id") == task_id


# ---- accept membrane_review for task_promote (the bug we just fixed) --


@pytest.mark.asyncio
async def test_owner_accepts_task_promote_review(api_env):
    """End-to-end: dup-title defer → owner accepts via /collab/suggestions/
    {id}/accept → task flips to plan. Pre-fix this errored
    'missing_kb_item_id' because the accept handler only knew kb_item_id."""
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "pt_acc_owner")
    member_id = await _register_and_login(client, "pt_acc_mem")
    pid, req_id = await _mk_project_with_requirement(
        maker, owner_id=owner_id, extra_member_id=member_id
    )
    # Pre-seed an active plan task to force request_review.
    async with session_scope(maker) as session:
        session.add(
            TaskRow(
                id=str(uuid.uuid4()),
                project_id=pid,
                requirement_id=req_id,
                sort_order=0,
                deliverable_id=None,
                title="ship beta",
                description="",
                assignee_role="frontend",
                estimate_hours=None,
                acceptance_criteria=None,
                scope="plan",
                owner_user_id=None,
                source_message_id=None,
                status="open",
            )
        )

    # Member creates + promotes their personal draft.
    await _login(client, "pt_acc_mem")
    r = await client.post(f"/api/projects/{pid}/tasks", json={"title": "Ship Beta"})
    task_id = r.json()["task"]["id"]
    r = await client.post(f"/api/tasks/{task_id}/promote")
    assert r.json()["deferred"] is True

    # Find the queued suggestion id.
    async with session_scope(maker) as session:
        sug_id = (
            await session.execute(
                select(IMSuggestionRow.id).where(
                    IMSuggestionRow.project_id == pid,
                    IMSuggestionRow.kind == "membrane_review",
                )
            )
        ).scalar_one()

    # Owner accepts.
    await _login(client, "pt_acc_owner")
    r = await client.post(f"/api/im_suggestions/{sug_id}/accept")
    assert r.status_code == 200, r.text

    # Task is now plan-scope.
    async with session_scope(maker) as session:
        promoted = (
            await session.execute(
                select(TaskRow).where(TaskRow.id == task_id)
            )
        ).scalar_one()
    assert promoted.scope == "plan"
    assert promoted.requirement_id == req_id


# ---- Stage 6: budget overflow warning ----------------------------------


@pytest.mark.asyncio
async def test_promote_surfaces_budget_overflow_warning(api_env):
    client, maker, *_ = api_env
    a_id = await _register_and_login(client, "pt_b_owner")
    pid, req_id = await _mk_project_with_requirement(
        maker, owner_id=a_id, budget_hours=10
    )
    # Pre-seed plan tasks summing to 9 hours → adding another 4h pushes
    # over the 10h budget.
    async with session_scope(maker) as session:
        for idx, hrs in enumerate((5, 4)):
            session.add(
                TaskRow(
                    id=str(uuid.uuid4()),
                    project_id=pid,
                    requirement_id=req_id,
                    sort_order=idx,
                    deliverable_id=None,
                    title=f"existing {hrs}h",
                    description="",
                    assignee_role="unknown",
                    estimate_hours=hrs,
                    acceptance_criteria=None,
                    scope="plan",
                    owner_user_id=None,
                    source_message_id=None,
                    status="open",
                )
            )

    await _login(client, "pt_b_owner")
    r = await client.post(
        f"/api/projects/{pid}/tasks",
        json={"title": "new feature", "estimate_hours": 4},
    )
    task_id = r.json()["task"]["id"]

    r = await client.post(f"/api/tasks/{task_id}/promote")
    assert r.status_code == 200, r.text
    body = r.json()
    # Auto-merged (no title dup) but with a budget warning surfaced.
    assert body["task"] is not None
    warnings = body.get("warnings") or []
    assert any("budget" in w.lower() for w in warnings)


# ---- Stage 5 — clarification routes to proposer's personal stream -----


@pytest.mark.asyncio
async def test_kb_clarification_posts_to_proposer_personal_stream(api_env):
    """When _review_kb_item_group returns request_clarification (title
    matches existing entry but body size diverges notably), the question
    lands in the PROPOSER's personal stream — not team room — and no
    membrane_review inbox card is created."""
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "kb_clar_owner")
    member_id = await _register_and_login(client, "kb_clar_mem")
    pid, _ = await _mk_project_with_requirement(
        maker, owner_id=owner_id, extra_member_id=member_id
    )

    # Existing group KB entry with substantial body.
    await _login(client, "kb_clar_owner")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "deployment runbook",
            "content_md": "x" * 800,
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text

    # Member writes a tiny new entry with the same title — content
    # size diverges by >2x → clarification, not review.
    await _login(client, "kb_clar_mem")
    r = await client.post(
        f"/api/projects/{pid}/kb-items",
        json={
            "title": "deployment runbook",
            "content_md": "tl;dr",
            "scope": "group",
        },
    )
    assert r.status_code == 200, r.text

    # No membrane_review IMSuggestion (clarification doesn't go to team).
    # A membrane-clarify message lands in the member's personal stream.
    async with session_scope(maker) as session:
        sugs = (
            await session.execute(
                select(IMSuggestionRow).where(
                    IMSuggestionRow.project_id == pid,
                    IMSuggestionRow.kind == "membrane_review",
                )
            )
        ).scalars().all()
        clarify_msgs = (
            await session.execute(
                select(MessageRow).where(
                    MessageRow.project_id == pid,
                    MessageRow.kind == "membrane-clarify",
                    MessageRow.author_id == EDGE_AGENT_SYSTEM_USER_ID,
                )
            )
        ).scalars().all()
    assert sugs == []
    assert len(clarify_msgs) == 1
    assert "supersede" in clarify_msgs[0].body.lower()
