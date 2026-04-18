"""Phase 6 Planning Engine — unit + integration tests.

Covers the AC set from PLAN.md Phase 6:
  - PlanningAgent stub synthesizes a valid DAG (≥3 tasks, chain deps, 1 milestone, 1 risk).
  - POST /api/projects/{id}/plan persists tasks + dependencies + milestones.
  - Plan is idempotent per requirement version (second call returns same rows).
  - Orphan-deliverable detection → manual_review outcome (not 500).
  - Cycle detection → manual_review outcome.
  - Unknown task ref in dependency → manual_review outcome.
  - Unknown deliverable ref on task → manual_review outcome.
  - planning.produced event fires with counts + outcome.
  - agent_run_log entry for planning.
  - Stage derives to "planned" after successful plan; plan_counts populated.
  - New risks from the plan append onto the graph (dedup by title).
  - POST /plan with no deliverables (manual_review parse) → 409.
  - POST /plan with unknown project → 404.
  - GET /plan returns persisted shape, empty arrays for missing project.
"""

from __future__ import annotations

import pytest

from workgraph_agents import (
    ParsedPlan,
    PlannedDependency,
    PlannedMilestone,
    PlannedRisk,
    PlannedTask,
)
from workgraph_agents.testing import (
    StubPlanningAgent,
    StubRequirementAgent,
)
from workgraph_persistence import (
    AgentRunLogRepository,
    EventRepository,
    PlanRepository,
    ProjectGraphRepository,
    RequirementRepository,
    project_stage,
    session_scope,
)

from workgraph_api.services import IntakeService, PlanningService


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _intake_once(client, *, source_event_id: str = "plan-setup") -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": source_event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


def _swap_planning(client, maker, bus, plan_agent: StubPlanningAgent) -> None:
    """Replace the api_env-bound PlanningService with one using a custom agent."""
    client._transport.app.state.planning_agent = plan_agent
    client._transport.app.state.planning_service = PlanningService(
        maker, bus, agent=plan_agent
    )


# ---------- happy path: stub plan is valid --------------------------------


@pytest.mark.asyncio
async def test_plan_produces_dag_and_persists(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200, r.text
    body = r.json()

    # StubPlanningAgent synthesizes 1 task per deliverable + OTP = 3 tasks
    # when the default StubRequirementAgent emits 2 deliverables.
    assert body["outcome"] == "ok"
    assert body["regenerated"] is True
    assert len(body["tasks"]) == 3
    assert len(body["dependencies"]) == 2  # chain T1 → T2 → OTP
    assert len(body["milestones"]) == 1
    # Dependency endpoints resolve to real task ids.
    task_ids = {t["id"] for t in body["tasks"]}
    for d in body["dependencies"]:
        assert d["from_task_id"] in task_ids
        assert d["to_task_id"] in task_ids

    # Acceptance criteria on every task.
    for t in body["tasks"]:
        assert t["acceptance_criteria"]

    # Backend + frontend roles distributed (AC: backend+frontend+OTP in the plan).
    roles = {t["assignee_role"] for t in body["tasks"]}
    assert "backend" in roles
    # And at least one task ties to a deliverable (OTP is null-deliverable).
    assert any(t["deliverable_id"] is not None for t in body["tasks"])


@pytest.mark.asyncio
async def test_plan_is_idempotent(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    first = await client.post(f"/api/projects/{project_id}/plan")
    assert first.status_code == 200
    second = await client.post(f"/api/projects/{project_id}/plan")
    assert second.status_code == 200

    assert second.json()["regenerated"] is False
    assert [t["id"] for t in first.json()["tasks"]] == [
        t["id"] for t in second.json()["tasks"]
    ]


@pytest.mark.asyncio
async def test_plan_persists_to_db(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200

    async with session_scope(maker) as session:
        latest = await RequirementRepository(session).latest_for_project(project_id)
        rows = await PlanRepository(session).list_all(latest.id)

    assert len(rows["tasks"]) == 3
    assert len(rows["dependencies"]) == 2
    assert len(rows["milestones"]) == 1
    # sort_order monotonic on tasks.
    assert [t.sort_order for t in rows["tasks"]] == [0, 1, 2]


# ---------- stage derivation ---------------------------------------------


@pytest.mark.asyncio
async def test_stage_flips_to_planned_after_plan(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    async with session_scope(maker) as session:
        before = await project_stage(session, project_id)
    assert before.stage == "ready_for_planning"
    assert before.plan_counts == {"tasks": 0, "dependencies": 0, "milestones": 0}

    await client.post(f"/api/projects/{project_id}/plan")

    async with session_scope(maker) as session:
        after = await project_stage(session, project_id)
    assert after.stage == "planned"
    assert after.plan_counts["tasks"] == 3
    assert after.plan_counts["dependencies"] == 2
    assert after.plan_counts["milestones"] == 1


# ---------- events + agent_run_log ---------------------------------------


@pytest.mark.asyncio
async def test_planning_produced_event_fires(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    await client.post(f"/api/projects/{project_id}/plan")

    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("planning.produced")

    assert len(events) == 1
    p = events[0].payload
    assert p["project_id"] == project_id
    assert p["outcome"] == "ok"
    assert p["task_count"] == 3
    assert p["dependency_count"] == 2
    assert p["milestone_count"] == 1
    assert p["prompt_version"].startswith("stub.planning")
    assert events[0].trace_id  # ContextVar pulled through EventBus


@pytest.mark.asyncio
async def test_agent_run_log_written_for_planning(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    await client.post(f"/api/projects/{project_id}/plan")

    async with session_scope(maker) as session:
        planning_entries = await AgentRunLogRepository(session).list_for_agent(
            "planning"
        )
    planning_entries = [e for e in planning_entries if e.project_id == project_id]
    assert len(planning_entries) == 1
    entry = planning_entries[0]
    assert entry.outcome == "ok"
    assert entry.attempts == 1
    assert entry.prompt_version.startswith("stub.planning")


# ---------- validation: orphan deliverable -------------------------------


@pytest.mark.asyncio
async def test_plan_with_uncovered_deliverable_becomes_manual_review(api_env):
    client, maker, bus, _, _, _ = api_env
    project_id = await _intake_once(client)

    # Plan that covers only one deliverable → the other is orphaned.
    bad_plan = ParsedPlan(
        tasks=[
            PlannedTask(
                ref="T1",
                title="Build one",
                description="",
                deliverable_ref="PLACEHOLDER-1",
                assignee_role="backend",
                estimate_hours=4,
                acceptance_criteria=["done"],
            )
        ],
        dependencies=[],
        milestones=[],
        risks=[],
    )

    # Fetch the real deliverable IDs to craft a plan that covers only the first.
    # We need to set deliverable_ref to something valid but miss one.
    # Simpler: use a FakePlanAgent that fixes up the ref at call time.
    class FixupAgent(StubPlanningAgent):
        async def plan(self, *, goal, deliverables, constraints, existing_risks=None):
            # Only cover the first deliverable.
            self._plan = ParsedPlan(
                tasks=[
                    PlannedTask(
                        ref="T1",
                        title="Build first",
                        description="",
                        deliverable_ref=deliverables[0]["id"],
                        assignee_role="backend",
                        estimate_hours=4,
                        acceptance_criteria=["done"],
                    )
                ],
                dependencies=[],
                milestones=[],
                risks=[],
            )
            return await super().plan(
                goal=goal,
                deliverables=deliverables,
                constraints=constraints,
                existing_risks=existing_risks,
            )

    _swap_planning(client, maker, bus, FixupAgent())

    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "manual_review"
    assert "uncovered_deliverable" in body["error"]
    assert body["tasks"] == []


# ---------- validation: cycle --------------------------------------------


@pytest.mark.asyncio
async def test_plan_with_cycle_becomes_manual_review(api_env):
    client, maker, bus, _, _, _ = api_env
    project_id = await _intake_once(client)

    class CyclicAgent(StubPlanningAgent):
        async def plan(self, *, goal, deliverables, constraints, existing_risks=None):
            self._plan = ParsedPlan(
                tasks=[
                    PlannedTask(
                        ref=f"T{i + 1}",
                        title=f"Task {i + 1}",
                        description="",
                        deliverable_ref=deliverables[i]["id"]
                        if i < len(deliverables) else None,
                        assignee_role="backend",
                        estimate_hours=4,
                        acceptance_criteria=["done"],
                    )
                    for i in range(len(deliverables))
                ],
                # Cycle: T1 → T2 → T1.
                dependencies=[
                    PlannedDependency.model_validate({"from": "T1", "to": "T2"}),
                    PlannedDependency.model_validate({"from": "T2", "to": "T1"}),
                ],
                milestones=[],
                risks=[],
            )
            return await super().plan(
                goal=goal,
                deliverables=deliverables,
                constraints=constraints,
                existing_risks=existing_risks,
            )

    _swap_planning(client, maker, bus, CyclicAgent())

    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "manual_review"
    assert "cycle" in body["error"]


# ---------- validation: unknown task ref in dependency --------------------


@pytest.mark.asyncio
async def test_plan_with_dangling_dep_becomes_manual_review(api_env):
    client, maker, bus, _, _, _ = api_env
    project_id = await _intake_once(client)

    class DanglingDepAgent(StubPlanningAgent):
        async def plan(self, *, goal, deliverables, constraints, existing_risks=None):
            self._plan = ParsedPlan(
                tasks=[
                    PlannedTask(
                        ref=f"T{i + 1}",
                        title=f"Task {i + 1}",
                        description="",
                        deliverable_ref=deliverables[i]["id"],
                        assignee_role="backend",
                        estimate_hours=4,
                        acceptance_criteria=["done"],
                    )
                    for i in range(len(deliverables))
                ],
                dependencies=[
                    PlannedDependency.model_validate({"from": "T1", "to": "T99"}),
                ],
                milestones=[],
                risks=[],
            )
            return await super().plan(
                goal=goal,
                deliverables=deliverables,
                constraints=constraints,
                existing_risks=existing_risks,
            )

    _swap_planning(client, maker, bus, DanglingDepAgent())

    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "manual_review"
    assert "unknown_task_ref" in body["error"]


# ---------- validation: unknown deliverable ref on task -------------------


@pytest.mark.asyncio
async def test_plan_with_unknown_deliverable_ref_becomes_manual_review(api_env):
    client, maker, bus, _, _, _ = api_env
    project_id = await _intake_once(client)

    class UnknownDeliverableAgent(StubPlanningAgent):
        async def plan(self, *, goal, deliverables, constraints, existing_risks=None):
            self._plan = ParsedPlan(
                tasks=[
                    PlannedTask(
                        ref="T1",
                        title="Task pointing at nothing",
                        description="",
                        deliverable_ref="does-not-exist",
                        assignee_role="backend",
                        estimate_hours=4,
                        acceptance_criteria=["done"],
                    )
                ],
                dependencies=[],
                milestones=[],
                risks=[],
            )
            return await super().plan(
                goal=goal,
                deliverables=deliverables,
                constraints=constraints,
                existing_risks=existing_risks,
            )

    _swap_planning(client, maker, bus, UnknownDeliverableAgent())

    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "manual_review"
    assert "unknown_deliverable" in body["error"]


# ---------- new risks appended ------------------------------------------


@pytest.mark.asyncio
async def test_plan_new_risks_append_to_graph(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200
    body = r.json()

    # StubPlanningAgent default adds one "Stub risk" — Phase 5 graph carried
    # none (StubRequirementAgent.default yields no risks), so it appends.
    assert len(body["risks_added"]) == 1
    assert body["risks_added"][0]["title"] == "Stub risk"

    async with session_scope(maker) as session:
        latest = await RequirementRepository(session).latest_for_project(project_id)
        risks = await ProjectGraphRepository(session).list_risks(latest.id)
    assert any(r.title == "Stub risk" for r in risks)


# ---------- manual_review parse → 409 NotReadyForPlanning -----------------


@pytest.mark.asyncio
async def test_plan_when_parse_manual_review_returns_409(api_env):
    client, maker, bus, _, _, _ = api_env

    # Force intake into manual_review — graph_builder skips, no deliverables.
    mr_agent = StubRequirementAgent(outcome="manual_review", attempts=3)
    client._transport.app.state.intake_service = IntakeService(
        maker, bus, agent=mr_agent
    )

    r = await client.post(
        "/api/intake/message",
        json={"text": "too short to plan", "source_event_id": "plan-mr"},
    )
    assert r.status_code == 200
    project_id = r.json()["project"]["id"]

    plan_r = await client.post(f"/api/projects/{project_id}/plan")
    assert plan_r.status_code == 409
    assert "no deliverables" in plan_r.json()["message"].lower()


# ---------- unknown project → 404 ----------------------------------------


@pytest.mark.asyncio
async def test_plan_unknown_project_returns_404(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.post("/api/projects/no-such-project/plan")
    assert r.status_code == 404


# ---------- GET /plan endpoint -------------------------------------------


@pytest.mark.asyncio
async def test_get_plan_returns_persisted_shape(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    # Empty plan before POST.
    r = await client.get(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200
    assert r.json()["tasks"] == []
    assert r.json()["dependencies"] == []

    await client.post(f"/api/projects/{project_id}/plan")

    r = await client.get(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200
    body = r.json()
    assert len(body["tasks"]) == 3
    assert len(body["dependencies"]) == 2
    assert body["requirement_version"] == 1


@pytest.mark.asyncio
async def test_get_plan_unknown_project_404(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.get("/api/projects/nope/plan")
    assert r.status_code == 404


# ---------- v+1 promotion gets its own plan ------------------------------


@pytest.mark.asyncio
async def test_v2_gets_its_own_plan_slot(api_env):
    """After clarify-reply promotes the requirement to v2, a new plan call
    produces a fresh plan tied to v2 (history of v1 plan stays intact)."""
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client, source_event_id="plan-v2")

    # Plan v1.
    v1_plan = (await client.post(f"/api/projects/{project_id}/plan")).json()
    assert v1_plan["requirement_version"] == 1

    # Promote to v2 via clarify-reply.
    clar = await client.post(f"/api/projects/{project_id}/clarify")
    for q in clar.json()["questions"]:
        await client.post(
            f"/api/projects/{project_id}/clarify-reply",
            json={"question_id": q["id"], "answer": "yes"},
        )

    # Plan v2 — new rows.
    v2_plan = (await client.post(f"/api/projects/{project_id}/plan")).json()
    assert v2_plan["requirement_version"] == 2
    assert v2_plan["regenerated"] is True

    v1_task_ids = {t["id"] for t in v1_plan["tasks"]}
    v2_task_ids = {t["id"] for t in v2_plan["tasks"]}
    assert v1_task_ids.isdisjoint(v2_task_ids)
