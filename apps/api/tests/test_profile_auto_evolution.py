"""Auto-evolution loop for response profile (competition §10 item 1).

Covers:
  1. Posting a message increments messages_posted on the poster.
  2. Accepting a decision increments decisions_resolved on the resolver.
  3. Replying to a routed signal increments routings_answered on the replier.
  4. routing_suggest ranks a high-tally candidate above an equivalent zero-tally one.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from workgraph_api.main import app
from workgraph_api.services import SkillsService
from workgraph_persistence import (
    ProjectMemberRepository,
    UserRepository,
    backfill_streams_from_projects,
    session_scope,
)

CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


def _alt_client() -> AsyncClient:
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _register(client: AsyncClient, username: str, password: str = "hunter22"):
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _login(client: AsyncClient, username: str, password: str = "hunter22") -> None:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text


async def _me_id(client: AsyncClient) -> str:
    r = await client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _intake(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


async def _invite(client: AsyncClient, project_id: str, username: str) -> None:
    r = await client.post(
        f"/api/projects/{project_id}/invite", json={"username": username}
    )
    assert r.status_code == 200, r.text


async def _tally(maker, user_id: str) -> dict:
    async with session_scope(maker) as session:
        row = await UserRepository(session).get(user_id)
        if row is None:
            return {}
        return dict((row.profile or {}).get("signal_tally") or {})


# ---------------------------------------------------------------------------
# Half 1 — persistence wires up from the existing code paths.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_posting_message_increments_messages_posted(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "ae_poster")
    project_id = await _intake(client, "AE-msg-1")
    poster_id = await _me_id(client)

    before = await _tally(maker, poster_id)
    assert before.get("messages_posted", 0) == 0

    r = await client.post(
        f"/api/projects/{project_id}/messages",
        json={"body": "Kicking off scope review for the launch."},
    )
    assert r.status_code == 200, r.text

    after = await _tally(maker, poster_id)
    assert after.get("messages_posted") == 1

    # A second post bumps again — the counter is monotonic.
    r2 = await client.post(
        f"/api/projects/{project_id}/messages",
        json={"body": "Second message to confirm the bump is additive."},
    )
    assert r2.status_code == 200, r2.text
    again = await _tally(maker, poster_id)
    assert again.get("messages_posted") == 2


@pytest.mark.asyncio
async def test_accepting_decision_increments_decisions_resolved(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "ae_resolver")
    project_id = await _intake(client, "AE-dec-1")
    resolver_id = await _me_id(client)

    # Plan generates conflicts; grab the first one to resolve.
    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200, r.text
    await app.state.conflict_service.drain()

    r = await client.get(f"/api/projects/{project_id}/conflicts")
    assert r.status_code == 200, r.text
    conflicts = r.json()["conflicts"]
    assert conflicts, "fixture should surface at least one conflict"
    conflict_id = conflicts[0]["id"]

    before = await _tally(maker, resolver_id)
    assert before.get("decisions_resolved", 0) == 0

    r = await client.post(
        f"/api/conflicts/{conflict_id}/decision",
        json={"option_index": 0, "rationale": "Scope tight for v1."},
    )
    assert r.status_code == 200, r.text

    after = await _tally(maker, resolver_id)
    assert after.get("decisions_resolved") == 1


@pytest.mark.asyncio
async def test_replying_to_routed_signal_increments_routings_answered(api_env):
    client, maker, _, _, _, _ = api_env
    # Source + target setup.
    await _register(client, "ae_src")
    project_id = await _intake(client, "AE-route-1")
    await _register(client, "ae_tgt")
    target_id = await _me_id(client)

    await _login(client, "ae_src")
    await _invite(client, project_id, "ae_tgt")
    # Personal streams must exist for both members before dispatch.
    await backfill_streams_from_projects(maker)

    dispatch = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": target_id,
            "project_id": project_id,
            "framing": "Pick an option on the launch checklist.",
            "background": [],
            "options": [
                {
                    "id": "go",
                    "label": "Ship Thursday",
                    "kind": "action",
                    "background": "",
                    "reason": "",
                    "tradeoff": "",
                    "weight": 0.5,
                }
            ],
        },
    )
    assert dispatch.status_code == 200, dispatch.text
    signal_id = dispatch.json()["signal"]["id"]

    before = await _tally(maker, target_id)
    assert before.get("routings_answered", 0) == 0

    # Reply from the target's session.
    await _login(client, "ae_tgt")
    r = await client.post(
        f"/api/routing/{signal_id}/reply", json={"option_id": "go"}
    )
    assert r.status_code == 200, r.text

    after = await _tally(maker, target_id)
    assert after.get("routings_answered") == 1


# ---------------------------------------------------------------------------
# Half 2 — persisted tally feeds back into routing_suggest ranking.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routing_suggest_favors_high_tally_over_equivalent_zero(api_env):
    """Two candidates identical on graph/activity/profile signals; the one
    with persisted signal_tally should outrank the zero-tally peer so the
    loop rewards repeated resolvers."""
    _, maker, *_ = api_env

    # Seed a project + two members who are otherwise equivalent.
    from workgraph_persistence import (
        DecisionRepository,
        ProjectRow,
        RequirementRow,
    )
    import uuid

    async with session_scope(maker) as session:
        pid = str(uuid.uuid4())
        session.add(ProjectRow(id=pid, title="AE-route-rank"))
        session.add(
            RequirementRow(
                id=str(uuid.uuid4()), project_id=pid, raw_text="x", version=1
            )
        )
        user_repo = UserRepository(session)
        high = await user_repo.create(
            username="ae_rank_high", password_hash="x", password_salt="y",
            display_name="High Tally",
        )
        low = await user_repo.create(
            username="ae_rank_low", password_hash="x", password_salt="y",
            display_name="Low Tally",
        )
        high_id, low_id = high.id, low.id

    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=high_id
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=low_id
        )
        # Both resolved a decision with identical rationale — identical
        # graph_score, identical activity_score, identical profile_score.
        for uid in (high_id, low_id):
            await DecisionRepository(session).create(
                conflict_id=None,
                project_id=pid,
                resolver_id=uid,
                option_index=None,
                custom_text="done",
                rationale="launch checklist review",
                apply_actions=[],
                apply_outcome="advisory",
            )

    # Give the high-tally user persisted signal_tally.
    async with session_scope(maker) as session:
        await UserRepository(session).update_profile(
            high_id, signal_tally={"decisions_resolved": 10, "routings_answered": 10}
        )

    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid,
        skill_name="routing_suggest",
        args={"query": "launch checklist review", "limit": 5},
    )
    assert out["ok"] is True
    rows = out["result"]
    assert len(rows) == 2, rows
    # High-tally wins. Base scores were equal, so the affinity bump must be
    # what flips the order.
    assert rows[0]["user_id"] == high_id
    assert rows[0]["score"] > rows[1]["score"]
