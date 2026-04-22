"""Phase 2.B meeting transcript upload acceptance tests.

Required cases (PLAN-v4.md Phase 2.B):
  1. Upload + stubbed metabolism extracts signals and the detail
     endpoint returns them as proposals.
  2. Empty/too-short transcript fails cleanly with a 400 at upload
     time — no row is created, no metabolism is queued. (We chose
     400 over status='failed' because the input is obviously bad;
     burning an LLM call to extract signals from "" is wasteful.)
  3. Extracted signals render as proposals, NOT facts: no DecisionRow
     / TaskRow / RiskRow exist until the accept endpoint is called
     for a specific signal.
  4. Non-members get 403 on upload and get. Members can upload; a
     separate user not on the project cannot see the transcript.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from workgraph_persistence import (
    DecisionRepository,
    MeetingTranscriptRepository,
    PlanRepository,
    ProjectGraphRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRepository,
    RequirementRow,
    RiskRow,
    TaskRow,
    UserRepository,
    session_scope,
)


# ---- helpers -------------------------------------------------------------


async def _register(
    client: AsyncClient, username: str, password: str = "hunter22"
) -> str:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _login(
    client: AsyncClient, username: str, password: str = "hunter22"
) -> None:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text


async def _mk_project(maker, title: str = "Meeting demo") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _add_member(
    maker,
    project_id: str,
    user_id: str,
    *,
    role: str = "member",
) -> None:
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role=role
        )


async def _seed_requirement(maker, *, project_id: str) -> str:
    async with session_scope(maker) as session:
        req = RequirementRow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            version=1,
            raw_text="thesis",
            parsed_json={},
            parse_outcome="ok",
        )
        session.add(req)
        await session.flush()
        return req.id


def _set_stub_signals(app_state, signals_dict):
    """Configure the scriptable metabolizer stub's next output."""
    from workgraph_api.services.meeting_ingest import MetabolizedSignals

    app_state.meeting_metabolizer.next_signals = MetabolizedSignals(
        **signals_dict
    )


# ---- tests ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_and_metabolism_extracts_signals(api_env):
    """Case 1: upload a transcript, metabolizer returns scripted signals,
    detail endpoint surfaces them as proposals."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _register(client, "mt_alice")
    await _add_member(maker, pid, uid, role="owner")
    await _login(client, "mt_alice")

    from workgraph_api.main import app

    _set_stub_signals(
        app.state,
        {
            "decisions": [
                {
                    "text": "Ship in two stages: MVP then polish",
                    "rationale": "Team needs user feedback before polish",
                }
            ],
            "tasks": [
                {
                    "title": "Draft MVP spec",
                    "description": "Scope doc covering the two-stage plan",
                    "suggested_owner_hint": "PM",
                }
            ],
            "risks": [
                {
                    "title": "Design bandwidth may slip",
                    "content": "Design team is at 110% load already",
                    "severity": "high",
                }
            ],
            "stances": [
                {
                    "participant_hint": "Alice",
                    "topic": "Whether to parallelize polish",
                    "stance": "Against — wants MVP data first",
                }
            ],
        },
    )

    r = await client.post(
        f"/api/projects/{pid}/meetings",
        json={
            "title": "Stage-gating discussion",
            "transcript_text": (
                "Alice: We should ship MVP first.\n"
                "Bob: Agreed. Design is stretched thin.\n"
                "Decision: two-stage ship, MVP then polish.\n"
                "Action: Alice drafts the MVP spec by Friday."
            ),
            "participant_user_ids": [],
        },
    )
    assert r.status_code == 200, r.text
    created = r.json()["transcript"]
    assert created["metabolism_status"] == "pending"
    assert created["title"] == "Stage-gating discussion"
    transcript_id = created["id"]

    # Let the background metabolism finish.
    await app.state.meeting_ingest_service.drain()

    detail_resp = await client.get(
        f"/api/projects/{pid}/meetings/{transcript_id}"
    )
    assert detail_resp.status_code == 200, detail_resp.text
    detail = detail_resp.json()["transcript"]
    assert detail["metabolism_status"] == "done"
    signals = detail["extracted_signals"]
    assert len(signals["decisions"]) == 1
    assert signals["decisions"][0]["text"].startswith("Ship in two stages")
    assert len(signals["tasks"]) == 1
    assert signals["tasks"][0]["title"] == "Draft MVP spec"
    assert len(signals["risks"]) == 1
    assert signals["risks"][0]["severity"] == "high"
    assert len(signals["stances"]) == 1
    # The metabolizer was called exactly once with the transcript text.
    assert len(app.state.meeting_metabolizer.calls) == 1
    call = app.state.meeting_metabolizer.calls[0]
    assert "MVP" in call["transcript_text"]


@pytest.mark.asyncio
async def test_empty_transcript_fails_cleanly(api_env):
    """Case 2: a too-short transcript is rejected at the POST boundary
    with a 400. No row is created, no metabolism runs."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _register(client, "mt_bob")
    await _add_member(maker, pid, uid, role="member")
    await _login(client, "mt_bob")

    # Empty string: caught by the Pydantic min_length guard → 422.
    r = await client.post(
        f"/api/projects/{pid}/meetings",
        json={"title": "Empty", "transcript_text": ""},
    )
    assert r.status_code in (400, 422), r.text

    # Below MIN_TRANSCRIPT_CHARS but non-empty: service-side reject → 400.
    r2 = await client.post(
        f"/api/projects/{pid}/meetings",
        json={"title": "Shorty", "transcript_text": "too short"},
    )
    assert r2.status_code == 400, r2.text
    # Error handler maps HTTPException(detail=code) → ApiError(message=code).
    assert "transcript_too_short" in r2.text

    # No rows created.
    async with session_scope(maker) as session:
        rows = await MeetingTranscriptRepository(session).list_for_project(pid)
        assert rows == []

    # Metabolizer was never called.
    from workgraph_api.main import app

    assert app.state.meeting_metabolizer.calls == []


@pytest.mark.asyncio
async def test_signals_are_proposals_not_facts(api_env):
    """Case 3: extracted signals do NOT auto-create DecisionRow / TaskRow
    / RiskRow. Only accepting a specific signal materializes a row."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _register(client, "mt_carol")
    await _add_member(maker, pid, uid, role="owner")
    req_id = await _seed_requirement(maker, project_id=pid)
    await _login(client, "mt_carol")

    from workgraph_api.main import app

    _set_stub_signals(
        app.state,
        {
            "decisions": [{"text": "Adopt the two-stage rollout plan"}],
            "tasks": [{"title": "Draft MVP spec"}],
            "risks": [{"title": "Design bandwidth gap", "severity": "medium"}],
            "stances": [],
        },
    )

    r = await client.post(
        f"/api/projects/{pid}/meetings",
        json={
            "title": "Rollout alignment",
            "transcript_text": (
                "We agreed on a two-stage rollout. Alice will draft the MVP "
                "spec. Design bandwidth is a concern."
            ),
        },
    )
    assert r.status_code == 200, r.text
    transcript_id = r.json()["transcript"]["id"]
    await app.state.meeting_ingest_service.drain()

    # Graph is untouched — no decision / task / risk rows exist yet.
    async with session_scope(maker) as session:
        decisions = await DecisionRepository(session).list_for_project(pid)
        assert decisions == []
        tasks = await PlanRepository(session).list_tasks(req_id)
        assert tasks == []
        risks = await ProjectGraphRepository(session).list_risks(req_id)
        assert risks == []

    # Accept the decision signal → DecisionRow appears.
    accept_d = await client.post(
        f"/api/projects/{pid}/meetings/{transcript_id}"
        "/signals/decision/0/accept"
    )
    assert accept_d.status_code == 200, accept_d.text
    assert accept_d.json()["signal_kind"] == "decision"

    # Accept the task signal → TaskRow appears.
    accept_t = await client.post(
        f"/api/projects/{pid}/meetings/{transcript_id}"
        "/signals/task/0/accept"
    )
    assert accept_t.status_code == 200, accept_t.text

    # Accept the risk signal → RiskRow appears.
    accept_r = await client.post(
        f"/api/projects/{pid}/meetings/{transcript_id}"
        "/signals/risk/0/accept"
    )
    assert accept_r.status_code == 200, accept_r.text

    async with session_scope(maker) as session:
        decisions = await DecisionRepository(session).list_for_project(pid)
        assert len(decisions) == 1
        assert decisions[0].custom_text.startswith("Adopt the two-stage")
        assert decisions[0].resolver_id == uid

        tasks = (
            await session.execute(
                select(TaskRow).where(TaskRow.project_id == pid)
            )
        ).scalars().all()
        assert len(list(tasks)) == 1

        risks = (
            await session.execute(
                select(RiskRow).where(RiskRow.project_id == pid)
            )
        ).scalars().all()
        risks_list = list(risks)
        assert len(risks_list) == 1
        assert risks_list[0].severity == "medium"

    # Accepting the same signal twice still creates a second row (the
    # service flags the bucket item with `_accepted_entity_id`, but
    # doesn't currently block re-accept; that's an explicit v2 polish).
    # Verify the bucket item now carries provenance:
    detail_resp = await client.get(
        f"/api/projects/{pid}/meetings/{transcript_id}"
    )
    detail = detail_resp.json()["transcript"]
    accepted_task = detail["extracted_signals"]["tasks"][0]
    assert accepted_task.get("_accepted_entity_id")


@pytest.mark.asyncio
async def test_non_member_is_forbidden(api_env):
    """Case 4: a user who is not a project member gets 403 on upload
    and get endpoints. Members can do both."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)

    # Alice is a member; Bob is not.
    alice_id = await _register(client, "mt_alice4")
    await _add_member(maker, pid, alice_id, role="member")
    await _login(client, "mt_alice4")

    from workgraph_api.main import app

    _set_stub_signals(
        app.state, {"decisions": [], "tasks": [], "risks": [], "stances": []}
    )
    r = await client.post(
        f"/api/projects/{pid}/meetings",
        json={
            "title": "Members-only meeting",
            "transcript_text": (
                "Short sync on next sprint scope. No decisions reached."
            ),
        },
    )
    assert r.status_code == 200, r.text
    transcript_id = r.json()["transcript"]["id"]
    await app.state.meeting_ingest_service.drain()

    # Bob registers but is not added to the project.
    await _register(client, "mt_bob4")
    await _login(client, "mt_bob4")

    forbidden_upload = await client.post(
        f"/api/projects/{pid}/meetings",
        json={
            "title": "Sneaky upload",
            "transcript_text": (
                "Bob trying to post a transcript to a project he's not on."
            ),
        },
    )
    assert forbidden_upload.status_code == 403

    forbidden_list = await client.get(f"/api/projects/{pid}/meetings")
    assert forbidden_list.status_code == 403

    forbidden_detail = await client.get(
        f"/api/projects/{pid}/meetings/{transcript_id}"
    )
    assert forbidden_detail.status_code == 403
