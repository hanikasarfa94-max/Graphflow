"""Phase 1.B ambient onboarding acceptance tests.

Required cases (PLAN-v4.md Phase 1.B):
  1. First visit triggers OnboardingStateRow creation with first_seen_at.
  2. Completed state persists across subsequent visits (overlay not
     re-shown).
  3. Dismissal persists (overlay not re-shown, but not marked
     completed).
  4. License-scoped walkthrough excludes out-of-view nodes (observer
     tier sees a narrower slice than full-tier).

Plus a couple of sanity guards (checkpoint validation, replay resets
the row).
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from workgraph_persistence import (
    AssignmentRepository,
    CommitmentRepository,
    PlanRepository,
    ProjectGraphRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRow,
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


async def _seed_user(maker, username: str) -> str:
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        return user.id


async def _mk_project(maker, title: str = "Onboarding demo") -> str:
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
    license_tier: str = "full",
) -> None:
    async with session_scope(maker) as session:
        member = await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role=role
        )
        member.license_tier = license_tier
        await session.flush()


async def _seed_graph_plan(maker, *, project_id: str) -> dict[str, str]:
    """Seed 1 goal, 2 deliverables, 2 tasks, 1 risk so the walkthrough
    has something to render on."""
    async with session_scope(maker) as session:
        req = RequirementRow(
            id=str(uuid.uuid4()),
            project_id=project_id,
            version=1,
            raw_text="t",
            parsed_json={},
            parse_outcome="ok",
        )
        session.add(req)
        await session.flush()
        req_id = req.id

    async with session_scope(maker) as session:
        graph = await ProjectGraphRepository(
            session
        ).append_for_requirement(
            project_id=project_id,
            requirement_id=req_id,
            goals=[{"title": "Ship feature"}],
            deliverables=[
                {"title": "Del A"},
                {"title": "Del B"},
            ],
            constraints=[],
            risks=[{"title": "Scope creep", "severity": "high"}],
        )
        ids = {
            "goal_id": graph["goals"][0].id,
            "del_a": graph["deliverables"][0].id,
            "del_b": graph["deliverables"][1].id,
            "risk_id": graph["risks"][0].id,
        }
        plan = await PlanRepository(session).append_plan(
            project_id=project_id,
            requirement_id=req_id,
            tasks=[
                {
                    "ref": "t-mine",
                    "title": "Mine",
                    "deliverable_id": ids["del_a"],
                    "assignee_role": "backend",
                },
                {
                    "ref": "t-theirs",
                    "title": "Theirs",
                    "deliverable_id": ids["del_b"],
                    "assignee_role": "backend",
                },
            ],
            dependencies=[],
            milestones=[],
        )
        ids["task_mine"] = plan["tasks"][0].id
        ids["task_theirs"] = plan["tasks"][1].id
    return ids


async def _assign(maker, *, project_id: str, task_id: str, user_id: str):
    async with session_scope(maker) as session:
        await AssignmentRepository(session).set_assignment(
            project_id=project_id, task_id=task_id, user_id=user_id
        )


async def _seed_commitment(
    maker, *, project_id: str, owner_id: str, headline: str
) -> str:
    async with session_scope(maker) as session:
        row = await CommitmentRepository(session).create(
            project_id=project_id,
            created_by_user_id=owner_id,
            owner_user_id=owner_id,
            headline=headline,
        )
        return row.id


# ---- tests ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_visit_creates_onboarding_state(api_env):
    """Case 1: GET walkthrough on a cold (user, project) creates the
    OnboardingStateRow with first_seen_at and returns the structured
    script."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _register(client, "ob_alice")
    await _add_member(maker, pid, uid, role="member")
    await _seed_graph_plan(maker, project_id=pid)
    await _seed_commitment(
        maker,
        project_id=pid,
        owner_id=uid,
        headline="Ship the thing by end of quarter",
    )

    await _login(client, "ob_alice")
    r = await client.get(
        f"/api/projects/{pid}/onboarding/walkthrough"
    )
    assert r.status_code == 200, r.text
    body = r.json()

    state = body["state"]
    assert state["user_id"] == uid
    assert state["project_id"] == pid
    assert state["first_seen_at"] is not None
    assert state["walkthrough_completed_at"] is None
    assert state["dismissed"] is False
    assert state["last_checkpoint"] == "not_started"

    walkthrough = body["walkthrough"]
    section_kinds = [s["kind"] for s in walkthrough["sections"]]
    # All five required sections are present, in canonical order.
    assert section_kinds == [
        "vision",
        "decisions",
        "teammates",
        "your_tasks",
        "open_risks",
    ]
    # Vision section picks up the seeded commitment as a citation.
    vision = walkthrough["sections"][0]
    cited_kinds = {
        c["kind"]
        for claim in vision["claims"]
        for c in (claim.get("citations") or [])
    }
    assert "commitment" in cited_kinds


@pytest.mark.asyncio
async def test_completed_state_persists_overlay_not_reshown(api_env):
    """Case 2: marking the walkthrough completed persists across
    subsequent GETs — walkthrough_completed_at is set and remains
    across reads so the overlay won't re-open."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _register(client, "ob_bob")
    await _add_member(maker, pid, uid)
    await _seed_graph_plan(maker, project_id=pid)

    await _login(client, "ob_bob")

    r = await client.get(
        f"/api/projects/{pid}/onboarding/walkthrough"
    )
    assert r.status_code == 200

    # Advance through sections + mark completed.
    for ck in (
        "vision",
        "decisions",
        "teammates",
        "your_tasks",
        "open_risks",
        "completed",
    ):
        rr = await client.post(
            f"/api/projects/{pid}/onboarding/checkpoint",
            json={"checkpoint": ck},
        )
        assert rr.status_code == 200, rr.text

    # Reload — the row still says completed.
    r2 = await client.get(
        f"/api/projects/{pid}/onboarding/walkthrough"
    )
    assert r2.status_code == 200
    state = r2.json()["state"]
    assert state["last_checkpoint"] == "completed"
    assert state["walkthrough_completed_at"] is not None
    # A third read yields the same timestamp — the "done" state is
    # stable, not re-stamped.
    r3 = await client.get(
        f"/api/projects/{pid}/onboarding/walkthrough"
    )
    assert r3.status_code == 200
    assert (
        r3.json()["state"]["walkthrough_completed_at"]
        == state["walkthrough_completed_at"]
    )


@pytest.mark.asyncio
async def test_dismissal_persists_without_completion(api_env):
    """Case 3: dismiss endpoint sets dismissed=True and the state row
    continues to carry that on subsequent reads, without marking
    completed_at."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _register(client, "ob_carol")
    await _add_member(maker, pid, uid)
    await _seed_graph_plan(maker, project_id=pid)

    await _login(client, "ob_carol")
    # Trigger first-visit row creation.
    r = await client.get(
        f"/api/projects/{pid}/onboarding/walkthrough"
    )
    assert r.status_code == 200
    assert r.json()["state"]["dismissed"] is False

    rd = await client.post(
        f"/api/projects/{pid}/onboarding/dismiss"
    )
    assert rd.status_code == 200, rd.text
    assert rd.json()["state"]["dismissed"] is True
    assert rd.json()["state"]["walkthrough_completed_at"] is None

    # Subsequent GET still shows dismissed=True, completed still null.
    r2 = await client.get(
        f"/api/projects/{pid}/onboarding/walkthrough"
    )
    assert r2.status_code == 200
    state = r2.json()["state"]
    assert state["dismissed"] is True
    assert state["walkthrough_completed_at"] is None

    # Replay resets both.
    rr = await client.post(
        f"/api/projects/{pid}/onboarding/replay"
    )
    assert rr.status_code == 200
    replayed = rr.json()["state"]
    assert replayed["dismissed"] is False
    assert replayed["last_checkpoint"] == "not_started"
    assert replayed["walkthrough_completed_at"] is None


@pytest.mark.asyncio
async def test_observer_walkthrough_is_narrower_than_full(api_env):
    """Case 4: an observer-tier member's walkthrough excludes
    out-of-view tasks and risks. A full-tier peer on the same project
    sees the full surface — this proves the slice is license-scoped,
    not just a visual filter."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)

    full_uid = await _register(client, "ob_full")
    # Log out so the second register works cleanly.
    client.cookies.clear()
    obs_uid = await _register(client, "ob_observer")

    await _add_member(maker, pid, full_uid, role="member", license_tier="full")
    await _add_member(
        maker, pid, obs_uid, role="member", license_tier="observer"
    )

    ids = await _seed_graph_plan(maker, project_id=pid)
    # Full member owns one task; observer owns nothing.
    await _assign(
        maker,
        project_id=pid,
        task_id=ids["task_mine"],
        user_id=full_uid,
    )

    # Observer fetches walkthrough — license slice returns empty tasks +
    # empty risks, so `your_tasks` and `open_risks` sections carry no
    # citations.
    await _login(client, "ob_observer")
    r_obs = await client.get(
        f"/api/projects/{pid}/onboarding/walkthrough"
    )
    assert r_obs.status_code == 200
    obs_walkthrough = r_obs.json()["walkthrough"]
    assert obs_walkthrough["license_tier"] == "observer"

    obs_sections = {s["kind"]: s for s in obs_walkthrough["sections"]}
    # Your-tasks section: observer owns no task assignments, zero claims.
    assert obs_sections["your_tasks"]["claims"] == []
    # Open-risks section: observer's graph slice strips all risks
    # (observer sees only explicit links; RiskRow has no viewer
    # link). Zero citations.
    assert obs_sections["open_risks"]["claims"] == []

    # Full member on the same project sees their assigned task + the risk.
    await _login(client, "ob_full")
    r_full = await client.get(
        f"/api/projects/{pid}/onboarding/walkthrough"
    )
    assert r_full.status_code == 200
    full_walkthrough = r_full.json()["walkthrough"]
    assert full_walkthrough["license_tier"] == "full"
    full_sections = {s["kind"]: s for s in full_walkthrough["sections"]}

    full_task_ids = {
        c["node_id"]
        for claim in full_sections["your_tasks"]["claims"]
        for c in (claim.get("citations") or [])
    }
    assert ids["task_mine"] in full_task_ids

    full_risk_ids = {
        c["node_id"]
        for claim in full_sections["open_risks"]["claims"]
        for c in (claim.get("citations") or [])
    }
    assert ids["risk_id"] in full_risk_ids


@pytest.mark.asyncio
async def test_invalid_checkpoint_rejected(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    uid = await _register(client, "ob_dan")
    await _add_member(maker, pid, uid)

    await _login(client, "ob_dan")
    # Initialise state first so the checkpoint path has a row.
    await client.get(f"/api/projects/{pid}/onboarding/walkthrough")

    r = await client.post(
        f"/api/projects/{pid}/onboarding/checkpoint",
        json={"checkpoint": "not_a_real_checkpoint"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_non_member_forbidden(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    _ = await _register(client, "ob_outside")
    await _login(client, "ob_outside")
    r = await client.get(
        f"/api/projects/{pid}/onboarding/walkthrough"
    )
    assert r.status_code == 403
