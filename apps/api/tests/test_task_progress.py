"""Phase U — task status self-reports + leader scoring tests."""
from __future__ import annotations

import uuid

import pytest

from workgraph_persistence import (
    AssignmentRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRow,
    TaskRow,
    UserRepository,
    session_scope,
)


# ---- helpers ------------------------------------------------------------


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


async def _seed_project_with_task(maker, *, owner_id: str, assignee_id: str):
    """Insert a project + requirement + task + active assignment."""
    pid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="Stellar Drift"))
        session.add(
            RequirementRow(id=rid, project_id=pid, raw_text="x", version=1)
        )
        session.add(
            TaskRow(
                id=tid,
                project_id=pid,
                requirement_id=rid,
                title="Wire OTP",
                description="hand-rolled OTP service",
                status="open",
                sort_order=0,
            )
        )
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=assignee_id, role="member"
        )
        await AssignmentRepository(session).set_assignment(
            project_id=pid, task_id=tid, user_id=assignee_id
        )
    return pid, tid


# ---- 1. status updates --------------------------------------------------


@pytest.mark.asyncio
async def test_assignee_can_walk_through_status_states(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_1")
    assignee_id = await _register_and_login(client, "tp_assignee_1")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_assignee_1")
    r = await client.post(
        f"/api/tasks/{tid}/status",
        json={"new_status": "in_progress", "note": "started"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "in_progress"

    r = await client.post(
        f"/api/tasks/{tid}/status",
        json={"new_status": "done", "note": "shipped to staging"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "done"


@pytest.mark.asyncio
async def test_manual_status_change_writes_replay_log(api_env):
    """H2 regression: a manual task-status transition must append a
    StatusTransitionRow so graph-at-timestamp replay can reconstruct it.

    Before the fix, TaskProgressService.update_status wrote TaskRow.status
    + TaskStatusUpdateRow but skipped the replay log — so scrubbing the
    time-cursor back silently missed every manual transition.
    """
    from sqlalchemy import select
    from workgraph_persistence import StatusTransitionRow

    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_replay_owner")
    assignee_id = await _register_and_login(client, "tp_replay_assignee")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_replay_assignee")
    assert (
        await client.post(
            f"/api/tasks/{tid}/status", json={"new_status": "in_progress"}
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/tasks/{tid}/status", json={"new_status": "done"}
        )
    ).status_code == 200

    async with session_scope(maker) as session:
        rows = (
            (
                await session.execute(
                    select(StatusTransitionRow)
                    .where(StatusTransitionRow.project_id == pid)
                    .where(StatusTransitionRow.entity_kind == "task")
                    .where(StatusTransitionRow.entity_id == tid)
                    .order_by(StatusTransitionRow.changed_at)
                )
            )
            .scalars()
            .all()
        )

    transitions = [(r.old_status, r.new_status) for r in rows]
    assert ("open", "in_progress") in transitions
    assert ("in_progress", "done") in transitions
    # Attribution is preserved on the replay row.
    assert all(r.changed_by_user_id == assignee_id for r in rows)


@pytest.mark.asyncio
async def test_invalid_transition_rejected(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_2")
    assignee_id = await _register_and_login(client, "tp_assignee_2")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_assignee_2")
    # open → done direct (must mark in_progress first).
    r = await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "done"}
    )
    assert r.status_code == 400
    assert r.json()["message"] == "invalid_transition"


@pytest.mark.asyncio
async def test_non_assignee_non_owner_forbidden(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_3")
    assignee_id = await _register_and_login(client, "tp_assignee_3")
    intruder_id = await _register_and_login(client, "tp_intruder_3")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_intruder_3")
    r = await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "in_progress"}
    )
    assert r.status_code == 403
    assert r.json()["message"] == "forbidden"


@pytest.mark.asyncio
async def test_project_owner_can_force_status(api_env):
    """Owner can intervene if assignee ghosts."""
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_4")
    assignee_id = await _register_and_login(client, "tp_assignee_4")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_owner_4")
    r = await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "canceled"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"


# ---- 2. scoring ---------------------------------------------------------


@pytest.mark.asyncio
async def test_owner_scores_done_task(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_5")
    assignee_id = await _register_and_login(client, "tp_assignee_5")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    # Assignee marks done.
    await _login(client, "tp_assignee_5")
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "in_progress"}
    )
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "done"}
    )

    # Owner scores good.
    await _login(client, "tp_owner_5")
    r = await client.post(
        f"/api/tasks/{tid}/score",
        json={"quality": "good", "feedback": "shipped clean"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["quality"] == "good"
    assert r.json()["assignee_user_id"] == assignee_id

    # Re-score updates the same row (upsert).
    r = await client.post(
        f"/api/tasks/{tid}/score",
        json={"quality": "ok", "feedback": "actually a few rough edges"},
    )
    assert r.status_code == 200
    assert r.json()["quality"] == "ok"
    assert r.json()["created"] is False


@pytest.mark.asyncio
async def test_cannot_score_unfinished_task(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_6")
    assignee_id = await _register_and_login(client, "tp_assignee_6")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_owner_6")
    r = await client.post(
        f"/api/tasks/{tid}/score", json={"quality": "good"}
    )
    assert r.status_code == 400
    assert r.json()["message"] == "not_done"


@pytest.mark.asyncio
async def test_non_owner_cannot_score(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_7")
    assignee_id = await _register_and_login(client, "tp_assignee_7")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_assignee_7")
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "in_progress"}
    )
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "done"}
    )

    # Assignee tries to score themselves.
    r = await client.post(
        f"/api/tasks/{tid}/score", json={"quality": "good"}
    )
    assert r.status_code == 403
    assert r.json()["message"] == "forbidden"


# ---- 3. history ---------------------------------------------------------


@pytest.mark.asyncio
async def test_history_shows_status_timeline_and_score(api_env):
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_owner_8")
    assignee_id = await _register_and_login(client, "tp_assignee_8")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_assignee_8")
    await client.post(
        f"/api/tasks/{tid}/status",
        json={"new_status": "in_progress", "note": "started"},
    )
    await client.post(
        f"/api/tasks/{tid}/status",
        json={"new_status": "done", "note": "complete"},
    )
    await _login(client, "tp_owner_8")
    await client.post(
        f"/api/tasks/{tid}/score",
        json={"quality": "good", "feedback": "ok"},
    )

    r = await client.get(f"/api/tasks/{tid}/history")
    assert r.status_code == 200
    data = r.json()
    assert data["current_status"] == "done"
    assert len(data["updates"]) == 2
    assert data["updates"][0]["new_status"] == "in_progress"
    assert data["updates"][1]["new_status"] == "done"
    assert data["score"]["quality"] == "good"
    assert data["score"]["feedback"] == "ok"


# ---- 4. perf integration ------------------------------------------------


@pytest.mark.asyncio
async def test_perf_includes_task_quality_payload(api_env):
    """A scored task surfaces in /team/perf via task_quality."""
    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_perf_owner")
    assignee_id = await _register_and_login(client, "tp_perf_assignee")
    pid, tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=assignee_id
    )

    await _login(client, "tp_perf_assignee")
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "in_progress"}
    )
    await client.post(
        f"/api/tasks/{tid}/status", json={"new_status": "done"}
    )
    await _login(client, "tp_perf_owner")
    await client.post(
        f"/api/tasks/{tid}/score", json={"quality": "good"}
    )

    r = await client.get(f"/api/projects/{pid}/team/perf")
    assert r.status_code == 200, r.text
    # team_perf returns the list directly, not wrapped in {"members": ...}.
    members = r.json()
    assignee_row = next(m for m in members if m["user_id"] == assignee_id)
    assert assignee_row["task_quality"]["good"] == 1
    assert assignee_row["task_quality"]["total"] == 1
    assert assignee_row["task_quality"]["quality_index"] == 1.0


# ---- M3 — Task Membrane Agent (semantic review) ------------------------


class _StubMembraneReviewer:
    """Stub copy of the M1 fixture from test_kb_items.py — duplicated
    here to keep that module's private helpers private. Returns a
    pre-canned review without calling an LLM and records every packet
    it received so tests can inspect the pretext shape too."""

    def __init__(self, review):
        self._review = review
        self.calls: list[dict] = []

    async def review_candidate(self, packet):
        from dataclasses import dataclass

        from workgraph_agents.llm import LLMResult

        @dataclass
        class _Outcome:
            review: object
            result: LLMResult
            outcome: str
            attempts: int = 1
            error: str | None = None

        self.calls.append(packet)
        return _Outcome(
            review=self._review,
            result=LLMResult(
                content="",
                model="stub",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
            ),
            outcome="ok",
        )


def _make_review(action, **kwargs):
    from workgraph_agents import MembraneAgentReview

    defaults = {
        "reason": "stub_test",
        "diff_summary": None,
        "clarify_question": None,
        "conflict_with": [],
        "warnings": [],
        "confidence": 0.9,
    }
    defaults.update(kwargs)
    return MembraneAgentReview(action=action, **defaults)


async def _seed_personal_task_for_promote(
    maker, *, project_id: str, owner_id: str, title: str, description: str = ""
) -> str:
    """Add a personal-scope task this owner can promote. Reuses the
    project's existing requirement (created by _seed_project_with_task)."""
    tid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            TaskRow(
                id=tid,
                project_id=project_id,
                requirement_id=None,
                owner_user_id=owner_id,
                title=title,
                description=description,
                status="open",
                scope="personal",
                sort_order=0,
            )
        )
    return tid


@pytest.mark.asyncio
async def test_m3_agent_blocks_decision_contradicting_task(api_env):
    """M3 integration: deterministic checks pass (no title dup, no
    budget overflow), but the agent flags a contradiction with a recent
    decision. Promote should defer with deferred=True."""
    from workgraph_api.main import app

    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_m3_a_owner")
    member_id = await _register_and_login(client, "tp_m3_a_member")
    pid, _existing_tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=member_id
    )

    # Seed a recent decision so the pretext has a related_decisions
    # entry to point at. Keywords overlap with the candidate title so
    # the topic-token filter retains it.
    from workgraph_persistence import DecisionRow
    from datetime import datetime, timezone

    decision_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            DecisionRow(
                id=decision_id,
                project_id=pid,
                resolver_id=owner_id,
                custom_text="Cut revive from launch.",
                rationale="Out of scope for the 6-week alpha.",
                created_at=datetime.now(timezone.utc),
            )
        )

    # Member files a personal task whose topic touches the decision.
    member_task_id = await _seed_personal_task_for_promote(
        maker,
        project_id=pid,
        owner_id=member_id,
        title="Implement revive system",
        description="Add revive on player death — 3 charges per run.",
    )

    # Stub: agent flags the contradiction.
    stub_review = _make_review(
        "request_review",
        reason="task_contradicts_recent_decision",
        diff_summary=(
            "Candidate restores revive after the launch-scope decision "
            "cut it. Owner should reconsider supersession explicitly."
        ),
        conflict_with=[f"decision:{decision_id}"],
        confidence=0.88,
    )
    stub = _StubMembraneReviewer(stub_review)
    app.state.membrane_service._agent_reviewer = stub

    await _login(client, "tp_m3_a_member")
    r = await client.post(f"/api/tasks/{member_task_id}/promote")
    assert r.status_code == 200, r.text
    body = r.json()
    # request_review verdict surfaces as deferred=True per task_progress.
    assert body["deferred"] is True, body
    assert body["task"] is None
    # Agent was actually called + saw a related_decisions packet entry.
    assert len(stub.calls) == 1
    packet = stub.calls[0]
    assert packet["candidate"]["kind"] == "task_promote"
    assert packet["candidate"]["title"] == "Implement revive system"
    decision_refs = [d["ref"] for d in packet["recent_decisions"]]
    assert f"decision:{decision_id}" in decision_refs


@pytest.mark.asyncio
async def test_m3_agent_permits_compatible_task(api_env):
    """M3: agent says auto_merge → the task promotes normally and
    lands as scope='plan'."""
    from workgraph_api.main import app

    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_m3_b_owner")
    member_id = await _register_and_login(client, "tp_m3_b_member")
    pid, _existing_tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=member_id
    )

    member_task_id = await _seed_personal_task_for_promote(
        maker,
        project_id=pid,
        owner_id=member_id,
        title="Polish OTP UX",
        description="Tighten the OTP entry flow",
    )

    stub_review = _make_review(
        "auto_merge",
        reason="no_semantic_conflicts",
        confidence=0.78,
    )
    stub = _StubMembraneReviewer(stub_review)
    app.state.membrane_service._agent_reviewer = stub

    await _login(client, "tp_m3_b_member")
    r = await client.post(f"/api/tasks/{member_task_id}/promote")
    assert r.status_code == 200, r.text
    body = r.json()
    # auto_merge — task promoted, response carries the plan task.
    assert body.get("deferred") is not True, body
    assert body["task"] is not None
    assert body["task"]["scope"] == "plan"


@pytest.mark.asyncio
async def test_m3_agent_skipped_when_pretext_empty(api_env):
    """Spec §7: don't burn an LLM call when there's nothing to review
    against (no related tasks, no related decisions). The candidate
    auto-merges via the deterministic path without invoking the agent."""
    from workgraph_api.main import app

    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_m3_c_owner")
    member_id = await _register_and_login(client, "tp_m3_c_member")
    pid, _existing_tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=member_id
    )

    # Personal task whose topic-tokens don't overlap with any plan task
    # or decision in this project. The seeded existing task is "Wire
    # OTP" — pick a wholly unrelated topic.
    member_task_id = await _seed_personal_task_for_promote(
        maker,
        project_id=pid,
        owner_id=member_id,
        title="Submit GDC presentation",
        description="Prepare slides for indie showcase track.",
    )

    # Stub raises if called — we want to assert the agent is NOT called.
    sentinel = _StubMembraneReviewer(
        _make_review("request_review", reason="should_not_fire")
    )
    app.state.membrane_service._agent_reviewer = sentinel

    await _login(client, "tp_m3_c_member")
    r = await client.post(f"/api/tasks/{member_task_id}/promote")
    assert r.status_code == 200, r.text
    body = r.json()
    # Pretext was empty — agent skipped, deterministic auto_merge.
    assert sentinel.calls == [], "agent should be skipped for empty pretext"
    assert body["task"] is not None
    assert body["task"]["scope"] == "plan"


@pytest.mark.asyncio
async def test_m3_agent_invented_ref_dropped_and_review_proceeds(api_env):
    """M1 invariant carried forward: refs the agent invents that don't
    appear in the pretext are dropped silently. Concretely: the agent
    flags `decision:does-not-exist` along with a real `decision:<id>` —
    the invented ref is filtered, the real one survives, the verdict
    still applies."""
    from workgraph_api.main import app
    from workgraph_persistence import DecisionRow
    from datetime import datetime, timezone

    client, maker, *_ = api_env
    owner_id = await _register_and_login(client, "tp_m3_d_owner")
    member_id = await _register_and_login(client, "tp_m3_d_member")
    pid, _existing_tid = await _seed_project_with_task(
        maker, owner_id=owner_id, assignee_id=member_id
    )

    real_decision_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            DecisionRow(
                id=real_decision_id,
                project_id=pid,
                resolver_id=owner_id,
                custom_text="Lock the OTP design.",
                rationale="Avoid late churn.",
                created_at=datetime.now(timezone.utc),
            )
        )

    member_task_id = await _seed_personal_task_for_promote(
        maker,
        project_id=pid,
        owner_id=member_id,
        title="Rewrite OTP design",
        description="Switch OTP from email to push.",
    )

    stub_review = _make_review(
        "request_review",
        reason="contradicts_locked_design",
        diff_summary="Candidate rewrites a design we just locked.",
        conflict_with=[
            f"decision:{real_decision_id}",
            "decision:does-not-exist",
        ],
        confidence=0.9,
    )
    stub = _StubMembraneReviewer(stub_review)
    app.state.membrane_service._agent_reviewer = stub

    await _login(client, "tp_m3_d_member")
    r = await client.post(f"/api/tasks/{member_task_id}/promote")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deferred"] is True
    # The agent saw both refs but only the real one was in the pretext.
    sent_packet = stub.calls[0]
    decision_refs = [d["ref"] for d in sent_packet["recent_decisions"]]
    assert f"decision:{real_decision_id}" in decision_refs
    assert "decision:does-not-exist" not in decision_refs
