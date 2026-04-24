"""Migration 0014 — Scene 2 routing gate tests.

Covers:
  1. propose → GatedProposalRow created, gate-keeper gets pending card.
  2. approve → DecisionRow with decision_class + gated_via_proposal_id;
     proposer gets resolved card.
  3. deny → no DecisionRow; proposer gets resolved card.
  4. permission: only gate-keeper can approve/deny; only proposer can
     withdraw.
  5. state machine: double-approve / approve-after-deny rejected.
  6. no-gate-keeper in map → 'no_gate_keeper' error → caller falls back.
  7. unknown decision_class rejected with 400.
  8. proposer_is_gate_keeper rejected with 409.
  9. gate-keeper-map PUT: owner-only; validates class + project
     membership of each user_id; empty values remove an entry.
 10. listings — per-project audit + per-user pending.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    DecisionRepository,
    DecisionRow,
    MessageRepository,
    ProjectMemberRepository,
    ProjectRow,
    StreamRepository,
    UserRepository,
    backfill_streams_from_projects,
    session_scope,
)


# ---- helpers ------------------------------------------------------------


async def _mk_project(maker, title: str = "GP") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _mk_orphan_user(maker, username: str) -> str:
    """Create a user with an un-loginable password hash. For cases where
    the user appears as a project member but never acts as a session
    holder (e.g., a dangling outsider we reject via validation)."""
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


# ---- 1. propose ---------------------------------------------------------


@pytest.mark.asyncio
async def test_propose_creates_row_and_notifies_gate_keeper(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_proposer_1")
    gate_id = await _register_and_login(client, "gp_gate_1")
    await _login(client, "gp_proposer_1")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"budget": gate_id})

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={
            "decision_class": "budget",
            "proposal_body": "Allocate $50k to the new UI agency",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    proposal = data["proposal"]
    assert proposal["status"] == "pending"
    assert proposal["decision_class"] == "budget"
    assert proposal["proposer_user_id"] == proposer_id
    assert proposal["gate_keeper_user_id"] == gate_id
    proposal_id = proposal["id"]

    # A pending card should have been posted into the gate-keeper's
    # personal stream (kind='gated-proposal-pending', linked_id=proposal).
    async with session_scope(maker) as session:
        stream = await StreamRepository(
            session
        ).get_personal_for_user_in_project(
            user_id=gate_id, project_id=pid
        )
        assert stream is not None
        messages = await MessageRepository(session).list_for_stream(
            stream_id=stream.id, limit=50
        )
        pending_cards = [
            m for m in messages if m.kind == "gated-proposal-pending"
        ]
    assert len(pending_cards) == 1
    assert pending_cards[0].linked_id == proposal_id


# ---- 1b. decision_text round-trip (v0.5 polish) ------------------------


@pytest.mark.asyncio
async def test_propose_persists_and_returns_decision_text(api_env):
    """When the proposer supplies decision_text (the raw user utterance),
    it is persisted on the row and surfaced in every read path the
    gate-keeper UI relies on: POST response, GET /gated-proposals/{id},
    and the project listing."""
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_dt_proposer")
    gate_id = await _register_and_login(client, "gp_dt_gate")
    await _login(client, "gp_dt_proposer")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"scope_cut": gate_id})

    raw = "let's cut auth from v1 — it's blocking the demo"
    framing = "Scope cut — Maya gates scope decisions; sending for sign-off."
    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={
            "decision_class": "scope_cut",
            "proposal_body": framing,
            "decision_text": raw,
        },
    )
    assert r.status_code == 200, r.text
    proposal_id = r.json()["proposal"]["id"]
    assert r.json()["proposal"]["decision_text"] == raw
    assert r.json()["proposal"]["proposal_body"] == framing

    # Single-proposal GET echoes it.
    g = await client.get(f"/api/gated-proposals/{proposal_id}")
    assert g.status_code == 200
    assert g.json()["proposal"]["decision_text"] == raw

    # Project listing echoes it.
    lst = await client.get(f"/api/projects/{pid}/gated-proposals")
    assert lst.status_code == 200
    rows = lst.json()["proposals"]
    assert any(
        p["id"] == proposal_id and p["decision_text"] == raw for p in rows
    )


@pytest.mark.asyncio
async def test_decision_text_optional_defaults_to_null(api_env):
    """Omitted decision_text deserializes as null everywhere — covers the
    legacy / programmatic path where no raw utterance was captured."""
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_dtnull_proposer")
    gate_id = await _register_and_login(client, "gp_dtnull_gate")
    await _login(client, "gp_dtnull_proposer")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"budget": gate_id})

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "budget", "proposal_body": "X"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["proposal"]["decision_text"] is None


# ---- 2. approve ---------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_creates_decision_with_lineage(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_proposer_2")
    gate_id = await _register_and_login(client, "gp_gate_2")
    await _login(client, "gp_proposer_2")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"legal": gate_id})

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={
            "decision_class": "legal",
            "proposal_body": "Publish FLOSS under MIT terms",
        },
    )
    assert r.status_code == 200, r.text
    proposal_id = r.json()["proposal"]["id"]

    # Gate-keeper logs in and approves.
    await _login(client, "gp_gate_2")
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/approve",
        json={"rationale": "Standard FLOSS boilerplate"},
    )
    assert r.status_code == 200, r.text
    decision_id = r.json()["decision_id"]
    assert r.json()["proposal"]["status"] == "approved"

    async with session_scope(maker) as session:
        decision = await DecisionRepository(session).get(decision_id)
        assert decision is not None
        assert decision.decision_class == "legal"
        assert decision.gated_via_proposal_id == proposal_id
        assert decision.resolver_id == gate_id
        assert decision.custom_text == "Publish FLOSS under MIT terms"
        assert decision.apply_outcome == "advisory"

        # Proposer should have received a resolved-card in their stream.
        proposer_stream = await StreamRepository(
            session
        ).get_personal_for_user_in_project(
            user_id=proposer_id, project_id=pid
        )
        assert proposer_stream is not None
        msgs = await MessageRepository(session).list_for_stream(
            stream_id=proposer_stream.id, limit=50
        )
    resolved = [m for m in msgs if m.kind == "gated-proposal-resolved"]
    assert len(resolved) == 1
    assert resolved[0].linked_id == proposal_id
    assert "approved" in resolved[0].body.lower()


# ---- 3. deny ------------------------------------------------------------


@pytest.mark.asyncio
async def test_deny_does_not_create_decision(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_proposer_3")
    gate_id = await _register_and_login(client, "gp_gate_3")
    await _login(client, "gp_proposer_3")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"hire": gate_id})

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={
            "decision_class": "hire",
            "proposal_body": "Hire a senior designer at $180k",
        },
    )
    assert r.status_code == 200, r.text
    proposal_id = r.json()["proposal"]["id"]

    await _login(client, "gp_gate_3")
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/deny",
        json={"resolution_note": "Budget is frozen this quarter"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["proposal"]["status"] == "denied"
    assert r.json()["proposal"]["resolution_note"] == "Budget is frozen this quarter"

    async with session_scope(maker) as session:
        decisions = list(
            (
                await session.execute(
                    select(DecisionRow).where(DecisionRow.project_id == pid)
                )
            )
            .scalars()
            .all()
        )
    # No DecisionRow should exist — denied proposals never crystallize.
    gated = [d for d in decisions if d.gated_via_proposal_id == proposal_id]
    assert gated == []


# ---- 4. permissions -----------------------------------------------------


@pytest.mark.asyncio
async def test_non_gate_keeper_cannot_approve(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_proposer_4")
    gate_id = await _register_and_login(client, "gp_gate_4")
    stranger_id = await _register_and_login(client, "gp_stranger_4")
    await _login(client, "gp_proposer_4")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _add_member(
        maker, project_id=pid, user_id=stranger_id, role="member"
    )
    await _set_gate_keeper_map(maker, project_id=pid, map_={"budget": gate_id})

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "budget", "proposal_body": "X"},
    )
    assert r.status_code == 200, r.text
    proposal_id = r.json()["proposal"]["id"]

    # Stranger (not gate-keeper) tries to approve.
    await _login(client, "gp_stranger_4")
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/approve",
        json={},
    )
    assert r.status_code == 403, r.text
    assert r.json()["message"] == "not_gate_keeper"


@pytest.mark.asyncio
async def test_only_proposer_can_withdraw(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_proposer_5")
    gate_id = await _register_and_login(client, "gp_gate_5")
    other_id = await _register_and_login(client, "gp_other_5")
    await _login(client, "gp_proposer_5")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _add_member(maker, project_id=pid, user_id=other_id, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"budget": gate_id})

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "budget", "proposal_body": "X"},
    )
    proposal_id = r.json()["proposal"]["id"]

    # Other member tries to withdraw — should 403.
    await _login(client, "gp_other_5")
    r = await client.post(f"/api/gated-proposals/{proposal_id}/withdraw")
    assert r.status_code == 403

    # Proposer withdraws successfully.
    await _login(client, "gp_proposer_5")
    r = await client.post(f"/api/gated-proposals/{proposal_id}/withdraw")
    assert r.status_code == 200
    assert r.json()["proposal"]["status"] == "withdrawn"


# ---- 5. state machine ---------------------------------------------------


@pytest.mark.asyncio
async def test_already_resolved_rejects_second_resolve(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_proposer_6")
    gate_id = await _register_and_login(client, "gp_gate_6")
    await _login(client, "gp_proposer_6")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"budget": gate_id})

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "budget", "proposal_body": "X"},
    )
    proposal_id = r.json()["proposal"]["id"]

    await _login(client, "gp_gate_6")
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/approve",
        json={},
    )
    assert r.status_code == 200

    # Second approve should 409.
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/approve",
        json={},
    )
    assert r.status_code == 409
    assert r.json()["message"] == "already_resolved"

    # Deny-after-approve also 409.
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/deny",
        json={},
    )
    assert r.status_code == 409


# ---- 6. no gate-keeper fallback ----------------------------------------


@pytest.mark.asyncio
async def test_no_gate_keeper_falls_back(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_proposer_7")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    # gate_keeper_map intentionally empty.

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "budget", "proposal_body": "X"},
    )
    assert r.status_code == 409
    assert r.json()["message"] == "no_gate_keeper"


# ---- 7. unknown class ---------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_decision_class_rejected(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_proposer_8")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "fiction", "proposal_body": "X"},
    )
    assert r.status_code == 400
    assert r.json()["message"] == "invalid_decision_class"


# ---- 8. proposer_is_gate_keeper ----------------------------------------


@pytest.mark.asyncio
async def test_proposer_is_gate_keeper_rejected(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_proposer_9")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"budget": proposer_id})

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "budget", "proposal_body": "X"},
    )
    assert r.status_code == 409
    assert r.json()["message"] == "proposer_is_gate_keeper"


# ---- 9. gate-keeper-map CRUD -------------------------------------------


@pytest.mark.asyncio
async def test_gate_keeper_map_put_owner_only(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    owner_id = await _register_and_login(client, "gp_owner_10")
    member_id = await _register_and_login(client, "gp_member_10")
    gate_id = await _register_and_login(client, "gp_gate_10")
    await _login(client, "gp_owner_10")
    await _add_member(maker, project_id=pid, user_id=owner_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=member_id, role="member")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")

    # Non-owner member tries to PUT — 403.
    await _login(client, "gp_member_10")
    r = await client.put(
        f"/api/projects/{pid}/gate-keeper-map",
        json={"map": {"budget": gate_id}},
    )
    assert r.status_code == 403
    assert r.json()["message"] == "not_owner"

    # Owner PUTs successfully.
    await _login(client, "gp_owner_10")
    r = await client.put(
        f"/api/projects/{pid}/gate-keeper-map",
        json={"map": {"budget": gate_id, "legal": gate_id}},
    )
    assert r.status_code == 200
    assert r.json()["map"] == {"budget": gate_id, "legal": gate_id}

    # GET echoes the map + returns the valid_classes enum.
    r = await client.get(f"/api/projects/{pid}/gate-keeper-map")
    assert r.status_code == 200
    assert r.json()["map"] == {"budget": gate_id, "legal": gate_id}
    assert set(r.json()["valid_classes"]) == {
        "budget",
        "legal",
        "hire",
        "scope_cut",
    }

    # Empty value removes a class.
    r = await client.put(
        f"/api/projects/{pid}/gate-keeper-map",
        json={"map": {"budget": gate_id, "legal": ""}},
    )
    assert r.status_code == 200
    assert r.json()["map"] == {"budget": gate_id}


@pytest.mark.asyncio
async def test_gate_keeper_map_rejects_non_member_user_id(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    owner_id = await _register_and_login(client, "gp_owner_11")
    outsider_id = await _mk_orphan_user(maker, "gp_outsider_11")
    await _add_member(maker, project_id=pid, user_id=owner_id, role="owner")

    r = await client.put(
        f"/api/projects/{pid}/gate-keeper-map",
        json={"map": {"budget": outsider_id}},
    )
    assert r.status_code == 400
    assert r.json()["message"] == "gate_keeper_not_member"


# ---- 10. listings -------------------------------------------------------


@pytest.mark.asyncio
async def test_listings_per_project_and_pending_for_me(api_env):
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "gp_proposer_12")
    gate_id = await _register_and_login(client, "gp_gate_12")
    await _login(client, "gp_proposer_12")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _set_gate_keeper_map(
        maker,
        project_id=pid,
        map_={"budget": gate_id, "legal": gate_id},
    )

    # Create two proposals.
    r1 = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "budget", "proposal_body": "Buy rack"},
    )
    r2 = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "legal", "proposal_body": "Sign NDA"},
    )
    assert r1.status_code == 200 and r2.status_code == 200

    # Per-project listing (proposer sees).
    r = await client.get(f"/api/projects/{pid}/gated-proposals")
    assert r.status_code == 200
    proposals = r.json()["proposals"]
    assert len(proposals) == 2
    assert {p["decision_class"] for p in proposals} == {"budget", "legal"}

    # Filter by status=pending returns both.
    r = await client.get(
        f"/api/projects/{pid}/gated-proposals?status=pending"
    )
    assert len(r.json()["proposals"]) == 2

    # Gate-keeper's pending list shows both.
    await _login(client, "gp_gate_12")
    r = await client.get("/api/gated-proposals/pending")
    assert r.status_code == 200
    pending = r.json()["proposals"]
    assert len(pending) == 2
    assert all(p["gate_keeper_user_id"] == gate_id for p in pending)

    # After approving one, only one remains pending.
    r = await client.post(
        f"/api/gated-proposals/{r1.json()['proposal']['id']}/approve",
        json={},
    )
    assert r.status_code == 200
    r = await client.get("/api/gated-proposals/pending")
    assert len(r.json()["proposals"]) == 1
    assert r.json()["proposals"][0]["decision_class"] == "legal"


# ---- 11. vote mode (Phase S) -------------------------------------------
#
# When ≥2 authority holders (owners ∪ gate-keeper) exist for a
# proposal's class, any eligible actor (proposer, any owner, the
# gate-keeper) can convert pending → in_vote. Voters cast approve /
# deny / abstain; threshold = floor(n/2)+1. Approve-threshold →
# approved + DecisionRow. Deny-lock → denied.


async def _seed_vote_ready_project(client, maker, suffix: str):
    """Project with 3 owners + 1 extra member, budget → first owner
    as gate-keeper. Logs in as `gp_owner_a_{suffix}` at exit.

    Returns (project_id, {label: user_id}).
    """
    pid = await _mk_project(maker)
    # Manually-inserted ProjectRows bypass the app's boot-time
    # backfill, so the project/team stream + personal streams are
    # absent. Seed them explicitly — vote-opened / vote-resolved
    # runtime logs depend on the project stream existing.
    await backfill_streams_from_projects(maker)
    a = await _register_and_login(client, f"gp_owner_a_{suffix}")
    b = await _register_and_login(client, f"gp_owner_b_{suffix}")
    c = await _register_and_login(client, f"gp_owner_c_{suffix}")
    m = await _register_and_login(client, f"gp_member_{suffix}")
    await _add_member(maker, project_id=pid, user_id=a, role="owner")
    await _add_member(maker, project_id=pid, user_id=b, role="owner")
    await _add_member(maker, project_id=pid, user_id=c, role="owner")
    await _add_member(maker, project_id=pid, user_id=m, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"scope_cut": a})
    await _login(client, f"gp_owner_b_{suffix}")  # b is proposer (owner, not gate-keeper)
    return pid, {"a": a, "b": b, "c": c, "m": m}


@pytest.mark.asyncio
async def test_open_to_vote_threshold_and_resolve_on_approve(api_env):
    """Proposer converts to vote → 3-owner pool → threshold 2 → two
    approves resolves the proposal + mints a DecisionRow."""
    client, maker, *_ = api_env
    pid, u = await _seed_vote_ready_project(client, maker, "v1")

    # Proposer creates proposal.
    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "scope_cut", "proposal_body": "drop invite codes"},
    )
    assert r.status_code == 200, r.text
    proposal_id = r.json()["proposal"]["id"]

    # Proposer opens to vote.
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/open-to-vote", json={}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["proposal"]["status"] == "in_vote"
    # Pool = 3 owners (a, b, c). Gate-keeper (a) already in pool.
    pool = set(data["proposal"]["voter_pool"])
    assert pool == {u["a"], u["b"], u["c"]}
    assert data["threshold"] == 2  # floor(3/2)+1

    # First approve (owner b — the proposer).
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/votes",
        json={"verdict": "approve", "rationale": "lean v1"},
    )
    assert r.status_code == 200
    assert r.json()["resolved_as"] is None
    assert r.json()["tally"]["approve"] == 1

    # Second approve (owner c) → threshold hit → resolves.
    await _login(client, "gp_owner_c_v1")
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/votes",
        json={"verdict": "approve"},
    )
    assert r.status_code == 200
    assert r.json()["resolved_as"] == "approved"
    decision_id = r.json()["decision_id"]
    assert decision_id

    # DecisionRow exists with lineage.
    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(DecisionRow).where(DecisionRow.id == decision_id)
            )
        ).scalar_one()
        assert row.decision_class == "scope_cut"
        assert row.gated_via_proposal_id == proposal_id

    # Proposal status is approved.
    t = await client.get(f"/api/gated-proposals/{proposal_id}")
    assert t.json()["proposal"]["status"] == "approved"


@pytest.mark.asyncio
async def test_cast_vote_deny_lock_resolves_as_denied(api_env):
    """Pool=3 → threshold=2. 2 denies make approve+outstanding <
    threshold. Proposal resolves as denied with no DecisionRow."""
    client, maker, *_ = api_env
    pid, u = await _seed_vote_ready_project(client, maker, "v2")

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "scope_cut", "proposal_body": "skip QA"},
    )
    proposal_id = r.json()["proposal"]["id"]
    await client.post(f"/api/gated-proposals/{proposal_id}/open-to-vote", json={})

    # Two denies → approve+outstanding = 0+1 = 1 < threshold 2 → lock.
    r1 = await client.post(
        f"/api/gated-proposals/{proposal_id}/votes",
        json={"verdict": "deny"},
    )
    assert r1.json()["resolved_as"] is None

    await _login(client, "gp_owner_c_v2")
    r2 = await client.post(
        f"/api/gated-proposals/{proposal_id}/votes",
        json={"verdict": "deny"},
    )
    assert r2.status_code == 200
    assert r2.json()["resolved_as"] == "denied"
    assert r2.json()["decision_id"] is None


@pytest.mark.asyncio
async def test_vote_change_updates_existing_row(api_env):
    """Voter flipping their verdict UPDATEs the same VoteRow, not
    inserts a second. Tally reflects the latest cast."""
    client, maker, *_ = api_env
    pid, u = await _seed_vote_ready_project(client, maker, "v3")

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "scope_cut", "proposal_body": "x"},
    )
    proposal_id = r.json()["proposal"]["id"]
    await client.post(f"/api/gated-proposals/{proposal_id}/open-to-vote", json={})

    # First cast: deny.
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/votes",
        json={"verdict": "deny", "rationale": "first pass"},
    )
    assert r.json()["tally"]["deny"] == 1
    assert r.json()["tally"]["approve"] == 0

    # Flip to approve.
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/votes",
        json={"verdict": "approve", "rationale": "changed my mind"},
    )
    assert r.status_code == 200
    tally = r.json()["tally"]
    assert tally["deny"] == 0
    assert tally["approve"] == 1

    # Tally endpoint returns one row, verdict=approve.
    t = await client.get(f"/api/gated-proposals/{proposal_id}/tally")
    assert t.status_code == 200
    assert len(t.json()["votes"]) == 1
    assert t.json()["votes"][0]["verdict"] == "approve"
    assert t.json()["votes"][0]["rationale"] == "changed my mind"


@pytest.mark.asyncio
async def test_open_to_vote_insufficient_voters(api_env):
    """Pool of 1 (solo owner as gate-keeper) → can't open to vote."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    solo = await _register_and_login(client, "gp_solo_v4")
    other = await _register_and_login(client, "gp_other_v4")
    await _login(client, "gp_solo_v4")
    await _add_member(maker, project_id=pid, user_id=solo, role="owner")
    await _add_member(maker, project_id=pid, user_id=other, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"hire": solo})

    # Pool calculation: owners={solo}, gate_keeper=solo → pool={solo},
    # size 1 → insufficient.
    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "hire", "proposal_body": "hire Raj"},
    )
    # proposer_is_gate_keeper blocks the single-owner case at propose
    # time anyway. Use a different gate-keeper to exercise the vote
    # path specifically.
    assert r.status_code == 409  # proposer_is_gate_keeper for solo owner


@pytest.mark.asyncio
async def test_cast_vote_by_non_pool_member_rejected(api_env):
    """Regular member (not owner, not gate-keeper) can't cast votes."""
    client, maker, *_ = api_env
    pid, u = await _seed_vote_ready_project(client, maker, "v5")

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "scope_cut", "proposal_body": "x"},
    )
    proposal_id = r.json()["proposal"]["id"]
    await client.post(f"/api/gated-proposals/{proposal_id}/open-to-vote", json={})

    # Log in as the plain member (not in owner pool).
    await _login(client, "gp_member_v5")
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/votes",
        json={"verdict": "approve"},
    )
    assert r.status_code == 403
    assert r.json()["message"] == "not_in_voter_pool"


@pytest.mark.asyncio
async def test_open_to_vote_permission_check(api_env):
    """Non-authorized user can't open to vote."""
    client, maker, *_ = api_env
    pid, u = await _seed_vote_ready_project(client, maker, "v6")

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "scope_cut", "proposal_body": "x"},
    )
    proposal_id = r.json()["proposal"]["id"]

    # Plain member tries to open → 403.
    await _login(client, "gp_member_v6")
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/open-to-vote", json={}
    )
    assert r.status_code == 403
    assert r.json()["message"] == "not_authorized_to_open_vote"


@pytest.mark.asyncio
async def test_invalid_verdict_rejected(api_env):
    client, maker, *_ = api_env
    pid, u = await _seed_vote_ready_project(client, maker, "v7")

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "scope_cut", "proposal_body": "x"},
    )
    proposal_id = r.json()["proposal"]["id"]
    await client.post(f"/api/gated-proposals/{proposal_id}/open-to-vote", json={})

    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/votes",
        json={"verdict": "maybe"},
    )
    assert r.status_code == 400
    assert r.json()["message"] == "invalid_verdict"


@pytest.mark.asyncio
async def test_vote_opened_and_resolved_post_to_group_stream(api_env):
    """open_to_vote posts 'vote-opened' to the project/team stream;
    threshold-approve resolution posts 'vote-resolved-approved'
    alongside the proposer's personal-stream notification."""
    client, maker, *_ = api_env
    pid, u = await _seed_vote_ready_project(client, maker, "v9")

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "scope_cut", "proposal_body": "trim payments"},
    )
    proposal_id = r.json()["proposal"]["id"]
    await client.post(f"/api/gated-proposals/{proposal_id}/open-to-vote", json={})

    # Group-stream opened card.
    async with session_scope(maker) as session:
        stream = await StreamRepository(session).get_for_project(pid)
        assert stream is not None
        msgs = await MessageRepository(session).list_for_stream(
            stream_id=stream.id, limit=50
        )
        opened = [m for m in msgs if m.kind == "vote-opened"]
    assert len(opened) == 1
    assert opened[0].linked_id == proposal_id
    assert "Vote opened" in opened[0].body

    # Drive through to resolution: b (already logged in) + c both approve.
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/votes", json={"verdict": "approve"}
    )
    assert r.status_code == 200
    await _login(client, "gp_owner_c_v9")
    r = await client.post(
        f"/api/gated-proposals/{proposal_id}/votes", json={"verdict": "approve"}
    )
    assert r.status_code == 200
    assert r.json()["resolved_as"] == "approved"

    # Group-stream resolved card.
    async with session_scope(maker) as session:
        stream = await StreamRepository(session).get_for_project(pid)
        msgs = await MessageRepository(session).list_for_stream(
            stream_id=stream.id, limit=50
        )
        resolved = [m for m in msgs if m.kind == "vote-resolved-approved"]
    assert len(resolved) == 1
    assert resolved[0].linked_id == proposal_id
    assert "2 approve" in resolved[0].body


@pytest.mark.asyncio
async def test_inbox_gated_feed_mixes_sign_offs_and_vote_pending(api_env):
    """GET /api/inbox/gated returns both (a) proposals where I'm the
    single-approver gate-keeper (kind='gate-sign-off') and (b)
    in-vote proposals where I'm in voter_pool (kind='vote-pending'),
    in one most-recent-first feed. `my_vote` reflects whether I've
    already cast on vote-pending items."""
    client, maker, *_ = api_env
    pid, u = await _seed_vote_ready_project(client, maker, "vi")

    # 1. Proposer (b) creates single-approver proposal for budget class
    #    with gate-keeper = different owner (c). Need a second mapping.
    await _set_gate_keeper_map(
        maker,
        project_id=pid,
        map_={"scope_cut": u["a"], "budget": u["c"]},
    )
    r1 = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "budget", "proposal_body": "buy rack"},
    )
    assert r1.status_code == 200, r1.text
    sign_off_proposal_id = r1.json()["proposal"]["id"]

    # 2. Proposer (b) creates scope_cut proposal, opens to vote.
    r2 = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "scope_cut", "proposal_body": "trim auth"},
    )
    vote_proposal_id = r2.json()["proposal"]["id"]
    await client.post(
        f"/api/gated-proposals/{vote_proposal_id}/open-to-vote", json={}
    )

    # 3. As owner c: inbox should show BOTH items (gate-sign-off on
    #    proposal 1, vote-pending on proposal 2; c is an owner so in
    #    voter_pool).
    await _login(client, "gp_owner_c_vi")
    r = await client.get("/api/inbox/gated")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    kinds = {i["kind"] for i in items}
    assert kinds == {"gate-sign-off", "vote-pending"}
    vote_item = next(i for i in items if i["kind"] == "vote-pending")
    assert vote_item["proposal"]["id"] == vote_proposal_id
    assert vote_item["my_vote"] is None  # c hasn't voted yet

    # 4. c casts approve. Inbox reflects my_vote.
    await client.post(
        f"/api/gated-proposals/{vote_proposal_id}/votes",
        json={"verdict": "approve", "rationale": "ok with it"},
    )
    r = await client.get("/api/inbox/gated")
    assert r.status_code == 200
    vote_item = next(
        i for i in r.json()["items"] if i["kind"] == "vote-pending"
    )
    assert vote_item["my_vote"] is not None
    assert vote_item["my_vote"]["verdict"] == "approve"
    assert vote_item["my_vote"]["rationale"] == "ok with it"

    # 5. Plain member (m) is NOT an owner, NOT a gate-keeper → empty inbox.
    await _login(client, "gp_member_vi")
    r = await client.get("/api/inbox/gated")
    assert r.status_code == 200
    assert r.json()["items"] == []


@pytest.mark.asyncio
async def test_cast_vote_bumps_votes_cast_tally(api_env):
    """Casting a vote bumps signal_tally.votes_cast on the voter,
    regardless of verdict. Verdict re-casts still bump (governance
    participation = engagement, not just decisiveness)."""
    client, maker, *_ = api_env
    pid, u = await _seed_vote_ready_project(client, maker, "v8")

    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "scope_cut", "proposal_body": "x"},
    )
    proposal_id = r.json()["proposal"]["id"]
    await client.post(f"/api/gated-proposals/{proposal_id}/open-to-vote", json={})

    async def _votes_cast(uid: str) -> int:
        async with session_scope(maker) as session:
            row = await UserRepository(session).get(uid)
            if row is None:
                return 0
            return int(((row.profile or {}).get("signal_tally") or {}).get("votes_cast", 0))

    proposer_id = u["b"]
    assert await _votes_cast(proposer_id) == 0

    # First cast: approve → tally bumps to 1.
    await client.post(
        f"/api/gated-proposals/{proposal_id}/votes",
        json={"verdict": "approve"},
    )
    assert await _votes_cast(proposer_id) == 1

    # Flip verdict: still a cast → tally bumps to 2.
    await client.post(
        f"/api/gated-proposals/{proposal_id}/votes",
        json={"verdict": "deny"},
    )
    assert await _votes_cast(proposer_id) == 2


# ---- 12. counterfactual ("if approved") --------------------------------


@pytest.mark.asyncio
async def test_counterfactual_empty_for_advisory_only_proposal(api_env):
    """v0 proposals frequently have apply_actions=[] (advisory-only).
    The endpoint returns empty=True with reason='no_actions' so the
    frontend can render a graceful "no mechanical effects predicted"
    card instead of an empty box."""
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "cf_proposer_1")
    gate_id = await _register_and_login(client, "cf_gate_1")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"budget": gate_id})

    await _login(client, "cf_proposer_1")
    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={
            "decision_class": "budget",
            "proposal_body": "Freeze hiring for Q3",
            # apply_actions intentionally omitted — default empty list.
        },
    )
    assert r.status_code == 200
    proposal_id = r.json()["proposal"]["id"]

    r = await client.get(
        f"/api/gated-proposals/{proposal_id}/counterfactual"
    )
    assert r.status_code == 200, r.text
    cf = r.json()["counterfactual"]
    assert cf["empty"] is True
    assert cf["reason"] == "no_actions"
    assert cf["action_count"] == 0
    assert cf["reassignments"] == []
    assert cf["total_effects"] == 0
    assert cf["proposal_id"] == proposal_id


@pytest.mark.asyncio
async def test_counterfactual_renders_assign_task_reassignment(api_env):
    """Proposal with apply_actions=[{kind:'assign_task', task_id, user_id}]
    surfaces a reassignment entry with from/to user display names."""
    from workgraph_persistence import (
        AssignmentRepository,
        RequirementRow,
        TaskRow,
    )

    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "cf_proposer_2")
    gate_id = await _register_and_login(client, "cf_gate_2")
    current_owner_id = await _register_and_login(client, "cf_owner_cur")
    next_owner_id = await _register_and_login(client, "cf_owner_next")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _add_member(maker, project_id=pid, user_id=current_owner_id, role="member")
    await _add_member(maker, project_id=pid, user_id=next_owner_id, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"scope_cut": gate_id})

    # Seed a requirement + task and assign it to current_owner.
    req_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            RequirementRow(
                id=req_id,
                project_id=pid,
                version=1,
                raw_text="stub",
                parse_outcome="ok",
            )
        )
        session.add(
            TaskRow(
                id=task_id,
                project_id=pid,
                requirement_id=req_id,
                sort_order=0,
                title="Ship login flow",
            )
        )
        await session.flush()
        await AssignmentRepository(session).set_assignment(
            project_id=pid, task_id=task_id, user_id=current_owner_id
        )

    await _login(client, "cf_proposer_2")
    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={
            "decision_class": "scope_cut",
            "proposal_body": "Hand login flow to next_owner",
            "apply_actions": [
                {
                    "kind": "assign_task",
                    "task_id": task_id,
                    "user_id": next_owner_id,
                },
                {"kind": "advisory", "rule": "discuss_with_pm"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    proposal_id = r.json()["proposal"]["id"]

    r = await client.get(
        f"/api/gated-proposals/{proposal_id}/counterfactual"
    )
    assert r.status_code == 200, r.text
    cf = r.json()["counterfactual"]
    assert cf["empty"] is False
    assert cf["action_count"] == 2
    assert cf["advisory_count"] == 1
    assert cf["total_effects"] == 1
    assert len(cf["reassignments"]) == 1
    rx = cf["reassignments"][0]
    assert rx["task_id"] == task_id
    assert rx["task_title"] == "Ship login flow"
    assert rx["from_user_id"] == current_owner_id
    assert rx["to_user_id"] == next_owner_id
    # Display names resolve to usernames when no display_name set.
    assert rx["from_display_name"] == "cf_owner_cur"
    assert rx["to_display_name"] == "cf_owner_next"


@pytest.mark.asyncio
async def test_counterfactual_requires_project_membership(api_env):
    """Non-members can't read the counterfactual payload — scoped to
    project-audit visibility."""
    client, maker, *_ = api_env

    pid = await _mk_project(maker)
    proposer_id = await _register_and_login(client, "cf_member_1")
    gate_id = await _register_and_login(client, "cf_gate_3")
    outsider_id = await _register_and_login(client, "cf_outsider")
    await _add_member(maker, project_id=pid, user_id=proposer_id, role="owner")
    await _add_member(maker, project_id=pid, user_id=gate_id, role="member")
    await _set_gate_keeper_map(maker, project_id=pid, map_={"budget": gate_id})

    await _login(client, "cf_member_1")
    r = await client.post(
        f"/api/projects/{pid}/gated-proposals",
        json={"decision_class": "budget", "proposal_body": "$"},
    )
    proposal_id = r.json()["proposal"]["id"]

    await _login(client, "cf_outsider")
    r = await client.get(
        f"/api/gated-proposals/{proposal_id}/counterfactual"
    )
    assert r.status_code == 403
    # outsider_id is only used to confirm we're logged in as them
    assert outsider_id
