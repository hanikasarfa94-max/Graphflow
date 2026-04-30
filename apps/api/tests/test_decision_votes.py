"""DecisionVoteService — N.4 smallest-relevant-vote tally.

Covers the contract the FE DecisionVoteButtons + tally view consume:
  * Cast vote / change vote / abstain.
  * Tally math: approve / deny / abstain / cast / outstanding /
    quorum / status.
  * Membership gating: room-scoped decisions require room membership;
    project-scoped require project membership.
  * Tally enriches the decision payload at REST snapshot
    (room timeline endpoint) AND WS upserts (IMService.accept
    crystallization broadcast).
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from workgraph_agents.im_assist import IMProposal, IMSuggestion
from workgraph_api.main import app
from workgraph_api.services.decision_votes import (
    DecisionVoteError,
    DecisionVoteService,
    SUBJECT_KIND,
)
from workgraph_persistence import (
    DecisionRow,
    IMSuggestionRow,
    VoteRepository,
    session_scope,
)


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _register(client: AsyncClient, username: str) -> str:
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _intake(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


async def _alt_login_get_me(username: str) -> str:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as alt:
        r = await alt.post(
            "/api/auth/login",
            json={"username": username, "password": "hunter22"},
        )
        assert r.status_code == 200, r.text
        me = await alt.get("/api/auth/me")
        return me.json()["id"]


async def _create_room(client, pid, *, name, members):
    r = await client.post(
        f"/api/projects/{pid}/rooms",
        json={"name": name, "member_user_ids": members},
    )
    assert r.status_code == 200, r.text
    return r.json()["stream"]


async def _crystallize_room_decision(
    client,
    maker,
    pid: str,
    room_id: str,
    *,
    deliverable_id: str,
) -> str:
    """End-to-end helper: post a decision-flavored room message,
    accept the resulting suggestion, return the new decision_id.
    """
    im_agent = app.state.im_agent
    im_agent._suggestion = IMSuggestion(
        kind="decision",
        confidence=0.85,
        targets=[],
        proposal=IMProposal(
            action="drop_deliverable",
            summary="vote-test crystallization",
            detail={"deliverable_id": deliverable_id},
        ),
        reasoning="vote test",
    )
    try:
        r = await client.post(
            f"/api/projects/{pid}/messages",
            json={
                "body": "let's drop this deliverable for the v1 launch",
                "stream_id": room_id,
            },
        )
        assert r.status_code == 200, r.text
        await app.state.im_service.drain()

        async with session_scope(maker) as session:
            sug = (
                await session.execute(
                    select(IMSuggestionRow).where(IMSuggestionRow.project_id == pid)
                )
            ).scalar_one()
        r = await client.post(f"/api/im_suggestions/{sug.id}/accept")
        assert r.status_code == 200, r.text
        return r.json()["decision"]["id"]
    finally:
        im_agent._suggestion = None


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cast_vote_room_member_succeeds_and_increments_tally(api_env):
    client, maker, *_ = api_env
    await _register(client, "vt_owner")
    pid = await _intake(client, "vt-cast-1")
    me = await _alt_login_get_me("vt_owner")
    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]

    room = await _create_room(client, pid, name="vote-room", members=[me])
    decision_id = await _crystallize_room_decision(
        client, maker, pid, room["id"], deliverable_id=deliverable_id
    )

    svc = DecisionVoteService(maker, collab_hub=app.state.collab_hub)
    out = await svc.cast_vote(
        decision_id=decision_id, voter_user_id=me, verdict="approve"
    )
    assert out["my_vote"]["verdict"] == "approve"
    tally = out["tally"]
    assert tally["approve"] == 1
    assert tally["cast"] == 1
    assert tally["quorum"] == 1  # solo room
    assert tally["status"] == "passed"  # 1/1 majority


@pytest.mark.asyncio
async def test_cast_vote_change_verdict_updates_existing_row(api_env):
    client, maker, *_ = api_env
    await _register(client, "vt_change")
    pid = await _intake(client, "vt-change-1")
    me = await _alt_login_get_me("vt_change")
    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]

    room = await _create_room(client, pid, name="change-room", members=[me])
    decision_id = await _crystallize_room_decision(
        client, maker, pid, room["id"], deliverable_id=deliverable_id
    )

    svc = DecisionVoteService(maker, collab_hub=app.state.collab_hub)
    await svc.cast_vote(decision_id=decision_id, voter_user_id=me, verdict="approve")
    out = await svc.cast_vote(
        decision_id=decision_id, voter_user_id=me, verdict="deny"
    )
    assert out["my_vote"]["verdict"] == "deny"

    # DB-layer: still exactly one row for this voter.
    async with session_scope(maker) as session:
        rows = await VoteRepository(session).list_for_subject(
            subject_kind=SUBJECT_KIND, subject_id=decision_id
        )
    assert len(rows) == 1
    assert rows[0].verdict == "deny"


@pytest.mark.asyncio
async def test_cast_vote_rejects_non_room_member(api_env):
    """Project member who isn't in the room cannot vote on its decisions."""
    client, maker, *_ = api_env
    await _register(client, "vt_owner2")
    pid = await _intake(client, "vt-reject-1")
    me_owner = await _alt_login_get_me("vt_owner2")

    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]

    room = await _create_room(client, pid, name="closed-room", members=[me_owner])
    decision_id = await _crystallize_room_decision(
        client, maker, pid, room["id"], deliverable_id=deliverable_id
    )

    # Add an outsider to the project (NOT to the room).
    await _register(client, "vt_outsider")
    client.cookies.clear()
    login = await client.post(
        "/api/auth/login",
        json={"username": "vt_owner2", "password": "hunter22"},
    )
    assert login.status_code == 200
    invite = await client.post(
        f"/api/projects/{pid}/invite", json={"username": "vt_outsider"}
    )
    assert invite.status_code == 200, invite.text
    me_outsider = await _alt_login_get_me("vt_outsider")

    svc = DecisionVoteService(maker, collab_hub=app.state.collab_hub)
    with pytest.raises(DecisionVoteError) as exc:
        await svc.cast_vote(
            decision_id=decision_id,
            voter_user_id=me_outsider,
            verdict="approve",
        )
    assert exc.value.code == "not_in_voter_pool"
    assert exc.value.status == 403


@pytest.mark.asyncio
async def test_cast_vote_invalid_verdict_raises(api_env):
    client, maker, *_ = api_env
    await _register(client, "vt_inv")
    pid = await _intake(client, "vt-invalid-1")
    me = await _alt_login_get_me("vt_inv")
    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]
    room = await _create_room(client, pid, name="inv-room", members=[me])
    decision_id = await _crystallize_room_decision(
        client, maker, pid, room["id"], deliverable_id=deliverable_id
    )
    svc = DecisionVoteService(maker, collab_hub=app.state.collab_hub)
    with pytest.raises(DecisionVoteError) as exc:
        await svc.cast_vote(
            decision_id=decision_id, voter_user_id=me, verdict="maybe"
        )
    assert exc.value.code == "invalid_verdict"


@pytest.mark.asyncio
async def test_cast_vote_unknown_decision_returns_404(api_env):
    _, maker, *_ = api_env
    svc = DecisionVoteService(maker, collab_hub=None)
    with pytest.raises(DecisionVoteError) as exc:
        await svc.cast_vote(
            decision_id="00000000-0000-0000-0000-deadbeefface",
            voter_user_id="anyone",
            verdict="approve",
        )
    assert exc.value.code == "decision_not_found"
    assert exc.value.status == 404


# ---------------------------------------------------------------------------
# Tally enrichment in the wire payloads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_timeline_decision_carries_tally(api_env):
    """GET /timeline returns each decision item with a `tally` field."""
    client, maker, *_ = api_env
    await _register(client, "vt_enrich")
    pid = await _intake(client, "vt-enrich-1")
    me = await _alt_login_get_me("vt_enrich")
    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]
    room = await _create_room(client, pid, name="enrich-room", members=[me])
    decision_id = await _crystallize_room_decision(
        client, maker, pid, room["id"], deliverable_id=deliverable_id
    )

    # Cast one vote.
    svc = DecisionVoteService(maker, collab_hub=app.state.collab_hub)
    await svc.cast_vote(decision_id=decision_id, voter_user_id=me, verdict="approve")

    r = await client.get(f"/api/projects/{pid}/rooms/{room['id']}/timeline")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    decision_item = next(it for it in items if it["kind"] == "decision")
    assert "tally" in decision_item
    assert decision_item["tally"]["approve"] == 1
    assert decision_item["tally"]["quorum"] == 1
    assert decision_item["tally"]["status"] == "passed"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_vote_route_round_trips_tally(api_env):
    client, maker, *_ = api_env
    await _register(client, "vt_route")
    pid = await _intake(client, "vt-route-1")
    me = await _alt_login_get_me("vt_route")
    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]
    room = await _create_room(client, pid, name="route-room", members=[me])
    decision_id = await _crystallize_room_decision(
        client, maker, pid, room["id"], deliverable_id=deliverable_id
    )

    r = await client.post(
        f"/api/decisions/{decision_id}/votes",
        json={"verdict": "approve"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tally"]["approve"] == 1
    assert body["my_vote"]["verdict"] == "approve"


@pytest.mark.asyncio
async def test_get_tally_route_includes_my_vote(api_env):
    client, maker, *_ = api_env
    await _register(client, "vt_get")
    pid = await _intake(client, "vt-get-1")
    me = await _alt_login_get_me("vt_get")
    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]
    room = await _create_room(client, pid, name="get-room", members=[me])
    decision_id = await _crystallize_room_decision(
        client, maker, pid, room["id"], deliverable_id=deliverable_id
    )

    # No vote yet → tally is empty + my_vote None.
    r = await client.get(f"/api/decisions/{decision_id}/votes")
    assert r.status_code == 200
    body = r.json()
    assert body["my_vote"] is None
    assert body["tally"]["cast"] == 0

    # Cast → my_vote populated.
    await client.post(
        f"/api/decisions/{decision_id}/votes",
        json={"verdict": "abstain", "rationale": "thinking it through"},
    )
    r = await client.get(f"/api/decisions/{decision_id}/votes")
    body = r.json()
    assert body["my_vote"]["verdict"] == "abstain"
    assert body["my_vote"]["rationale"] == "thinking it through"


@pytest.mark.asyncio
async def test_post_vote_route_400_on_invalid_verdict(api_env):
    client, maker, *_ = api_env
    await _register(client, "vt_inv2")
    pid = await _intake(client, "vt-inv-route-1")
    me = await _alt_login_get_me("vt_inv2")
    state = (await client.get(f"/api/projects/{pid}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]
    room = await _create_room(client, pid, name="inv-route-room", members=[me])
    decision_id = await _crystallize_room_decision(
        client, maker, pid, room["id"], deliverable_id=deliverable_id
    )

    r = await client.post(
        f"/api/decisions/{decision_id}/votes",
        json={"verdict": "love-it"},
    )
    assert r.status_code == 400
