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
