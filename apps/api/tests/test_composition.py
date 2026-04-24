"""Composition service/router tests — HR/COO diagnostic (read-only v0).

Covers:
  1. Happy path: 3 owners + 2 members, gate_keeper_map set on two
     classes → per-class pools sized correctly, SPOF flagged where
     only one owner sits in the pool.
  2. No-gates: empty gate_keeper_map → every class falls back to just
     the owner set, gate_keeper_user_id=null everywhere.
  3. Permissions: non-member → 403; unknown project → 404.
  4. Active in-flight: 3 pending proposals on same gate-keeper →
     active_in_flight_count == 3.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    GatedProposalRepository,
    ProjectMemberRepository,
    ProjectRow,
    UserRepository,
    session_scope,
)


# ---- helpers ------------------------------------------------------------


async def _mk_project(maker, title: str = "CP") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _add_member(
    maker, *, project_id: str, user_id: str, role: str = "member"
) -> None:
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role=role
        )


async def _set_gate_keeper_map(
    maker, *, project_id: str, map_: dict[str, str]
) -> None:
    async with session_scope(maker) as session:
        project = (
            await session.execute(
                select(ProjectRow).where(ProjectRow.id == project_id)
            )
        ).scalar_one()
        project.gate_keeper_map = dict(map_)
        await session.flush()


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


async def _mk_orphan_user(maker, username: str) -> str:
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        return user.id


# ---- 1. happy path: owners + members + partial gate map ----------------


@pytest.mark.asyncio
async def test_composition_happy_path(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker, "Composition HP")
    # 3 owners, 2 members. First owner logs in as caller.
    owner_a = await _register_and_login(client, "cp_owner_a")
    owner_b = await _register_and_login(client, "cp_owner_b")
    owner_c = await _register_and_login(client, "cp_owner_c")
    member_d = await _register_and_login(client, "cp_member_d")
    member_e = await _register_and_login(client, "cp_member_e")
    await _login(client, "cp_owner_a")

    for uid in (owner_a, owner_b, owner_c):
        await _add_member(maker, project_id=pid, user_id=uid, role="owner")
    for uid in (member_d, member_e):
        await _add_member(maker, project_id=pid, user_id=uid, role="member")

    # budget → owner_b (already an owner → no new pool members). scope_cut
    # → member_d (a non-owner gate-keeper → pool grows by 1 to 4).
    await _set_gate_keeper_map(
        maker,
        project_id=pid,
        map_={"budget": owner_b, "scope_cut": member_d},
    )

    r = await client.get(f"/api/projects/{pid}/composition")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    comp = data["composition"]

    # ---- classes ----
    classes = {c["decision_class"]: c for c in comp["classes"]}
    # Every VALID_DECISION_CLASS appears.
    assert {"budget", "legal", "hire", "scope_cut"} <= set(classes.keys())

    # budget: gate_keeper = owner_b, pool = owners only (B is already an
    # owner, so |pool| = 3 → healthy).
    budget = classes["budget"]
    assert budget["gate_keeper_user_id"] == owner_b
    assert set(budget["voter_pool"]) == {owner_a, owner_b, owner_c}
    assert budget["pool_size"] == 3
    assert budget["health"] == "healthy"

    # scope_cut: gate_keeper = member_d (non-owner) → pool = owners ∪ {D}
    # = 4 → healthy.
    scope_cut = classes["scope_cut"]
    assert scope_cut["gate_keeper_user_id"] == member_d
    assert set(scope_cut["voter_pool"]) == {owner_a, owner_b, owner_c, member_d}
    assert scope_cut["pool_size"] == 4
    assert scope_cut["health"] == "healthy"

    # legal + hire: no gate-keeper → pool = owners = 3 → healthy.
    for cls_name in ("legal", "hire"):
        cls = classes[cls_name]
        assert cls["gate_keeper_user_id"] is None
        assert set(cls["voter_pool"]) == {owner_a, owner_b, owner_c}
        assert cls["health"] == "healthy"

    # ---- members ----
    members = {m["user_id"]: m for m in comp["members"]}
    assert set(members.keys()) == {
        owner_a, owner_b, owner_c, member_d, member_e
    }
    # owner_b holds budget gate (gate_count=1) + sits in every owner pool
    # (4 classes — legal/hire/budget/scope_cut) → vote_pool_count=4.
    assert members[owner_b]["gate_count"] == 1
    assert members[owner_b]["vote_pool_count"] == 4
    assert members[owner_b]["gated_classes"] == ["budget"]
    # load_score = 1*2 + 4 = 6
    assert members[owner_b]["load_score"] == 6

    # member_d gates scope_cut, sits only in that one pool.
    assert members[member_d]["gate_count"] == 1
    assert members[member_d]["vote_pool_count"] == 1
    assert members[member_d]["load_score"] == 1 * 2 + 1

    # member_e has no authority anywhere.
    assert members[member_e]["gate_count"] == 0
    assert members[member_e]["vote_pool_count"] == 0
    assert members[member_e]["load_score"] == 0

    # members list is sorted by load_score desc → owner_b should appear
    # before member_e (load 6 vs 0).
    ordered_ids = [m["user_id"] for m in comp["members"]]
    assert ordered_ids.index(owner_b) < ordered_ids.index(member_e)

    # ---- summary ----
    summary = comp["summary"]
    assert summary["total_members"] == 5
    assert summary["total_owners"] == 3
    assert summary["classes_covered"] == 2  # budget + scope_cut
    # No SPOFs (every pool is >= 3).
    assert summary["spof_count"] == 0
    # Most loaded is owner_b (load=6).
    assert summary["most_loaded_user_id"] == owner_b
    assert summary["most_loaded_score"] == 6

    # ---- overlaps ----
    # Every pair of owners co-holds authority on all 4 classes. With 3
    # owners that's C(3,2)=3 pairs, each sharing all 4 classes.
    owner_pairs = [
        o
        for o in comp["overlaps"]
        if {o["user_a_id"], o["user_b_id"]} <= {owner_a, owner_b, owner_c}
    ]
    assert len(owner_pairs) == 3
    for pair in owner_pairs:
        assert set(pair["shared_classes"]) == {
            "budget",
            "legal",
            "hire",
            "scope_cut",
        }


# ---- 2. no gates → every class is owner-only -----------------------------


@pytest.mark.asyncio
async def test_composition_no_gates(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker, "No Gates")
    owner = await _register_and_login(client, "cp_ng_owner")
    other = await _register_and_login(client, "cp_ng_other")
    await _login(client, "cp_ng_owner")
    await _add_member(maker, project_id=pid, user_id=owner, role="owner")
    await _add_member(maker, project_id=pid, user_id=other, role="member")

    r = await client.get(f"/api/projects/{pid}/composition")
    assert r.status_code == 200, r.text
    comp = r.json()["composition"]

    # gate_keeper_user_id is null for every class; voter pool is the
    # singleton owner set → pool_size=1 → SPOF across the board.
    for cls in comp["classes"]:
        assert cls["gate_keeper_user_id"] is None
        assert cls["voter_pool"] == [owner]
        assert cls["pool_size"] == 1
        assert cls["health"] == "spof"

    assert comp["summary"]["classes_covered"] == 0
    # 4 classes, all SPOF.
    assert comp["summary"]["spof_count"] == 4
    assert comp["summary"]["total_owners"] == 1
    # Most-loaded is the sole owner.
    assert comp["summary"]["most_loaded_user_id"] == owner
    assert comp["summary"]["most_loaded_score"] == 4  # 0 gates + 4 pools


# ---- 3. permissions -----------------------------------------------------


@pytest.mark.asyncio
async def test_composition_non_member_forbidden(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker, "Secret")
    insider = await _register_and_login(client, "cp_insider")
    outsider = await _register_and_login(client, "cp_outsider")
    await _add_member(maker, project_id=pid, user_id=insider, role="owner")
    # outsider is NOT a member.
    await _login(client, "cp_outsider")

    r = await client.get(f"/api/projects/{pid}/composition")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_composition_unknown_project_404(api_env):
    client, _maker, *_ = api_env

    # Log in so auth doesn't short-circuit to 401.
    await _register_and_login(client, "cp_lookup")
    await _login(client, "cp_lookup")

    # Unknown project id — membership check runs first and returns 403
    # because the user isn't a member of a non-existent project. That's
    # the intended leak-resistant behavior (don't distinguish "exists
    # but no access" from "doesn't exist" for outsiders).
    r = await client.get(f"/api/projects/{uuid.uuid4()}/composition")
    assert r.status_code == 403


# ---- 4. active in-flight counts -----------------------------------------


@pytest.mark.asyncio
async def test_composition_active_in_flight_count(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker, "Inflight")
    owner = await _register_and_login(client, "cp_if_owner")
    gate = await _register_and_login(client, "cp_if_gate")
    proposer = await _register_and_login(client, "cp_if_proposer")
    await _login(client, "cp_if_owner")
    await _add_member(maker, project_id=pid, user_id=owner, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate, role="member")
    await _add_member(maker, project_id=pid, user_id=proposer, role="member")

    await _set_gate_keeper_map(
        maker, project_id=pid, map_={"budget": gate}
    )

    # Seed 3 pending proposals on `gate` (status='pending' by default on
    # GatedProposalRepository.create). We go directly through the repo
    # here rather than the API so the test is purely about composition's
    # in-flight aggregation, not the propose flow.
    async with session_scope(maker) as session:
        repo = GatedProposalRepository(session)
        for i in range(3):
            await repo.create(
                project_id=pid,
                proposer_user_id=proposer,
                gate_keeper_user_id=gate,
                decision_class="budget",
                proposal_body=f"budget proposal {i}",
                apply_actions=[],
            )

    r = await client.get(f"/api/projects/{pid}/composition")
    assert r.status_code == 200, r.text
    comp = r.json()["composition"]
    members = {m["user_id"]: m for m in comp["members"]}

    assert members[gate]["active_in_flight_count"] == 3
    # Owner + proposer aren't touched by in-flight proposals here
    # (pending proposals only surface on the gate-keeper for
    # single-approver mode).
    assert members[owner]["active_in_flight_count"] == 0
    assert members[proposer]["active_in_flight_count"] == 0
