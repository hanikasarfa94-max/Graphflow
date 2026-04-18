"""Phase 4 Clarification Loop — unit + integration tests.

Covers the AC set from PLAN.md Phase 4:
  - question-count cap (max 3, prefer high-blocking)
  - answer merge → v+1 requirement with a fresh re-parse
  - stage transition (1E: derived from graph, not column)
  - regeneration idempotence (second /clarify returns same rows)
  - clarification.generated + clarification.answered events
  - agent_run_log entries for both agents
"""

from __future__ import annotations

import pytest

from workgraph_agents import (
    ClarificationQuestionItem,
    ParsedRequirement,
)
from workgraph_agents.testing import (
    StubClarificationAgent,
    StubRequirementAgent,
)
from workgraph_persistence import (
    AgentRunLogRepository,
    ClarificationQuestionRepository,
    EventRepository,
    RequirementRepository,
    project_stage,
    session_scope,
)

from workgraph_api.services import ClarificationService, IntakeService


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _intake_once(client) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": "clarify-setup"},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


# ---------- question-cap + persistence ------------------------------------


@pytest.mark.asyncio
async def test_clarify_persists_questions_and_emits_event(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    r = await client.post(f"/api/projects/{project_id}/clarify")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == project_id
    assert body["regenerated"] is True
    assert 0 < len(body["questions"]) <= 3
    for q in body["questions"]:
        assert q["question"]
        assert q["answer"] is None

    async with session_scope(maker) as session:
        # Event emitted exactly once.
        events = await EventRepository(session).list_by_name("clarification.generated")
        assert len(events) == 1
        assert events[0].payload["project_id"] == project_id
        assert events[0].payload["question_count"] == len(body["questions"])

        # agent_run_log row exists for the clarification agent.
        rows = await AgentRunLogRepository(session).list_for_agent("clarification")
        assert len(rows) == 1
        assert rows[0].outcome == "ok"
        assert rows[0].prompt_version == "stub.clarification.v1"


@pytest.mark.asyncio
async def test_clarify_is_idempotent(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    first = await client.post(f"/api/projects/{project_id}/clarify")
    assert first.status_code == 200
    ids_first = [q["id"] for q in first.json()["questions"]]

    second = await client.post(f"/api/projects/{project_id}/clarify")
    assert second.status_code == 200
    body2 = second.json()
    assert body2["regenerated"] is False
    ids_second = [q["id"] for q in body2["questions"]]
    assert ids_first == ids_second, "idempotence: same IDs on repeat call"


@pytest.mark.asyncio
async def test_clarify_enforces_three_question_cap():
    """Direct agent test — hand the agent 5 questions, prove cap is 3."""
    chatty = StubClarificationAgent(
        questions=[
            ClarificationQuestionItem(question="q1", blocking_level="low"),
            ClarificationQuestionItem(question="q2", blocking_level="high"),
            ClarificationQuestionItem(question="q3", blocking_level="medium"),
            ClarificationQuestionItem(question="q4", blocking_level="high"),
            ClarificationQuestionItem(question="q5", blocking_level="low"),
        ]
    )
    parsed = ParsedRequirement(
        goal="x", scope_items=[], deadline=None, open_questions=[], confidence=0.5
    )
    outcome = await chatty.generate(raw_text="x", parsed=parsed)
    # Stub itself passes through — cap enforcement is in ClarificationBatch.
    # The real agent calls complete_structured → Pydantic validator → cap.
    # Validate the cap directly through the Pydantic model:
    from workgraph_agents import ClarificationBatch

    capped = ClarificationBatch(questions=outcome.batch.questions)
    assert len(capped.questions) == 3
    assert [q.blocking_level for q in capped.questions] == ["high", "high", "medium"]


@pytest.mark.asyncio
async def test_clarify_rejects_unknown_project(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.post("/api/projects/does-not-exist/clarify")
    assert r.status_code == 404


# ---------- answer-merge → v+1 --------------------------------------------


@pytest.mark.asyncio
async def test_answer_all_promotes_to_v2(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    gen = await client.post(f"/api/projects/{project_id}/clarify")
    assert gen.status_code == 200
    questions = gen.json()["questions"]
    assert len(questions) >= 2

    # Answer all but the last — still in clarification state, no promotion.
    for q in questions[:-1]:
        r = await client.post(
            f"/api/projects/{project_id}/clarify-reply",
            json={"question_id": q["id"], "answer": "answer to " + q["question"]},
        )
        assert r.status_code == 200
        assert r.json()["promoted"] is False

    # Final answer — v+1 written, requirement re-parsed.
    last = questions[-1]
    final = await client.post(
        f"/api/projects/{project_id}/clarify-reply",
        json={"question_id": last["id"], "answer": "final answer"},
    )
    assert final.status_code == 200
    body = final.json()
    assert body["promoted"] is True
    assert body["remaining"] == 0
    assert body["requirement_version"] == 2
    assert body["requirement"]["version"] == 2
    assert body["requirement"]["parse_outcome"] == "ok"
    assert body["requirement"]["parsed_json"] is not None
    # The merged raw_text carries the clarification transcript.
    assert "Clarifications:" in body["requirement"]["raw_text"]
    assert "final answer" in body["requirement"]["raw_text"]

    # Event shape: requirement.parsed fires on promotion, marked source.
    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("requirement.parsed")
    # 1 from intake + 1 from promotion.
    assert len(events) == 2
    promo = events[1]
    assert promo.payload["source"] == "clarification-reply"
    assert promo.payload["requirement_version"] == 2

    # agent_run_log got two requirement rows (intake + reparse) + 1 clarification.
    async with session_scope(maker) as session:
        req_rows = await AgentRunLogRepository(session).list_for_agent("requirement")
        clar_rows = await AgentRunLogRepository(session).list_for_agent("clarification")
    assert len(req_rows) == 2
    assert len(clar_rows) == 1


@pytest.mark.asyncio
async def test_answer_rejects_unknown_question(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _intake_once(client)
    await client.post(f"/api/projects/{project_id}/clarify")
    r = await client.post(
        f"/api/projects/{project_id}/clarify-reply",
        json={"question_id": "bogus-id", "answer": "x"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_answer_rejects_unknown_project(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.post(
        "/api/projects/no-project/clarify-reply",
        json={"question_id": "whatever", "answer": "x"},
    )
    assert r.status_code == 404


# ---------- graph-native stage (1E) ---------------------------------------


@pytest.mark.asyncio
async def test_stage_transitions_from_graph_only(api_env):
    """Stage is derived from (requirement.parse_outcome, question status).
    No Project column is written — we assert the stage endpoint reflects
    each step, proving the graph IS the status.
    """
    client, maker, _, _, _, _ = api_env
    project_id = await _intake_once(client)

    # After intake (parsed_json set): stage = ready_for_planning.
    # (Stub parse_outcome = "ok" with no questions yet.)
    r = await client.get(f"/api/projects/{project_id}/stage")
    assert r.status_code == 200
    assert r.json()["stage"] == "ready_for_planning"

    # After /clarify with N questions: clarification_pending.
    await client.post(f"/api/projects/{project_id}/clarify")
    r = await client.get(f"/api/projects/{project_id}/stage")
    body = r.json()
    assert body["stage"] == "clarification_pending"
    assert body["total_questions"] >= 2
    assert body["answered_questions"] == 0

    # Answer one (but not all): clarification_in_progress.
    async with session_scope(maker) as session:
        rows = await ClarificationQuestionRepository(session).list_for_requirement(
            (await RequirementRepository(session).latest_for_project(project_id)).id
        )
    first_q_id = rows[0].id
    await client.post(
        f"/api/projects/{project_id}/clarify-reply",
        json={"question_id": first_q_id, "answer": "first"},
    )
    r = await client.get(f"/api/projects/{project_id}/stage")
    body = r.json()
    assert body["stage"] == "clarification_in_progress"
    assert body["answered_questions"] == 1

    # Answer the rest → v+1 with no questions → ready_for_planning.
    for q in rows[1:]:
        await client.post(
            f"/api/projects/{project_id}/clarify-reply",
            json={"question_id": q.id, "answer": "x"},
        )
    r = await client.get(f"/api/projects/{project_id}/stage")
    body = r.json()
    assert body["stage"] == "ready_for_planning"
    assert body["requirement_version"] == 2


def test_no_current_stage_column_is_written():
    """Regression guard for decision 1E.

    Greps the project source for `current_stage` assignment forms. No code
    path should write a denormalized stage column.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    # Match assignment forms:
    #   current_stage = ...          (attribute or bare)
    #   self.current_stage = ...
    #   project.current_stage = ...
    #   current_stage: ... = ...     (typed)
    pattern = re.compile(
        r"""(?x)
        (?:^|[.\s])current_stage\s*
        (?::\s*[^=]+)?                 # optional type annotation
        =\s*(?!=)                      # = but not ==
        """
    )
    offenders: list[str] = []
    for py in root.rglob("*.py"):
        parts = set(py.parts)
        if parts & {".venv", "__pycache__", ".git", "node_modules"}:
            continue
        if py.name == "test_clarification.py":
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Skip lines inside docstrings: a crude but sufficient filter —
            # lines that don't end with a statement (no `=` followed by code)
            # and sit inside triple quotes are documentation. We enforce this
            # by requiring the `current_stage = X` pattern to have a non-string
            # RHS start on the same line.
            if pattern.search(line):
                # Ignore if the line is inside backticks (markdown-like prose
                # quoted in a docstring).
                if "`" in stripped:
                    continue
                offenders.append(f"{py}:{lineno}: {stripped}")
    assert offenders == [], "found current_stage assignment: " + "; ".join(offenders)
