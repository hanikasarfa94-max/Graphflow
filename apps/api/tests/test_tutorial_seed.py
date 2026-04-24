"""Tutorial onboarding seed — game-style welcome-project tests.

Covers:
  1. register → tutorial project exists + user is owner + one in_vote
     proposal with voter_pool containing the new user.
  2. second register → second user gets their OWN tutorial project, but
     synthetic teammates (Sam, Aiko, Diego) are REUSED (not duplicated).
  3. casting a vote on the tutorial proposal resolves it normally — the
     DecisionRow is minted and the proposal transitions to 'approved'.
  4. re-invoking `seed_for_new_user` for the same user is a no-op
     (idempotence guard).
  5. a failed seed MUST NOT block registration — the router swallows
     errors so users never see a 500 because of onboarding polish.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from workgraph_persistence import (
    DecisionRepository,
    GatedProposalRepository,
    GatedProposalRow,
    ProjectMemberRepository,
    ProjectRow,
    UserRepository,
    session_scope,
)

from workgraph_api.services import TUTORIAL_TITLE_EN, TUTORIAL_TITLES


# --------------------------------------------------------------------- fixtures


@pytest_asyncio.fixture
async def api_env_with_tutorial(api_env):
    """Promote the tutorial seed service into active state.

    `api_env` intentionally leaves `tutorial_seed_service = None` so
    existing tests don't pick up an unexpected welcome project on
    register. Tutorial tests opt in by requesting this fixture.
    """
    from workgraph_api.main import app

    app.state.tutorial_seed_service = app.state._tutorial_seed_service_available
    try:
        yield api_env
    finally:
        app.state.tutorial_seed_service = None


# --------------------------------------------------------------------- helpers


async def _register(client, username: str, password: str = "hunter22") -> dict:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _login(client, username: str, password: str = "hunter22") -> None:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text


async def _tutorial_project_for_user(maker, user_id: str) -> ProjectRow | None:
    async with session_scope(maker) as session:
        memberships = await ProjectMemberRepository(session).list_for_user(user_id)
        if not memberships:
            return None
        project_ids = [m.project_id for m in memberships]
        rows = (
            await session.execute(
                select(ProjectRow).where(ProjectRow.id.in_(project_ids))
            )
        ).scalars().all()
        for p in rows:
            if p.title in TUTORIAL_TITLES:
                return p
    return None


# ----------------------------------------------------- 1. registration seeds


@pytest.mark.asyncio
async def test_register_seeds_tutorial_project(api_env_with_tutorial):
    client, maker, *_ = api_env_with_tutorial

    user = await _register(client, "newbie_alice")
    user_id = user["id"]

    project = await _tutorial_project_for_user(maker, user_id)
    assert project is not None, "registration should seed a tutorial project"
    assert project.title == TUTORIAL_TITLE_EN
    # gate_keeper_map points scope_cut at Sam — the synthetic owner peer.
    assert "scope_cut" in (project.gate_keeper_map or {})

    # User is owner.
    async with session_scope(maker) as session:
        memberships = await ProjectMemberRepository(session).list_for_project(
            project.id
        )
    roles_by_user = {m.user_id: m.role for m in memberships}
    assert roles_by_user.get(user_id) == "owner"

    # Exactly one in_vote gated proposal, voter_pool contains new user.
    async with session_scope(maker) as session:
        proposals = await GatedProposalRepository(session).list_for_project(
            project.id
        )
    assert len(proposals) == 1
    prop = proposals[0]
    assert prop.status == "in_vote"
    assert prop.decision_class == "scope_cut"
    assert user_id in (prop.voter_pool or [])
    # Pool should be (owners) = {new user, Sam}; size 2.
    assert len(prop.voter_pool or []) == 2


# ----------------------------------- 2. second user reuses synthetic teammates


@pytest.mark.asyncio
async def test_second_user_reuses_synthetic_teammates(api_env_with_tutorial):
    client, maker, *_ = api_env_with_tutorial

    user_a = await _register(client, "newbie_bob")
    user_b = await _register(client, "newbie_carol")

    # Each user has their own tutorial project.
    pa = await _tutorial_project_for_user(maker, user_a["id"])
    pb = await _tutorial_project_for_user(maker, user_b["id"])
    assert pa is not None and pb is not None
    assert pa.id != pb.id

    # The synthetic personas are globally shared — one row per username.
    async with session_scope(maker) as session:
        user_repo = UserRepository(session)
        sam = await user_repo.get_by_username("sam_chen_demo")
        aiko = await user_repo.get_by_username("aiko_tanaka_demo")
        diego = await user_repo.get_by_username("diego_ramirez_demo")
    assert sam is not None and aiko is not None and diego is not None

    # Both projects' gate_keeper_map["scope_cut"] points at the SAME sam.id.
    assert (pa.gate_keeper_map or {}).get("scope_cut") == sam.id
    assert (pb.gate_keeper_map or {}).get("scope_cut") == sam.id

    # Sam is a member of both projects (was not re-created per project).
    async with session_scope(maker) as session:
        a_members = await ProjectMemberRepository(session).list_for_project(pa.id)
        b_members = await ProjectMemberRepository(session).list_for_project(pb.id)
    assert sam.id in {m.user_id for m in a_members}
    assert sam.id in {m.user_id for m in b_members}


# ------------------------------- 3. vote resolves proposal as usual


@pytest.mark.asyncio
async def test_vote_on_tutorial_proposal_resolves(api_env_with_tutorial):
    client, maker, *_ = api_env_with_tutorial

    user = await _register(client, "newbie_dan")
    user_id = user["id"]

    project = await _tutorial_project_for_user(maker, user_id)
    assert project is not None

    async with session_scope(maker) as session:
        proposals = await GatedProposalRepository(session).list_for_project(
            project.id
        )
    proposal_id = proposals[0].id
    pool = proposals[0].voter_pool or []
    assert len(pool) == 2  # threshold is 2, user's approve is tipping

    # Cast approve. Threshold=2; sam hasn't voted, but the user's vote
    # PLUS sam absent means approve (1) + outstanding (1) = 2 which is
    # not yet tipping. So we need sam's vote too — simulate via
    # GatedProposalService directly (synthetic user has no session).
    from workgraph_api.main import app

    svc = app.state.gated_proposals_service
    # First the user votes approve.
    r1 = await svc.cast_vote(
        proposal_id=proposal_id, voter_user_id=user_id, verdict="approve"
    )
    assert r1["ok"] is True
    # Not resolved yet — only one of two approves.
    assert r1["resolved_as"] is None

    # Find sam.
    async with session_scope(maker) as session:
        sam = await UserRepository(session).get_by_username("sam_chen_demo")
    assert sam is not None
    sam_id = sam.id

    # Sam votes approve — tips threshold (2/2).
    r2 = await svc.cast_vote(
        proposal_id=proposal_id, voter_user_id=sam_id, verdict="approve"
    )
    assert r2["ok"] is True
    assert r2["resolved_as"] == "approved"
    decision_id = r2["decision_id"]
    assert decision_id

    # DecisionRow minted with lineage back to the proposal.
    async with session_scope(maker) as session:
        decision = await DecisionRepository(session).get(decision_id)
        refreshed_prop = (
            await session.execute(
                select(GatedProposalRow).where(GatedProposalRow.id == proposal_id)
            )
        ).scalar_one()
    assert decision is not None
    assert decision.decision_class == "scope_cut"
    assert decision.gated_via_proposal_id == proposal_id
    assert refreshed_prop.status == "approved"


# ----------------------------- 4. seeding is idempotent per user


@pytest.mark.asyncio
async def test_onboarding_seed_is_idempotent(api_env_with_tutorial):
    client, maker, *_ = api_env_with_tutorial

    user = await _register(client, "newbie_ellie")
    user_id = user["id"]

    from workgraph_api.main import app

    svc = app.state.tutorial_seed_service
    # Re-invoking should be a no-op — user already has a tutorial project.
    result = await svc.seed_for_new_user(user_id=user_id)
    assert result["ok"] is True
    assert result["already_seeded"] is True

    # Only one tutorial project exists for this user.
    async with session_scope(maker) as session:
        memberships = await ProjectMemberRepository(session).list_for_user(user_id)
        project_ids = [m.project_id for m in memberships]
        rows = (
            await session.execute(
                select(ProjectRow).where(ProjectRow.id.in_(project_ids))
            )
        ).scalars().all()
    tutorial_count = sum(1 for p in rows if p.title in TUTORIAL_TITLES)
    assert tutorial_count == 1


# ---------------- 5. seeding failure must not block registration


@pytest.mark.asyncio
async def test_seed_failure_does_not_block_register(api_env_with_tutorial):
    client, maker, *_ = api_env_with_tutorial

    from workgraph_api.main import app

    class _ExplodingSeed:
        async def seed_for_new_user(self, **kwargs):
            raise RuntimeError("boom — deliberate failure")

    original = app.state.tutorial_seed_service
    app.state.tutorial_seed_service = _ExplodingSeed()
    try:
        r = await client.post(
            "/api/auth/register",
            json={"username": "newbie_frank", "password": "hunter22"},
        )
        # Registration itself MUST succeed even when seed blows up.
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["username"] == "newbie_frank"
    finally:
        app.state.tutorial_seed_service = original
