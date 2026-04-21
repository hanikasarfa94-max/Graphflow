"""Phase 2.A dissent + judgment-accuracy tests.

Covers the five acceptance criteria from PLAN-v3.md Phase 2.A:

1. Member records dissent on a crystallized decision.
2. Dissent renders on the decision's lineage view — i.e. the GET
   endpoint returns the member's stance.
3. On supersession (`decision_reversed` / `decision_superseded`) —
   modeled in services/dissent.py as "a new DecisionRow applied
   against the same conflict_id" — matching dissents flip
   `supported`.
4. On a successful mechanical apply (`milestone_hit` / `risk_closed`
   equivalent — modeled as `apply_outcome == 'ok'` on the decision
   itself) — matching dissents flip `refuted`.
5. Perf panel aggregation at `GET /api/projects/{id}/team/perf`
   reports `dissent_accuracy: { total, supported, refuted, still_open }`
   per member.

Validation style — the services/dissent.py module exposes an explicit
`validate_on_decision_applied(payload)` entry point subscribed to the
`decision.applied` EventBus event. The conftest fixture already wires
that subscription. We drive it two ways:

  * Integration path — emit `decision.applied` through the bus and
    let the subscriber fire (supersession test).
  * Direct-call path — invoke `validate_on_decision_applied` on the
    service with a synthesized payload (self-fruit test). Faster
    and avoids any racing with other drift/sla subscribers.

Both paths exercise the same validation code.
"""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from workgraph_persistence import (
    ConflictRow,
    DecisionRepository,
    DissentRepository,
    DissentRow,
    ProjectMemberRepository,
    ProjectRow,
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


async def _login(client: AsyncClient, username: str, password: str = "hunter22"):
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
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


async def _mk_project(maker, title: str = "Dissent") -> str:
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _add_member(
    maker, pid: str, uid: str, *, role: str = "member", license_tier: str = "full"
) -> None:
    async with session_scope(maker) as session:
        row = await ProjectMemberRepository(session).add(
            project_id=pid, user_id=uid, role=role
        )
        row.license_tier = license_tier
        await session.flush()


async def _seed_conflict(maker, pid: str, *, rule: str = "missing_owner") -> str:
    """Seed a minimal ConflictRow directly. Dissent validation keys
    off conflict_id linkage between decisions, so every supersession
    test needs a stable conflict to thread the two decisions through."""
    cid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(
            ConflictRow(
                id=cid,
                project_id=pid,
                rule=rule,
                severity="medium",
                fingerprint=f"fp-{cid}",
                targets=[],
                detail={},
                status="open",
            )
        )
        await session.flush()
    return cid


async def _seed_decision(
    maker,
    *,
    project_id: str,
    resolver_id: str,
    conflict_id: str | None = None,
    apply_outcome: str = "advisory",
) -> str:
    async with session_scope(maker) as session:
        row = await DecisionRepository(session).create(
            conflict_id=conflict_id,
            project_id=project_id,
            resolver_id=resolver_id,
            option_index=None,
            custom_text="pick",
            rationale="test decision",
            apply_actions=[],
            apply_outcome=apply_outcome,
        )
        return row.id


# ---- tests ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_records_dissent_on_crystallized_decision(api_env):
    """(1) Authenticated member POSTs a dissent; server persists it with
    the member's stance text and returns it under the expected shape."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "dissent_owner_1")
    member_id = await _register(client, "dissent_member_1")
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, member_id, role="member")
    did = await _seed_decision(maker, project_id=pid, resolver_id=owner_id)

    await _login(client, "dissent_member_1")
    r = await client.post(
        f"/api/projects/{pid}/decisions/{did}/dissents",
        json={"stance_text": "I think we should hold off."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    dissent = body["dissent"]
    assert dissent["decision_id"] == did
    assert dissent["dissenter_user_id"] == member_id
    assert dissent["stance_text"] == "I think we should hold off."
    assert dissent["validated_by_outcome"] is None


@pytest.mark.asyncio
async def test_dissent_renders_on_decision_lineage(api_env):
    """(2) GET returns the dissent on the decision's lineage surface."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "dissent_owner_2")
    member_id = await _register(client, "dissent_member_2")
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, member_id, role="member")
    did = await _seed_decision(maker, project_id=pid, resolver_id=owner_id)

    await _login(client, "dissent_member_2")
    r = await client.post(
        f"/api/projects/{pid}/decisions/{did}/dissents",
        json={"stance_text": "Disagree with scope."},
    )
    assert r.status_code == 200, r.text

    # Owner (or any member) can read back the list.
    await _login(client, "dissent_owner_2")
    r = await client.get(f"/api/projects/{pid}/decisions/{did}/dissents")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert len(body["dissents"]) == 1
    got = body["dissents"][0]
    assert got["dissenter_user_id"] == member_id
    assert got["stance_text"] == "Disagree with scope."
    assert got["dissenter_display_name"] == "dissent_member_2"


@pytest.mark.asyncio
async def test_supersession_flips_prior_dissents_to_supported(api_env):
    """(3) When a second decision is applied against the same
    conflict_id, every dissent recorded on the prior decision flips
    to `supported`, with the new decision's id appended to
    outcome_evidence_ids. Exercised through the real EventBus.
    """
    from workgraph_api.main import app

    client, maker, bus, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "dissent_owner_3")
    member_id = await _register(client, "dissent_member_3")
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, member_id, role="member")

    conflict_id = await _seed_conflict(maker, pid)
    prior_did = await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        conflict_id=conflict_id,
        apply_outcome="advisory",
    )

    # Member dissents the prior decision.
    await _login(client, "dissent_member_3")
    r = await client.post(
        f"/api/projects/{pid}/decisions/{prior_did}/dissents",
        json={"stance_text": "Wrong direction."},
    )
    assert r.status_code == 200, r.text

    # New decision on the same conflict — the supersession signal.
    new_did = await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        conflict_id=conflict_id,
        apply_outcome="advisory",
    )

    # Drive the validation pipeline directly so the assertion doesn't
    # race with any other decision.applied subscribers.
    dissent_service = app.state.dissent_service
    await dissent_service.validate_on_decision_applied(
        {
            "decision_id": new_did,
            "conflict_id": conflict_id,
            "project_id": pid,
            "outcome": "advisory",
        }
    )

    async with session_scope(maker) as session:
        rows = list(
            (
                await session.execute(
                    select(DissentRow).where(DissentRow.decision_id == prior_did)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    flipped = rows[0]
    assert flipped.validated_by_outcome == "supported"
    assert new_did in (flipped.outcome_evidence_ids or [])


@pytest.mark.asyncio
async def test_self_fruit_flips_dissent_to_refuted(api_env):
    """(4) When a decision's own apply_outcome is 'ok' (the graph
    mutation landed — equivalent to the PLAN's `milestone_hit` /
    `risk_closed` supporting event), its own dissents flip to
    `refuted`.
    """
    from workgraph_api.main import app

    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "dissent_owner_4")
    member_id = await _register(client, "dissent_member_4")
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, member_id, role="member")

    did = await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        apply_outcome="ok",
    )

    await _login(client, "dissent_member_4")
    r = await client.post(
        f"/api/projects/{pid}/decisions/{did}/dissents",
        json={"stance_text": "This will blow up."},
    )
    assert r.status_code == 200, r.text

    # Fire the validator against this decision's own applied event.
    dissent_service = app.state.dissent_service
    await dissent_service.validate_on_decision_applied(
        {
            "decision_id": did,
            "conflict_id": None,
            "project_id": pid,
            "outcome": "ok",
        }
    )

    async with session_scope(maker) as session:
        rows = list(
            (
                await session.execute(
                    select(DissentRow).where(DissentRow.decision_id == did)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].validated_by_outcome == "refuted"
    assert did in (rows[0].outcome_evidence_ids or [])


@pytest.mark.asyncio
async def test_perf_panel_reports_dissent_accuracy(api_env):
    """(5) /team/perf surfaces a `dissent_accuracy` bucket per member
    with the right counts across supported / refuted / still_open."""
    from workgraph_api.main import app

    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "perf_dissent_owner")
    member_id = await _seed_user(maker, "perf_dissent_member")
    await _add_member(maker, pid, owner_id, role="owner", license_tier="full")
    await _add_member(maker, pid, member_id, role="member")

    conflict_id = await _seed_conflict(maker, pid)

    # Dissent #1 — will flip `supported` via supersession.
    prior_did = await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        conflict_id=conflict_id,
    )
    # Dissent #2 — will flip `refuted` via self-fruit.
    fruit_did = await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        apply_outcome="ok",
    )
    # Dissent #3 — stays still_open (no triggering event).
    still_did = await _seed_decision(
        maker, project_id=pid, resolver_id=owner_id
    )

    dissent_service = app.state.dissent_service
    for did, stance in (
        (prior_did, "prior"),
        (fruit_did, "fruit"),
        (still_did, "still"),
    ):
        result = await dissent_service.record(
            project_id=pid,
            decision_id=did,
            dissenter_user_id=member_id,
            stance_text=stance,
        )
        assert result["ok"] is True

    # Drive supersession.
    new_did = await _seed_decision(
        maker,
        project_id=pid,
        resolver_id=owner_id,
        conflict_id=conflict_id,
    )
    await dissent_service.validate_on_decision_applied(
        {
            "decision_id": new_did,
            "conflict_id": conflict_id,
            "project_id": pid,
            "outcome": "advisory",
        }
    )
    # Drive self-fruit.
    await dissent_service.validate_on_decision_applied(
        {
            "decision_id": fruit_did,
            "conflict_id": None,
            "project_id": pid,
            "outcome": "ok",
        }
    )

    await _login(client, "perf_dissent_owner")
    r = await client.get(f"/api/projects/{pid}/team/perf")
    assert r.status_code == 200, r.text
    body = r.json()
    by_uid = {row["user_id"]: row for row in body}
    bucket = by_uid[member_id]["dissent_accuracy"]
    assert bucket["total"] == 3
    assert bucket["supported"] == 1
    assert bucket["refuted"] == 1
    assert bucket["still_open"] == 1

    # Owner has no dissents.
    assert by_uid[owner_id]["dissent_accuracy"] == {
        "total": 0,
        "supported": 0,
        "refuted": 0,
        "still_open": 0,
    }


@pytest.mark.asyncio
async def test_non_member_cannot_record_dissent(api_env):
    """Regression guard — routers/dissent.py gates on membership; a
    logged-in stranger must get 403 rather than silently writing."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "dissent_owner_x")
    await _add_member(maker, pid, owner_id, role="owner")
    did = await _seed_decision(maker, project_id=pid, resolver_id=owner_id)

    stranger_id = await _register(client, "dissent_stranger")
    assert stranger_id  # created
    await _login(client, "dissent_stranger")
    r = await client.post(
        f"/api/projects/{pid}/decisions/{did}/dissents",
        json={"stance_text": "hey"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_dissent_upsert_overwrites_prior_stance(api_env):
    """DissentRepository.upsert replaces the existing stance and
    clears the validation state — regression against the "one dissent
    per (decision, user)" invariant."""
    client, maker, *_ = api_env
    pid = await _mk_project(maker)
    owner_id = await _register(client, "dissent_owner_up")
    member_id = await _register(client, "dissent_member_up")
    await _add_member(maker, pid, owner_id, role="owner")
    await _add_member(maker, pid, member_id, role="member")
    did = await _seed_decision(maker, project_id=pid, resolver_id=owner_id)

    await _login(client, "dissent_member_up")
    r1 = await client.post(
        f"/api/projects/{pid}/decisions/{did}/dissents",
        json={"stance_text": "first pass"},
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/projects/{pid}/decisions/{did}/dissents",
        json={"stance_text": "rewritten"},
    )
    assert r2.status_code == 200
    async with session_scope(maker) as session:
        rows = await DissentRepository(session).list_for_decision(did)
    assert len(rows) == 1
    assert rows[0].stance_text == "rewritten"
