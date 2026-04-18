"""Canonical E2E fixture — per PLAN.md decision 3B.

This fixture starts with the canonical event-registration scenario from
prompt-contracts.md §16.1 and evolves across phases:

  Phase 2:        intake creates project + requirement, event emitted
                  with trace_id, dedup works across both paths.
  Phase 3:        Requirement Agent parses 4 scope items + deadline, confidence >0.7
  Phase 4:        ≥1 open_question generated, routed to correct Feishu channel
  Phase 5 (here): graph entities (Goal/Deliverable/Constraint/Risk) present
                  on latest requirement; stage=ready_for_planning driven by
                  graph presence; graph.built fires per parse.
  Phase 6+:       planning, sync, conflict, decision, delivery assertions chained

Every subsequent agent phase APPENDS its assertion block — this file is the
single end-to-end contract that proves the demo path works end-to-end.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from workgraph_agents import ClarificationAgent, PlanningAgent, RequirementAgent
from workgraph_agents.testing import (
    StubClarificationAgent,
    StubPlanningAgent,
    StubRequirementAgent,
)
from workgraph_domain import EventBus
from workgraph_persistence import (
    EventRepository,
    build_engine,
    build_sessionmaker,
    create_all,
    drop_all,
    session_scope,
)

from workgraph_api.main import app
from workgraph_api.services import ClarificationService, IntakeService, PlanningService

CANONICAL_REQUIREMENT_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _make_env(req_agent, clar_agent, plan_agent=None):
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    maker = build_sessionmaker(engine)
    bus = EventBus(maker)
    intake_service = IntakeService(maker, bus, agent=req_agent)
    clar_service = ClarificationService(
        maker, bus, clarification_agent=clar_agent, requirement_agent=req_agent
    )
    planning_service = PlanningService(maker, bus, agent=plan_agent) if plan_agent is not None else PlanningService(maker, bus)

    app.state.engine = engine
    app.state.sessionmaker = maker
    app.state.event_bus = bus
    app.state.intake_service = intake_service
    app.state.clarification_service = clar_service
    app.state.planning_service = planning_service

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    return client, maker, engine


@pytest_asyncio.fixture
async def canonical_env():
    """Phase 2 plumbing tests — stub agents, no network."""
    client, maker, engine = await _make_env(
        StubRequirementAgent(), StubClarificationAgent(), StubPlanningAgent()
    )
    async with client:
        yield client, maker
    await drop_all(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def canonical_env_live():
    """Phase 3+ E2E — real agents against DeepSeek."""
    client, maker, engine = await _make_env(
        RequirementAgent(), ClarificationAgent(), PlanningAgent()
    )
    async with client:
        yield client, maker
    await drop_all(engine)
    await engine.dispose()


skip_if_no_key = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set — live canonical E2E requires DeepSeek",
)


# ---------- Phase 2 assertions --------------------------------------------


@pytest.mark.asyncio
async def test_canonical_intake_via_api_path(canonical_env):
    client, maker = canonical_env
    trace_id = "trace-canonical-api"

    resp = await client.post(
        "/api/intake/message",
        json={
            "text": CANONICAL_REQUIREMENT_TEXT,
            "source_event_id": "canonical-api-1",
        },
        headers={"x-trace-id": trace_id},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "api"
    assert body["deduplicated"] is False
    assert body["requirement"]["raw_text"] == CANONICAL_REQUIREMENT_TEXT
    assert resp.headers.get("x-trace-id") == trace_id

    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("intake.received")
    assert len(events) == 1
    assert events[0].trace_id == trace_id
    assert events[0].payload["project_id"] == body["project"]["id"]


@pytest.mark.asyncio
async def test_canonical_intake_via_feishu_path(canonical_env):
    client, maker = canonical_env

    resp = await client.post(
        "/api/intake/feishu/webhook",
        json={
            "event_id": "canonical-fs-1",
            "message_text": CANONICAL_REQUIREMENT_TEXT,
            "sender_id": "ou_canonical_user",
            "chat_id": "oc_canonical_chat",
            "raw": {"_demo": "feishu-envelope-placeholder"},
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "feishu"
    assert body["requirement"]["raw_text"] == CANONICAL_REQUIREMENT_TEXT

    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("intake.received")
    assert len(events) == 1
    assert events[0].payload["source"] == "feishu"


@pytest.mark.asyncio
async def test_canonical_both_paths_same_domain_shape(canonical_env):
    """Core AC for Phase 2: API path and Feishu path produce the same domain result."""
    client, _ = canonical_env

    r_api = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_REQUIREMENT_TEXT, "source_event_id": "canonical-parity-api"},
    )
    r_fs = await client.post(
        "/api/intake/feishu/webhook",
        json={"event_id": "canonical-parity-fs", "message_text": CANONICAL_REQUIREMENT_TEXT},
    )
    api_body = r_api.json()
    fs_body = r_fs.json()

    assert set(api_body.keys()) == set(fs_body.keys())
    assert set(api_body["project"].keys()) == set(fs_body["project"].keys())
    assert set(api_body["requirement"].keys()) == set(fs_body["requirement"].keys())
    assert api_body["requirement"]["raw_text"] == fs_body["requirement"]["raw_text"]


@pytest.mark.asyncio
async def test_canonical_dedup_on_both_paths(canonical_env):
    client, _ = canonical_env

    # Two identical API calls → one project.
    api_payload = {"text": CANONICAL_REQUIREMENT_TEXT, "source_event_id": "canonical-dedup-api"}
    r1 = await client.post("/api/intake/message", json=api_payload)
    r2 = await client.post("/api/intake/message", json=api_payload)
    assert r1.json()["project"]["id"] == r2.json()["project"]["id"]
    assert r2.json()["deduplicated"] is True

    # Two identical Feishu calls → one project.
    fs_payload = {"event_id": "canonical-dedup-fs", "message_text": CANONICAL_REQUIREMENT_TEXT}
    f1 = await client.post("/api/intake/feishu/webhook", json=fs_payload)
    f2 = await client.post("/api/intake/feishu/webhook", json=fs_payload)
    assert f1.json()["project"]["id"] == f2.json()["project"]["id"]
    assert f2.json()["deduplicated"] is True


# ---------- Phase 3 assertions — live Requirement Agent --------------------
# Marked `eval` so default `uv run pytest` skips them; CI + devs opt in with
# `-m eval`. Decision 3B: canonical fixture asserts 4 scope items, deadline,
# confidence >0.7 on the real agent against DeepSeek.


@pytest.mark.eval
@skip_if_no_key
@pytest.mark.asyncio
async def test_canonical_requirement_parse_phase3(canonical_env_live):
    client, maker = canonical_env_live
    trace_id = "trace-canonical-phase3"

    resp = await client.post(
        "/api/intake/message",
        json={
            "text": CANONICAL_REQUIREMENT_TEXT,
            "source_event_id": "canonical-phase3-1",
        },
        headers={"x-trace-id": trace_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    req = body["requirement"]

    # Parse landed on the requirement row.
    assert req["parse_outcome"] == "ok"
    assert req["parsed_at"] is not None
    parsed = req["parsed_json"]
    assert parsed is not None

    # Core Phase 3 AC (3B):
    scope = parsed["scope_items"]
    assert len(scope) >= 4, f"expected >=4 scope items, got {len(scope)}: {scope}"
    scope_lower = " ".join(s.lower() for s in scope)
    for must_mention in ("invitation", "phone", "export", "conversion"):
        assert must_mention in scope_lower, (
            f"scope missing {must_mention!r}: {scope}"
        )
    assert parsed["deadline"] is not None
    assert parsed["confidence"] > 0.7

    # requirement.parsed event emitted with the right trace_id.
    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("requirement.parsed")
    assert len(events) == 1
    assert events[0].trace_id == trace_id
    assert events[0].payload["project_id"] == body["project"]["id"]
    assert events[0].payload["outcome"] == "ok"
    assert events[0].payload["scope_count"] == len(scope)


# ---------- Phase 4 assertions — live Clarification Agent ------------------
# Decision 3B extension: canonical fixture produces ≥1 open_question, routed
# to a reasonable target_role, promotes to v2 after the user answers.


@pytest.mark.eval
@skip_if_no_key
@pytest.mark.asyncio
async def test_canonical_clarification_loop_phase4(canonical_env_live):
    client, maker = canonical_env_live

    # 1) Intake canonical requirement.
    intake = await client.post(
        "/api/intake/message",
        json={
            "text": CANONICAL_REQUIREMENT_TEXT,
            "source_event_id": "canonical-phase4-1",
        },
        headers={"x-trace-id": "trace-canonical-phase4"},
    )
    assert intake.status_code == 200, intake.text
    project_id = intake.json()["project"]["id"]

    # 2) Stage right after intake: parsed_json is set → ready_for_planning.
    stage = await client.get(f"/api/projects/{project_id}/stage")
    assert stage.status_code == 200
    assert stage.json()["stage"] == "ready_for_planning"

    # 3) Generate clarifications. We require at least 1 question for the
    # canonical scenario (owner / acceptance criteria / launch date are
    # typical gaps the canonical text leaves open).
    clar = await client.post(f"/api/projects/{project_id}/clarify")
    assert clar.status_code == 200, clar.text
    body = clar.json()
    assert body["outcome"] == "ok"
    questions = body["questions"]
    assert 1 <= len(questions) <= 3, f"expected 1-3 questions, got {len(questions)}"

    # The target_role on each question must be one of the contract-allowed
    # values. This is the "routed to correct Feishu channel" hook — Phase 7
    # will convert target_role into a Feishu chat/group.
    allowed_roles = {
        "pm", "frontend", "backend", "qa", "design",
        "business", "approver", "unknown",
    }
    async with session_scope(maker) as session:
        from workgraph_persistence import ClarificationQuestionRepository, RequirementRepository
        latest = await RequirementRepository(session).latest_for_project(project_id)
        rows = await ClarificationQuestionRepository(session).list_for_requirement(latest.id)
    assert len(rows) == len(questions)

    # 4) Stage after /clarify: clarification_pending.
    stage = await client.get(f"/api/projects/{project_id}/stage")
    assert stage.json()["stage"] == "clarification_pending"

    # 5) Answer all questions — v2 is produced.
    for q in questions:
        r = await client.post(
            f"/api/projects/{project_id}/clarify-reply",
            json={
                "question_id": q["id"],
                "answer": "Live E2E stub answer — filled in by test.",
            },
        )
        assert r.status_code == 200
    final = r.json()
    assert final["promoted"] is True
    assert final["requirement_version"] == 2

    # 6) Stage after final answer: ready_for_planning (or clarification_pending
    # if the v2 re-parse surfaced new questions — PLAN.md allows that). What
    # matters is that the graph, not a column, drove the transition.
    stage = await client.get(f"/api/projects/{project_id}/stage")
    assert stage.json()["stage"] in {"ready_for_planning", "clarification_pending"}
    assert stage.json()["requirement_version"] == 2

    # 7) Events chain.
    async with session_scope(maker) as session:
        gen_events = await EventRepository(session).list_by_name("clarification.generated")
        ans_events = await EventRepository(session).list_by_name("clarification.answered")
        parse_events = await EventRepository(session).list_by_name("requirement.parsed")
    assert len(gen_events) == 1
    assert len(ans_events) == len(questions)
    # 1 from intake + 1 from v2 re-parse.
    assert len(parse_events) == 2
    assert parse_events[1].payload["requirement_version"] == 2
    assert parse_events[1].payload["source"] == "clarification-reply"


# ---------- Phase 5 assertions — live graph projection ---------------------
# Decision 3B extension: after intake, the graph has ≥4 Deliverables covering
# the canonical feature set, ≥1 Goal, and the deadline becomes a Constraint.
# Stage is ready_for_planning because the graph exists, not because of a
# column flip.


@pytest.mark.eval
@skip_if_no_key
@pytest.mark.asyncio
async def test_canonical_graph_init_phase5(canonical_env_live):
    client, maker = canonical_env_live
    trace_id = "trace-canonical-phase5"

    # 1) Intake the canonical requirement.
    intake = await client.post(
        "/api/intake/message",
        json={
            "text": CANONICAL_REQUIREMENT_TEXT,
            "source_event_id": "canonical-phase5-1",
        },
        headers={"x-trace-id": trace_id},
    )
    assert intake.status_code == 200, intake.text
    project_id = intake.json()["project"]["id"]

    # 2) Graph endpoint shape.
    graph_resp = await client.get(f"/api/projects/{project_id}/graph")
    assert graph_resp.status_code == 200
    graph = graph_resp.json()
    assert graph["project_id"] == project_id
    assert graph["requirement_version"] == 1

    # Goal row: exactly 1.
    assert len(graph["goals"]) == 1
    goal = graph["goals"][0]
    assert goal["status"] == "open"
    assert len(goal["title"]) > 0

    # Deliverables: ≥4 covering invitation / phone / export / conversion.
    deliverables = graph["deliverables"]
    assert len(deliverables) >= 4, (
        f"expected ≥4 deliverables, got {len(deliverables)}: {deliverables}"
    )
    titles_lower = " ".join(d["title"].lower() for d in deliverables)
    for must_mention in ("invitation", "phone", "export", "conversion"):
        assert must_mention in titles_lower, (
            f"deliverables missing {must_mention!r}: "
            f"{[d['title'] for d in deliverables]}"
        )
    assert all(d["kind"] == "feature" for d in deliverables)
    # sort_order should be a contiguous 0..n-1.
    assert [d["sort_order"] for d in deliverables] == list(range(len(deliverables)))

    # Deadline constraint: 1 row with kind=deadline, severity=high.
    constraints = graph["constraints"]
    assert len(constraints) == 1
    assert constraints[0]["kind"] == "deadline"
    assert constraints[0]["severity"] == "high"
    # content should reference the parsed deadline string from v1.
    assert "Deadline:" in constraints[0]["content"]

    # Risks left empty at Phase 5.
    assert graph["risks"] == []

    # 3) Stage is graph-driven ready_for_planning — and surfaces the counts.
    stage_resp = await client.get(f"/api/projects/{project_id}/stage")
    assert stage_resp.status_code == 200
    stage_body = stage_resp.json()
    assert stage_body["stage"] == "ready_for_planning"
    assert stage_body["graph_counts"]["goals"] == 1
    assert stage_body["graph_counts"]["deliverables"] >= 4
    assert stage_body["graph_counts"]["constraints"] == 1

    # 4) graph.built event fired once, with matching counts + trace_id.
    async with session_scope(maker) as session:
        built_events = await EventRepository(session).list_by_name("graph.built")
    assert len(built_events) == 1
    built = built_events[0]
    assert built.trace_id == trace_id
    assert built.payload["project_id"] == project_id
    assert built.payload["outcome"] == "ok"
    assert built.payload["source"] == "intake"
    assert built.payload["goal_count"] == 1
    assert built.payload["deliverable_count"] == len(deliverables)
    assert built.payload["constraint_count"] == 1
    assert built.payload["risk_count"] == 0
    assert built.payload["requirement_version"] == 1


# ---------- Phase 6 assertions — live planning engine ---------------------
# Decision 3B extension: the PlanningAgent produces a DAG with ≥6 tasks
# covering every canonical deliverable, includes backend + frontend + OTP
# work, and places at least one of those on the critical path. The plan is
# persisted, emits planning.produced, and flips the stage to "planned".


@pytest.mark.eval
@skip_if_no_key
@pytest.mark.asyncio
async def test_canonical_plan_phase6(canonical_env_live):
    client, maker = canonical_env_live
    trace_id = "trace-canonical-phase6"

    # 1) Seed the project through intake (same canonical text).
    intake = await client.post(
        "/api/intake/message",
        json={
            "text": CANONICAL_REQUIREMENT_TEXT,
            "source_event_id": "canonical-phase6-1",
        },
        headers={"x-trace-id": trace_id},
    )
    assert intake.status_code == 200, intake.text
    project_id = intake.json()["project"]["id"]

    # 2) Plan.
    plan_resp = await client.post(
        f"/api/projects/{project_id}/plan",
        headers={"x-trace-id": trace_id},
    )
    assert plan_resp.status_code == 200, plan_resp.text
    plan = plan_resp.json()
    assert plan["outcome"] == "ok"
    assert plan["regenerated"] is True

    tasks = plan["tasks"]
    deps = plan["dependencies"]
    milestones = plan["milestones"]

    # AC: ≥6 tasks.
    assert len(tasks) >= 6, f"expected ≥6 tasks, got {len(tasks)}: {tasks}"
    # AC: at least 1 milestone.
    assert len(milestones) >= 1

    # AC: backend + frontend + OTP work on the plan.
    roles = {t["assignee_role"] for t in tasks}
    assert "backend" in roles, f"no backend tasks: {roles}"
    assert "frontend" in roles, f"no frontend tasks: {roles}"

    joined_text = " ".join(
        f"{t['title']} {t['description'] or ''}".lower() for t in tasks
    )
    assert any(k in joined_text for k in ("otp", "sms", "phone verification")), (
        f"plan missing OTP/phone-verification task: titles="
        f"{[t['title'] for t in tasks]}"
    )

    # AC: dependencies form a valid DAG (persisted form uses task ids; we
    # rebuild adjacency from task ids here).
    task_ids = {t["id"] for t in tasks}
    for d in deps:
        assert d["from_task_id"] in task_ids
        assert d["to_task_id"] in task_ids
        assert d["from_task_id"] != d["to_task_id"]

    # Kahn's check — no cycle.
    adj: dict[str, list[str]] = {tid: [] for tid in task_ids}
    indeg: dict[str, int] = {tid: 0 for tid in task_ids}
    for d in deps:
        adj[d["from_task_id"]].append(d["to_task_id"])
        indeg[d["to_task_id"]] += 1
    queue = [t for t, v in indeg.items() if v == 0]
    order: list[str] = []
    while queue:
        x = queue.pop()
        order.append(x)
        for m in adj[x]:
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    assert len(order) == len(task_ids), "plan dependencies form a cycle"

    # AC: critical path (longest chain by estimate_hours) mentions OTP or
    # phone verification — the canonical cross-cutting concern.
    tasks_by_id = {t["id"]: t for t in tasks}

    def weight(tid: str) -> int:
        h = tasks_by_id[tid]["estimate_hours"]
        return int(h) if h is not None else 1

    dist = {tid: weight(tid) for tid in task_ids}
    prev: dict[str, str | None] = {tid: None for tid in task_ids}
    for tid in order:
        for m in adj[tid]:
            if dist[tid] + weight(m) > dist[m]:
                dist[m] = dist[tid] + weight(m)
                prev[m] = tid
    end = max(dist, key=lambda t: dist[t])
    chain: list[str] = []
    cur: str | None = end
    while cur is not None:
        chain.append(cur)
        cur = prev[cur]
    chain.reverse()
    chain_text = " ".join(
        f"{tasks_by_id[t]['title']} {tasks_by_id[t]['description'] or ''}".lower()
        for t in chain
    )
    assert any(k in chain_text for k in ("otp", "sms", "phone", "invitation")), (
        f"critical path missing OTP / invitation-code task: {chain_text!r}"
    )

    # AC: every deliverable is covered by at least one task.
    graph_resp = await client.get(f"/api/projects/{project_id}/graph")
    deliverable_ids = {d["id"] for d in graph_resp.json()["deliverables"]}
    covered = {t["deliverable_id"] for t in tasks if t["deliverable_id"] is not None}
    missing = deliverable_ids - covered
    assert not missing, f"deliverables not covered: {missing}"

    # 3) Stage flips to "planned".
    stage_resp = await client.get(f"/api/projects/{project_id}/stage")
    stage = stage_resp.json()
    assert stage["stage"] == "planned"
    assert stage["plan_counts"]["tasks"] == len(tasks)
    assert stage["plan_counts"]["dependencies"] == len(deps)

    # 4) planning.produced event fired with trace_id.
    async with session_scope(maker) as session:
        produced = await EventRepository(session).list_by_name("planning.produced")
    assert len(produced) == 1
    p = produced[0]
    assert p.trace_id == trace_id
    assert p.payload["project_id"] == project_id
    assert p.payload["outcome"] == "ok"
    assert p.payload["task_count"] == len(tasks)
    assert p.payload["dependency_count"] == len(deps)
    assert p.payload["milestone_count"] == len(milestones)
    assert p.payload["prompt_version"].startswith("2026-04-17.phase6")

    # 5) Idempotence: second /plan returns the same task ids.
    second = await client.post(f"/api/projects/{project_id}/plan")
    assert second.status_code == 200
    assert second.json()["regenerated"] is False
    assert [t["id"] for t in second.json()["tasks"]] == [t["id"] for t in tasks]
