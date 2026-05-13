"""RW-9 — Flow Request singleton + respond endpoint tests.

Covers:

  * GET  /api/flow-requests/{flow_id}                — singleton read
  * POST /api/flow-requests/{flow_id}/respond        — direct text response

Two surfaces, one row family (RoutedSignalRow). The other packet kinds
(kb_review / handoff / decision / manual_*) are intentionally NOT
wired here — the tests assert that route packets work end-to-end and
that unsupported kinds return a stable 422 not_supported_yet /
not_respondable_yet code so the FE drawer can render an honest
non-respondable state.
"""
from __future__ import annotations

import uuid

import pytest

from workgraph_persistence import (
    ProjectMemberRepository,
    ProjectRow,
    backfill_streams_from_projects,
    session_scope,
)


# ---- helpers (mirroring test_flow_projection.py style) -------------------


async def _register(client, username: str) -> str:
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


async def _mk_project_with_members(maker, *, owner_id: str, member_id: str):
    pid = str(uuid.uuid4())
    async with session_scope(maker) as session:
        session.add(ProjectRow(id=pid, title="RW9 Project"))
        await session.flush()
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=owner_id, role="owner"
        )
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=member_id, role="member"
        )
    # Routing dispatch needs personal streams for both members.
    await backfill_streams_from_projects(maker)
    return pid


async def _dispatch_route(client, *, target_user_id: str, project_id: str) -> str:
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": target_user_id,
            "project_id": project_id,
            "framing": "Can we sync on the launch checklist before Friday?",
            "background": [
                {
                    "source": "graph",
                    "snippet": "Launch checklist last edited 2 days ago.",
                },
            ],
            "options": [
                {
                    "id": "yes",
                    "label": "Yes, today at 3pm",
                    "kind": "action",
                    "weight": 0.7,
                },
                {
                    "id": "no",
                    "label": "Push to next week",
                    "kind": "action",
                    "weight": 0.3,
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["signal"]["id"]


# ---- GET singleton -------------------------------------------------------


@pytest.mark.asyncio
async def test_singleton_route_packet_returns_full_envelope(api_env):
    """The singleton response includes every field RW-9.1 names —
    title, requester, target/authority, framing, AI context summary,
    needed judgment, evidence refs, source context, status, scope,
    timestamps, plus the participants sidecar and respondability."""
    client, maker, *_ = api_env
    source_id = await _register(client, "rw9_get_source")
    target_id = await _register(client, "rw9_get_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw9_get_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    r = await client.get(f"/api/flow-requests/route:{signal_id}")
    assert r.status_code == 200, r.text
    body = r.json()

    assert "flow_request" in body
    assert "participants" in body
    assert "respondability" in body

    fr = body["flow_request"]
    assert fr["id"] == f"route:{signal_id}"
    assert fr["recipe_id"] == "ask_with_context"
    assert fr["status"] == "active"
    assert fr["stage"] == "awaiting_target"
    assert fr["source_user_id"] == source_id
    assert fr["target_user_ids"] == [target_id]
    assert fr["current_target_user_ids"] == [target_id]
    assert fr["project_id"] == pid
    # Title + summary derived from framing.
    assert "launch checklist" in (fr["title"] or "").lower()
    # Singleton-only enrichment.
    assert "framing_full" in fr
    assert "launch checklist" in fr["framing_full"].lower()
    assert fr["background"] and fr["background"][0]["source"] == "graph"
    assert len(fr["options"]) == 2
    assert fr["raw_status"] == "pending"
    # Participants sidecar carries display names.
    assert source_id in body["participants"]
    assert target_id in body["participants"]


@pytest.mark.asyncio
async def test_singleton_respondability_true_for_target_when_pending(api_env):
    """The target's view of a pending route packet is respondable."""
    client, maker, *_ = api_env
    source_id = await _register(client, "rw9_resp_source")
    target_id = await _register(client, "rw9_resp_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw9_resp_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    # Source view: not the target → respondable=false.
    r = await client.get(f"/api/flow-requests/route:{signal_id}")
    body = r.json()
    assert body["respondability"]["respondable"] is False
    assert body["respondability"]["reason"] == "not_the_target"
    assert body["respondability"]["response_kind"] == "direct_response"

    # Target view: respondable=true.
    await _login(client, "rw9_resp_target")
    r = await client.get(f"/api/flow-requests/route:{signal_id}")
    body = r.json()
    assert body["respondability"]["respondable"] is True
    assert body["respondability"]["reason"] is None
    assert body["respondability"]["response_kind"] == "direct_response"


@pytest.mark.asyncio
async def test_singleton_403_for_non_participant_non_owner(api_env):
    """A project member who is neither source, target, nor owner must
    NOT see the route singleton. Project membership alone is not
    enough — the per-packet visibility filter blocks them."""
    client, maker, *_ = api_env
    source_id = await _register(client, "rw9_403_source")
    target_id = await _register(client, "rw9_403_target")
    other_id = await _register(client, "rw9_403_other")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )
    # Add a third member who is neither source nor target.
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=other_id, role="member"
        )

    await _login(client, "rw9_403_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    await _login(client, "rw9_403_other")
    r = await client.get(f"/api/flow-requests/route:{signal_id}")
    assert r.status_code == 403, r.text
    assert other_id != source_id and other_id != target_id


@pytest.mark.asyncio
async def test_singleton_404_for_unknown_route_id(api_env):
    client, *_ = api_env
    await _register(client, "rw9_404")
    await _login(client, "rw9_404")
    r = await client.get("/api/flow-requests/route:not-a-real-id")
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_singleton_422_for_unsupported_kind(api_env):
    """kb_review / handoff / decision / manual_* are known packet
    kinds but not wired for singleton in RW-9. The endpoint returns
    422 with a stable `not_supported_yet:<kind>` so the FE drawer can
    render an honest non-respondable state per kind."""
    client, *_ = api_env
    await _register(client, "rw9_422")
    await _login(client, "rw9_422")
    r = await client.get("/api/flow-requests/kb:doesnt-matter-pid")
    assert r.status_code == 422, r.text
    assert "not_supported_yet" in r.json()["message"]
    assert ":kb" in r.json()["message"]


@pytest.mark.asyncio
async def test_singleton_404_for_completely_unknown_kind(api_env):
    """An id whose prefix isn't a known packet kind at all is a 404,
    not a 422 — there's no FE state to render for it."""
    client, *_ = api_env
    await _register(client, "rw9_unknown_kind")
    await _login(client, "rw9_unknown_kind")
    r = await client.get("/api/flow-requests/gibberish:abc")
    assert r.status_code == 404, r.text


# ---- POST /respond -------------------------------------------------------


@pytest.mark.asyncio
async def test_respond_target_happy_path_flips_status_to_replied(api_env):
    """The target sends a direct_response text. Status flips
    pending → replied. The response envelope carries the locked
    memory_candidate_prompt with [review, skip, later]."""
    client, maker, *_ = api_env
    source_id = await _register(client, "rw9_post_source")
    target_id = await _register(client, "rw9_post_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw9_post_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    await _login(client, "rw9_post_target")
    r = await client.post(
        f"/api/flow-requests/route:{signal_id}/respond",
        json={"kind": "direct_response", "text": "Yes, 3pm works."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["flow_request_id"] == f"route:{signal_id}"
    assert body["response_kind"] == "direct_response"

    # INVARIANT — memory decoupling.
    prompt = body["memory_candidate_prompt"]
    assert prompt["actions"] == ["review", "skip", "later"]
    assert "memory_auto_accepted" not in body
    assert prompt["has_candidate"] is False

    # The reply landed — status on the row is now `replied`. Confirm
    # via the projection list endpoint (already real).
    r = await client.get(f"/api/projects/{pid}/flows")
    assert r.status_code == 200, r.text
    packets = r.json()["packets"]
    routed = next(p for p in packets if p["id"] == f"route:{signal_id}")
    # Replied state — source now currently_blocks.
    assert routed["stage"] == "awaiting_source"
    assert routed["current_target_user_ids"] == [source_id]


@pytest.mark.asyncio
async def test_respond_403_when_caller_is_not_target(api_env):
    client, maker, *_ = api_env
    source_id = await _register(client, "rw9_post403_source")
    target_id = await _register(client, "rw9_post403_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw9_post403_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    # Source tries to respond — they're not the target.
    r = await client.post(
        f"/api/flow-requests/route:{signal_id}/respond",
        json={"kind": "direct_response", "text": "I'll answer myself."},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_respond_409_when_already_replied(api_env):
    client, maker, *_ = api_env
    source_id = await _register(client, "rw9_post409_source")
    target_id = await _register(client, "rw9_post409_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw9_post409_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    await _login(client, "rw9_post409_target")
    r = await client.post(
        f"/api/flow-requests/route:{signal_id}/respond",
        json={"kind": "direct_response", "text": "First reply."},
    )
    assert r.status_code == 200, r.text

    # Second reply attempt — idempotency boundary in RoutingService.
    r = await client.post(
        f"/api/flow-requests/route:{signal_id}/respond",
        json={"kind": "direct_response", "text": "Second reply."},
    )
    assert r.status_code == 409, r.text


@pytest.mark.asyncio
async def test_respond_404_for_unknown_signal(api_env):
    client, *_ = api_env
    await _register(client, "rw9_post404")
    await _login(client, "rw9_post404")
    r = await client.post(
        "/api/flow-requests/route:not-a-real-id/respond",
        json={"kind": "direct_response", "text": "anything"},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_respond_422_for_unsupported_kind(api_env):
    """Non-route packet kinds (kb_review / handoff / decision /
    manual_*) cannot be responded to via this endpoint. The FE
    drawer reads this 422 and renders an honest non-respondable
    state."""
    client, *_ = api_env
    await _register(client, "rw9_post422")
    await _login(client, "rw9_post422")
    r = await client.post(
        "/api/flow-requests/kb:nonsense/respond",
        json={"kind": "direct_response", "text": "Try anyway."},
    )
    assert r.status_code == 422, r.text
    assert "not_respondable_yet" in r.json()["message"]


@pytest.mark.asyncio
async def test_respond_422_for_empty_text(api_env):
    """Pydantic enforces min_length=1 — empty text is rejected at
    parse time, not the service layer."""
    client, maker, *_ = api_env
    source_id = await _register(client, "rw9_post_empty_source")
    target_id = await _register(client, "rw9_post_empty_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw9_post_empty_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    await _login(client, "rw9_post_empty_target")
    r = await client.post(
        f"/api/flow-requests/route:{signal_id}/respond",
        json={"kind": "direct_response", "text": ""},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_respond_422_for_unknown_response_kind(api_env):
    """The kind enum is locked to direct_response. delegate / counter
    / accept etc are not accepted at the parse layer."""
    client, *_ = api_env
    await _register(client, "rw9_post_kind")
    await _login(client, "rw9_post_kind")
    r = await client.post(
        "/api/flow-requests/route:whatever/respond",
        json={"kind": "delegate", "text": "Forward this."},
    )
    assert r.status_code == 422, r.text


# ---- Memory decoupling — explicit, separate from happy path --------------


@pytest.mark.asyncio
async def test_respond_envelope_locks_memory_decoupling(api_env):
    """B.4 invariant. The respond envelope must:
      * carry memory_candidate_prompt with actions [review, skip, later]
      * NEVER set memory_auto_accepted=true
    This is the load-bearing test the FE invariant suite refers to.
    """
    client, maker, *_ = api_env
    source_id = await _register(client, "rw9_inv_source")
    target_id = await _register(client, "rw9_inv_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw9_inv_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    await _login(client, "rw9_inv_target")
    r = await client.post(
        f"/api/flow-requests/route:{signal_id}/respond",
        json={"kind": "direct_response", "text": "Acknowledged."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Hard invariants.
    assert body["memory_candidate_prompt"]["actions"] == [
        "review",
        "skip",
        "later",
    ]
    assert body.get("memory_auto_accepted") is not True
    # Also: the prompt envelope MUST NOT lie about a candidate
    # existing when none was produced. RW-9 produces no candidate
    # (membrane integration is later work).
    assert body["memory_candidate_prompt"]["has_candidate"] is False
    assert body["memory_candidate_prompt"]["candidate_id"] is None
