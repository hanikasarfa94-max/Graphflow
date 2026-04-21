"""Phase 2.B — agent-vs-agent scrimmage acceptance tests.

Four required cases from PLAN-v3.md §2.B:
  1. Convergence: both sub-agents agree on a proposal → outcome
     'converged_proposal' + pending DecisionRow.
  2. Non-convergence: both sub-agents hold divergent positions across 3
     turns → outcome 'unresolved_crux', transcript length 3.
  3. License-aware: observer-tier target with no assignments gets a
     license-scoped slice for its own turn (no leak of out-of-view
     decisions into the prompt).
  4. Transcript persistence + visibility: GET round-trips the transcript;
     non-participant observer gets 403.

Stubs live on `_ScriptablePreAnswerAgent` (conftest). Queue drafts via
`pre_answer_agent.draft_queue.append(...)` — consumed FIFO per turn.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from workgraph_agents.pre_answer import PreAnswerDraft
from workgraph_persistence import (
    DecisionRepository,
    DecisionRow,
    ProjectGraphRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRow,
    UserRepository,
    session_scope,
)


# ---- helpers ------------------------------------------------------------


async def _mk_project(maker, title: str = "SC") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _mk_user(maker, username: str) -> str:
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        return user.id


async def _add_member(
    maker,
    *,
    project_id: str,
    user_id: str,
    role: str = "member",
    license_tier: str = "full",
) -> None:
    async with session_scope(maker) as session:
        member = await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role=role
        )
        member.license_tier = license_tier
        await session.flush()


async def _register_and_login(client, username: str) -> str:
    """Register a user via the auth endpoint and leave the session cookie set."""
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


def _draft(
    *,
    body: str,
    rationale: str,
    confidence: str = "medium",
    recommend_route: bool = False,
) -> PreAnswerDraft:
    return PreAnswerDraft(
        body=body,
        confidence=confidence,
        matched_skills=[],
        uncovered_topics=[],
        recommend_route=recommend_route,
        rationale=rationale,
    )


async def _seed_decision(maker, *, project_id: str, resolver_id: str, text: str) -> str:
    async with session_scope(maker) as session:
        row = await DecisionRepository(session).create(
            conflict_id=None,
            project_id=project_id,
            resolver_id=resolver_id,
            option_index=None,
            custom_text=text,
            rationale=f"seeded decision: {text}",
            apply_actions=[],
            apply_outcome="applied",
        )
        return row.id


# ---- 1. convergence path ------------------------------------------------


@pytest.mark.asyncio
async def test_convergence_records_proposal_and_pending_decision(api_env):
    client, maker, *_ = api_env
    from workgraph_api.main import app

    pid = await _mk_project(maker)
    source_id = await _register_and_login(client, "sc_src_conv")
    target_id = await _mk_user(maker, "sc_tgt_conv")
    await _add_member(maker, project_id=pid, user_id=source_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=target_id)

    # Turn 1 = target's pre-answer draft → agree on "keep permadeath".
    # Turn 2 = source's response, also "agree_with_other" on the same
    # proposal summary. The convergence detector should trip on turn 2.
    draft1 = _draft(
        body="Permadeath stays. Respawn tokens only for tutorial zone.",
        rationale=(
            "Target concurs with source's framing.\n"
            "STANCE:agree_with_other\n"
            "PROPOSAL:keep permadeath"
        ),
        confidence="high",
    )
    draft2 = _draft(
        body="Agreed — keep permadeath, tokens only in tutorial.",
        rationale=(
            "Source endorses target's position.\n"
            "STANCE:agree_with_other\n"
            "PROPOSAL:keep permadeath"
        ),
        confidence="high",
    )
    app.state.pre_answer_agent.draft_queue.append(draft1)
    app.state.pre_answer_agent.draft_queue.append(draft2)

    scrim = app.state.scrimmage_service
    result = await scrim.run_scrimmage(
        project_id=pid,
        source_user_id=source_id,
        target_user_id=target_id,
        question="Should we ship permadeath in the roguelike mode?",
    )

    assert result["outcome"] == "converged_proposal"
    assert result["proposal"] is not None
    assert "keep permadeath" in (result["proposal"]["proposal_text"] or "").lower()
    # 2-turn convergence: transcript length is 2, not 3.
    assert len(result["transcript"]) == 2

    # Pending DecisionRow created with apply_outcome=pending_scrimmage.
    decision_id = result["proposal"]["decision_id"]
    assert decision_id
    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(DecisionRow).where(DecisionRow.id == decision_id)
            )
        ).scalar_one()
    assert row.apply_outcome == "pending_scrimmage"
    assert row.project_id == pid
    assert (row.apply_detail or {}).get("scrimmage_id") == result["id"]


# ---- 2. non-convergence path --------------------------------------------


@pytest.mark.asyncio
async def test_non_convergence_records_three_turns_and_crux(api_env):
    _, maker, *_ = api_env
    from workgraph_api.main import app

    pid = await _mk_project(maker)
    source_id = await _mk_user(maker, "sc_src_div")
    target_id = await _mk_user(maker, "sc_tgt_div")
    await _add_member(maker, project_id=pid, user_id=source_id)
    await _add_member(maker, project_id=pid, user_id=target_id)

    # Turn 1 (target) — holds "permadeath is a mistake".
    # Turn 2 (source) — holds "permadeath is core DNA" (different
    # proposal summary → no convergence).
    # Turn 3 (target) — still holds "permadeath is a mistake" (different
    # from source → no convergence after 3 turns).
    queue = [
        _draft(
            body="We'd lose casual players if we kept permadeath.",
            rationale=(
                "STANCE:hold_position\nPROPOSAL:drop permadeath"
            ),
            confidence="medium",
            recommend_route=True,
        ),
        _draft(
            body="Permadeath IS the game — dropping it guts the hook.",
            rationale=(
                "STANCE:hold_position\nPROPOSAL:keep permadeath"
            ),
            confidence="medium",
            recommend_route=True,
        ),
        _draft(
            body="Retention data still says casuals bounce at run-2.",
            rationale=(
                "STANCE:hold_position\nPROPOSAL:drop permadeath"
            ),
            confidence="medium",
            recommend_route=True,
        ),
    ]
    for d in queue:
        app.state.pre_answer_agent.draft_queue.append(d)

    scrim = app.state.scrimmage_service
    result = await scrim.run_scrimmage(
        project_id=pid,
        source_user_id=source_id,
        target_user_id=target_id,
        question="Should we drop permadeath from the roguelike mode?",
    )

    assert result["outcome"] == "unresolved_crux"
    assert result["proposal"] is None
    assert len(result["transcript"]) == 3
    # Both sides' final stances should be "hold_position".
    by_speaker = {t["speaker"]: t for t in result["transcript"]}
    assert by_speaker["source"]["stance"] == "hold_position"
    assert by_speaker["target"]["stance"] == "hold_position"


# ---- 3. license-aware regression ---------------------------------------


@pytest.mark.asyncio
async def test_license_aware_slice_excludes_out_of_view_nodes(api_env):
    """Observer target: its own turn's prompt is license-scoped to its
    view — out-of-view decisions from the source's full-tier slice must
    NOT appear in the target-turn project_context.

    Easiest probe: seed a decision in the project, confirm it appears in
    a full-tier slice, then run the scrimmage with an observer target
    and check the captured `project_context` for the target-speaker
    turn excludes that decision id.
    """
    _, maker, *_ = api_env
    from workgraph_api.main import app

    pid = await _mk_project(maker)
    source_id = await _mk_user(maker, "sc_full_src")
    target_id = await _mk_user(maker, "sc_obs_tgt")
    # Source: full; target: observer with no assignments → empty view.
    await _add_member(
        maker, project_id=pid, user_id=source_id, license_tier="full"
    )
    await _add_member(
        maker,
        project_id=pid,
        user_id=target_id,
        license_tier="observer",
    )
    # Seed a decision that the full-tier source can see but the empty-
    # view observer cannot.
    hidden_decision_id = await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=source_id,
        text="pricing-strategy-hidden",
    )

    # Sanity: full-tier slice actually exposes this decision.
    full_slice = await app.state.license_context_service.build_slice(
        project_id=pid, viewer_user_id=source_id, audience_user_id=None
    )
    full_ids = {str(d.get("id")) for d in (full_slice.get("decisions") or [])}
    assert hidden_decision_id in full_ids

    # Observer-view slice should NOT include it.
    obs_slice = await app.state.license_context_service.build_slice(
        project_id=pid, viewer_user_id=target_id, audience_user_id=None
    )
    obs_ids = {str(d.get("id")) for d in (obs_slice.get("decisions") or [])}
    assert hidden_decision_id not in obs_ids
    assert obs_slice.get("license_tier") == "observer"

    # Force the scrimmage to take the 3-turn path so target's dedicated
    # turn (turn 3, viewer=target, audience=None) is exercised.
    for _i in range(3):
        app.state.pre_answer_agent.draft_queue.append(
            _draft(
                body=f"stance {_i}",
                rationale=f"STANCE:hold_position\nPROPOSAL:opt-{_i}",
                confidence="medium",
                recommend_route=True,
            )
        )

    agent = app.state.pre_answer_agent
    start_calls = len(agent.calls)

    scrim = app.state.scrimmage_service
    result = await scrim.run_scrimmage(
        project_id=pid,
        source_user_id=source_id,
        target_user_id=target_id,
        question="How should we price the season pass?",
    )
    assert result["outcome"] == "unresolved_crux"

    # Target-speaker turn (turn 3) went through the license-scoped path;
    # grep the captured project_context for the hidden decision id.
    # Call 0 = turn 1 (target via pre_answer_service, sender=source so
    # tier is tighter-of(source=full, target=observer)=observer → also
    # scoped).
    # Call 1 = turn 2 (source speaker → full slice).
    # Call 2 = turn 3 (target speaker → observer slice).
    turn3_ctx = agent.calls[start_calls + 2]["project_context"]
    decisions_in_prompt = turn3_ctx.get("recent_decisions") or []
    decision_ids_in_prompt = {str(d.get("id")) for d in decisions_in_prompt}
    assert hidden_decision_id not in decision_ids_in_prompt
    assert turn3_ctx.get("license_tier") == "observer"


# ---- 4. transcript persistence + fetch visibility -----------------------


@pytest.mark.asyncio
async def test_transcript_fetch_and_non_participant_forbidden(api_env):
    client, maker, *_ = api_env
    from workgraph_api.main import app

    pid = await _mk_project(maker)
    # Source: owns the stream, logs in via client so scrimmage runs
    # under its auth context.
    source_id = await _register_and_login(client, "sc_fetch_src")
    target_id = await _mk_user(maker, "sc_fetch_tgt")
    # Third user: project member but neither source nor target — must
    # NOT see the transcript.
    outsider_id = await _mk_user(maker, "sc_fetch_outsider")
    await _add_member(maker, project_id=pid, user_id=source_id, role="member")
    await _add_member(maker, project_id=pid, user_id=target_id)
    await _add_member(maker, project_id=pid, user_id=outsider_id)

    # Seed 3 divergent drafts so we exercise the full 3-turn transcript.
    for stance_text in ("drop it", "keep it", "drop it"):
        app.state.pre_answer_agent.draft_queue.append(
            _draft(
                body=f"position: {stance_text}",
                rationale=f"STANCE:hold_position\nPROPOSAL:{stance_text}",
                confidence="medium",
                recommend_route=True,
            )
        )

    # Trigger via the API router — exercises auth + router wiring.
    r = await client.post(
        f"/api/projects/{pid}/scrimmages",
        json={
            "target_user_id": target_id,
            "question_text": "Should we keep feature X?",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    scrimmage_id = body["id"]
    assert body["outcome"] == "unresolved_crux"
    assert len(body["transcript"]) == 3

    # Source can fetch the transcript.
    r = await client.get(f"/api/projects/{pid}/scrimmages/{scrimmage_id}")
    assert r.status_code == 200, r.text
    assert r.json()["id"] == scrimmage_id
    assert len(r.json()["transcript"]) == 3

    # Non-participant project member → 403.
    # Register a fresh account for the outsider so we have a real login
    # cookie — the seeded outsider has no password.
    outsider_client_id = await _register_and_login(
        client, "sc_fetch_outsider_login"
    )
    # Add the freshly-registered user to the project (is_member gate).
    await _add_member(maker, project_id=pid, user_id=outsider_client_id)
    r = await client.get(f"/api/projects/{pid}/scrimmages/{scrimmage_id}")
    assert r.status_code == 403, r.text
