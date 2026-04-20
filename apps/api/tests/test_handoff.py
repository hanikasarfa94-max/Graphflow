"""Stage 3 handoff tests.

Covers:
  * prepare: owner-only, derives routines from decisions + routings,
    PII-stripping invariant (no user_ids or display names in
    profile_skill_routines payload).
  * finalize: owner-only; flips status, stamps finalized_at.
  * list_for_project: owner sees all, successor sees only own inherited.
  * for_successor: merges multiple predecessors' routines per skill.
  * error paths: same_user, non-owner, non-member target.
"""
from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient

from workgraph_persistence import (
    DecisionRepository,
    ProjectMemberRepository,
    ProjectRow,
    RoutedSignalRow,
    UserRepository,
    session_scope,
)


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


async def _login(client: AsyncClient, username: str, password="hunter22"):
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text


async def _seed_user(
    maker, username: str, *, role_hints=None, declared=None
) -> str:
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        if role_hints or declared:
            await UserRepository(session).update_profile(
                user.id,
                role_hints=role_hints,
                declared_abilities=declared,
            )
        return user.id


async def _set_profile(maker, uid, *, role_hints=None, declared=None):
    async with session_scope(maker) as session:
        await UserRepository(session).update_profile(
            uid, role_hints=role_hints, declared_abilities=declared
        )


async def _mk_project(maker, title="HO") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _add_member(maker, pid, uid, *, role="member"):
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=uid, role=role
        )


async def _seed_decision(
    maker, *, project_id, resolver_id, apply_actions=None
):
    async with session_scope(maker) as session:
        await DecisionRepository(session).create(
            conflict_id=None,
            project_id=project_id,
            resolver_id=resolver_id,
            option_index=None,
            custom_text="test",
            rationale="handoff test decision",
            apply_actions=apply_actions or [],
            apply_outcome="advisory",
        )


async def _seed_routed_inbound(
    maker, *, project_id, source_user_id, target_user_id, replied=False
):
    """Create a RoutedSignalRow and attach a reply if replied=True.

    Needs streams — create them inline since RoutedSignalRow has FKs.
    """
    from workgraph_persistence import StreamRow

    async with session_scope(maker) as session:
        source_stream_id = str(uuid.uuid4())
        target_stream_id = str(uuid.uuid4())
        session.add(
            StreamRow(
                id=source_stream_id,
                type="personal",
                project_id=project_id,
                owner_user_id=source_user_id,
            )
        )
        session.add(
            StreamRow(
                id=target_stream_id,
                type="personal",
                project_id=project_id,
                owner_user_id=target_user_id,
            )
        )
        await session.flush()
        reply_json = (
            {"kind": "accept", "option_id": "x", "responded_at": "now"}
            if replied
            else None
        )
        session.add(
            RoutedSignalRow(
                id=str(uuid.uuid4()),
                source_user_id=source_user_id,
                target_user_id=target_user_id,
                source_stream_id=source_stream_id,
                target_stream_id=target_stream_id,
                project_id=project_id,
                framing="hey, can you look at this?",
                background_json=[],
                options_json=[],
                reply_json=reply_json,
                status="pending" if not replied else "resolved",
            )
        )


@pytest.mark.asyncio
async def test_prepare_owner_only(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "ho_owner")
    await _set_profile(maker, owner_id, role_hints=["founder"])
    depart_id = await _seed_user(
        maker, "ho_depart", role_hints=["engineering-lead"]
    )
    succ_id = await _seed_user(
        maker, "ho_succ", role_hints=["engineering-lead"]
    )
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, depart_id, role="member")
    await _add_member(maker, pid, succ_id, role="member")

    await _login(client, "ho_owner")
    r = await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": depart_id, "to_user_id": succ_id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    handoff = body["handoff"]
    assert handoff["status"] == "draft"
    assert handoff["from_user_id"] == depart_id
    assert handoff["to_user_id"] == succ_id
    # engineering-lead → systems-architecture / performance / eng-coordination
    assert "systems-architecture" in handoff["role_skills_transferred"]


@pytest.mark.asyncio
async def test_prepare_non_owner_forbidden(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    non_owner_id = await _register(client, "ho_nonowner")
    await _set_profile(maker, non_owner_id, role_hints=["junior-engineer"])
    depart_id = await _seed_user(maker, "ho_d2", role_hints=["qa-lead"])
    succ_id = await _seed_user(maker, "ho_s2", role_hints=["qa-lead"])
    await _add_member(maker, pid, non_owner_id, role="member")
    await _add_member(maker, pid, depart_id, role="member")
    await _add_member(maker, pid, succ_id, role="member")

    r = await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": depart_id, "to_user_id": succ_id},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_prepare_derives_routines_from_decisions_and_routings(api_env):
    """Happy path proving routines summarize observed emissions."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "ho_owner_derive")
    await _set_profile(maker, owner_id, role_hints=["founder"])
    depart_id = await _seed_user(
        maker, "ho_depart_derive", role_hints=["game-director"]
    )
    succ_id = await _seed_user(
        maker, "ho_succ_derive", role_hints=["game-director"]
    )
    helper_id = await _seed_user(
        maker, "ho_helper", role_hints=["qa-lead"]
    )
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, depart_id, role="member")
    await _add_member(maker, pid, succ_id, role="member")
    await _add_member(maker, pid, helper_id, role="member")

    # Seed 3 decisions by the departing member, two of which close
    # risks (→ risk-management routine).
    for actions in (
        [{"kind": "close_risk", "risk_id": "r1"}],
        [{"kind": "close_risk", "risk_id": "r2"}],
        [{"kind": "adjust_scope"}],
    ):
        await _seed_decision(
            maker,
            project_id=pid,
            resolver_id=depart_id,
            apply_actions=actions,
        )
    # Seed an inbound routing that the departing user answered
    # (source = helper, target = depart) → expertise-routing routine.
    await _seed_routed_inbound(
        maker,
        project_id=pid,
        source_user_id=helper_id,
        target_user_id=depart_id,
        replied=True,
    )

    await _login(client, "ho_owner_derive")
    r = await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": depart_id, "to_user_id": succ_id},
    )
    assert r.status_code == 200, r.text
    routines = r.json()["handoff"]["profile_skill_routines"]
    skills = {rt["skill"]: rt for rt in routines}
    assert "risk-management" in skills
    assert skills["risk-management"]["evidence_count"] == 2
    assert "scope-decisions" in skills
    assert "expertise-routing" in skills
    # Stakeholder = the person who asked, role_hint "qa-lead"
    assert (
        "qa-lead"
        in skills["expertise-routing"]["applies_to_roles"]
    )


@pytest.mark.asyncio
async def test_routines_strip_pii(api_env):
    """Invariant: profile_skill_routines never contains user_ids or
    raw display names — only skill names, role_hints, source kinds."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "ho_pii_owner")
    await _set_profile(maker, owner_id, role_hints=["founder"])
    depart_id = await _seed_user(
        maker, "ho_pii_depart", role_hints=["design-lead"]
    )
    succ_id = await _seed_user(
        maker, "ho_pii_succ", role_hints=["design-lead"]
    )
    helper_id = await _seed_user(maker, "ho_pii_helper", role_hints=["qa-lead"])
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, depart_id, role="member")
    await _add_member(maker, pid, succ_id, role="member")
    await _add_member(maker, pid, helper_id, role="member")

    await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=depart_id,
        apply_actions=[{"kind": "close_risk"}],
    )
    await _seed_routed_inbound(
        maker,
        project_id=pid,
        source_user_id=helper_id,
        target_user_id=depart_id,
        replied=True,
    )

    await _login(client, "ho_pii_owner")
    r = await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": depart_id, "to_user_id": succ_id},
    )
    routines = r.json()["handoff"]["profile_skill_routines"]
    # Flatten to JSON and assert no PII strings anywhere.
    blob = json.dumps(routines)
    assert depart_id not in blob
    assert succ_id not in blob
    assert helper_id not in blob
    assert "ho_pii_depart" not in blob
    assert "ho_pii_succ" not in blob
    assert "ho_pii_helper" not in blob


@pytest.mark.asyncio
async def test_finalize_flips_status(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "ho_fin_owner")
    await _set_profile(maker, owner_id, role_hints=["founder"])
    depart_id = await _seed_user(maker, "ho_fin_dep", role_hints=["qa-lead"])
    succ_id = await _seed_user(maker, "ho_fin_succ", role_hints=["qa-lead"])
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, depart_id, role="member")
    await _add_member(maker, pid, succ_id, role="member")
    await _login(client, "ho_fin_owner")
    r = await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": depart_id, "to_user_id": succ_id},
    )
    assert r.status_code == 200
    handoff_id = r.json()["handoff"]["id"]

    r = await client.post(f"/api/handoff/{handoff_id}/finalize")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["handoff"]["status"] == "finalized"
    assert body["handoff"]["finalized_at"] is not None


@pytest.mark.asyncio
async def test_for_successor_merges_predecessors(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "ho_merge_owner")
    await _set_profile(maker, owner_id, role_hints=["founder"])
    dep1 = await _seed_user(
        maker, "ho_merge_d1", role_hints=["engineering-lead"]
    )
    dep2 = await _seed_user(
        maker, "ho_merge_d2", role_hints=["engineering-lead"]
    )
    succ = await _seed_user(
        maker, "ho_merge_s", role_hints=["engineering-lead"]
    )
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, dep1, role="member")
    await _add_member(maker, pid, dep2, role="member")
    await _add_member(maker, pid, succ, role="member")

    # Seed each predecessor with a risk-management decision.
    await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=dep1,
        apply_actions=[{"kind": "close_risk"}],
    )
    await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=dep2,
        apply_actions=[{"kind": "close_risk"}],
    )

    await _login(client, "ho_merge_owner")
    for dep_id in (dep1, dep2):
        r = await client.post(
            f"/api/projects/{pid}/handoff/prepare",
            json={"from_user_id": dep_id, "to_user_id": succ},
        )
        handoff_id = r.json()["handoff"]["id"]
        r2 = await client.post(f"/api/handoff/{handoff_id}/finalize")
        assert r2.status_code == 200

    r = await client.get(f"/api/projects/{pid}/handoffs/for/{succ}")
    assert r.status_code == 200
    body = r.json()
    skills = {s["skill"]: s for s in body["inherited_routines"]}
    assert "risk-management" in skills
    assert skills["risk-management"]["evidence_count"] == 2
    assert len(body["predecessors"]) == 2


@pytest.mark.asyncio
async def test_for_successor_only_finalized(api_env):
    """Draft handoffs must NOT leak into the successor's inherited
    routines — only finalized rows do."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "ho_draft_owner")
    await _set_profile(maker, owner_id, role_hints=["founder"])
    dep = await _seed_user(maker, "ho_draft_dep", role_hints=["qa-lead"])
    succ = await _seed_user(maker, "ho_draft_succ", role_hints=["qa-lead"])
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, dep, role="member")
    await _add_member(maker, pid, succ, role="member")
    await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=dep,
        apply_actions=[{"kind": "close_risk"}],
    )

    await _login(client, "ho_draft_owner")
    await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": dep, "to_user_id": succ},
    )
    # Do NOT finalize.

    r = await client.get(f"/api/projects/{pid}/handoffs/for/{succ}")
    assert r.status_code == 200
    body = r.json()
    assert body["inherited_routines"] == []


@pytest.mark.asyncio
async def test_list_visibility_owner_vs_successor(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "ho_vis_owner")
    await _set_profile(maker, owner_id, role_hints=["founder"])
    dep = await _seed_user(maker, "ho_vis_dep", role_hints=["qa-lead"])
    succ = await _seed_user(maker, "ho_vis_succ", role_hints=["qa-lead"])
    other = await _seed_user(maker, "ho_vis_other", role_hints=["qa-lead"])
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, dep, role="member")
    await _add_member(maker, pid, succ, role="member")
    await _add_member(maker, pid, other, role="member")

    await _login(client, "ho_vis_owner")
    r = await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": dep, "to_user_id": succ},
    )
    assert r.status_code == 200

    # Owner sees all
    r = await client.get(f"/api/projects/{pid}/handoffs")
    assert r.json()["viewer_scope"] == "owner"
    assert len(r.json()["handoffs"]) == 1

    # Register 'succ' user properly so they can log in. The seed user
    # had password_hash='x' which can't be logged in via /login.
    client.cookies.clear()
    # Create a fresh registered user 'succ_live' and swap them in as a
    # member to emulate the successor scenario.
    succ_live = await _register(client, "ho_vis_succ_live")
    await _set_profile(maker, succ_live, role_hints=["qa-lead"])
    await _add_member(maker, pid, succ_live, role="member")
    # Prepare a handoff to the live successor so they have something
    # to see.
    await _login(client, "ho_vis_owner")
    await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": dep, "to_user_id": succ_live},
    )
    # Now switch to the live successor and check they see only their own.
    await _login(client, "ho_vis_succ_live")
    r = await client.get(f"/api/projects/{pid}/handoffs")
    assert r.status_code == 200
    body = r.json()
    assert body["viewer_scope"] == "successor"
    # Only the handoff targeting succ_live — not the one targeting succ.
    assert len(body["handoffs"]) == 1
    assert body["handoffs"][0]["to_user_id"] == succ_live


@pytest.mark.asyncio
async def test_prepare_same_user_rejected(api_env):
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "ho_same_owner")
    await _set_profile(maker, owner_id, role_hints=["founder"])
    me = await _seed_user(maker, "ho_same_me", role_hints=["qa-lead"])
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, me, role="member")
    await _login(client, "ho_same_owner")
    r = await client.post(
        f"/api/projects/{pid}/handoff/prepare",
        json={"from_user_id": me, "to_user_id": me},
    )
    assert r.status_code == 400
    assert "same_user" in r.text
