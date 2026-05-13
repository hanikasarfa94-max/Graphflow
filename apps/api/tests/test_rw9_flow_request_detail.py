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


# ---- RW-9.5 — recorded_reply + dm_stream enrichment ---------------------


@pytest.mark.asyncio
async def test_singleton_recorded_reply_is_null_while_pending(api_env):
    """Before the target replies, recorded_reply must be null. The FE
    uses null/non-null as the render switch for the RecordedReply
    card — silent strings or empty dicts would render a misleading
    "reply: ''" affordance."""
    client, maker, *_ = api_env
    source_id = await _register(client, "rw95_pend_source")
    target_id = await _register(client, "rw95_pend_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw95_pend_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    r = await client.get(f"/api/flow-requests/route:{signal_id}")
    assert r.status_code == 200, r.text
    fr = r.json()["flow_request"]
    assert "recorded_reply" in fr
    assert fr["recorded_reply"] is None


@pytest.mark.asyncio
async def test_singleton_recorded_reply_carries_custom_text(api_env):
    """After the target replies with custom_text, the singleton
    returns a full recorded_reply envelope. The FE renders this
    verbatim in the RecordedReply card."""
    client, maker, *_ = api_env
    source_id = await _register(client, "rw95_rec_source")
    target_id = await _register(client, "rw95_rec_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw95_rec_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    await _login(client, "rw95_rec_target")
    r = await client.post(
        f"/api/flow-requests/route:{signal_id}/respond",
        json={"kind": "direct_response", "text": "Yes, 3pm works."},
    )
    assert r.status_code == 200, r.text
    # Critical: the respond envelope STILL locks memory decoupling
    # after RW-9.5 enrichment. The recorded_reply addition must not
    # leak a memory candidate.
    prompt = r.json()["memory_candidate_prompt"]
    assert prompt["actions"] == ["review", "skip", "later"]
    assert prompt["has_candidate"] is False
    assert "memory_auto_accepted" not in r.json()

    # Now GET the singleton — recorded_reply should reflect the text.
    r = await client.get(f"/api/flow-requests/route:{signal_id}")
    assert r.status_code == 200, r.text
    fr = r.json()["flow_request"]
    rr = fr["recorded_reply"]
    assert rr is not None
    assert rr["text"] == "Yes, 3pm works."
    assert rr["replier_user_id"] == target_id
    assert rr["replied_at"] is not None
    # No option was picked — option_id and option_label are null.
    assert rr["option_id"] is None
    assert rr["option_label"] is None
    # Respondability also flipped — the source can no longer
    # respond from the drawer.
    assert r.json()["respondability"]["respondable"] is False


@pytest.mark.asyncio
async def test_singleton_recorded_reply_carries_option_pick(api_env):
    """When the target picks an option_id (1-click reply via the
    /api/routing/:id/reply path), recorded_reply must include the
    resolved option_label so the FE renders the human-readable
    pick alongside the option_id."""
    client, maker, *_ = api_env
    source_id = await _register(client, "rw95_opt_source")
    target_id = await _register(client, "rw95_opt_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw95_opt_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    # Reply via the existing routing endpoint with an option pick.
    # /api/flow-requests/:id/respond only supports custom_text in
    # RW-9, so we use the legacy route to seed an option pick — the
    # singleton must still surface it.
    await _login(client, "rw95_opt_target")
    r = await client.post(
        f"/api/routing/{signal_id}/reply",
        json={"option_id": "yes"},
    )
    assert r.status_code == 200, r.text

    r = await client.get(f"/api/flow-requests/route:{signal_id}")
    assert r.status_code == 200, r.text
    rr = r.json()["flow_request"]["recorded_reply"]
    assert rr is not None
    assert rr["option_id"] == "yes"
    assert rr["option_label"] == "Yes, today at 3pm"
    # custom_text was not used — text is null.
    assert rr["text"] is None


@pytest.mark.asyncio
async def test_singleton_dm_stream_present_after_dispatch(api_env):
    """RoutingService.dispatch creates the source↔target DM stream
    via StreamService.create_or_get_dm. By the time the singleton
    is fetched, that DM exists and the dm envelope carries its
    stream_id + a /conversations/{id} href."""
    client, maker, *_ = api_env
    source_id = await _register(client, "rw95_dm_source")
    target_id = await _register(client, "rw95_dm_target")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw95_dm_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )

    r = await client.get(f"/api/flow-requests/route:{signal_id}")
    assert r.status_code == 200, r.text
    fr = r.json()["flow_request"]
    assert "dm" in fr
    dm = fr["dm"]
    assert dm["stream_id"] is not None
    assert dm["href"] == f"/conversations/{dm['stream_id']}"


@pytest.mark.asyncio
async def test_singleton_dm_stream_does_not_get_created_by_get(api_env):
    """RW-9.5 invariant: GET singleton must NOT create a DM stream as
    a side effect. We construct a routed signal where the DM lookup
    would return None (by tampering with the row's source/target to
    a fresh user pair that never dispatched). Result: dm.stream_id
    stays null and no DM stream materialises in StreamMemberRow.

    This is a regression guard — replacing find_dm_between with
    create_or_get_dm would be invisible at the FE but would slowly
    fill StreamRow with phantom DMs from every detail open."""
    client, maker, *_ = api_env
    source_id = await _register(client, "rw95_nodm_source")
    target_id = await _register(client, "rw95_nodm_target")
    other_id = await _register(client, "rw95_nodm_other")
    pid = await _mk_project_with_members(
        maker, owner_id=source_id, member_id=target_id
    )

    await _login(client, "rw95_nodm_source")
    signal_id = await _dispatch_route(
        client, target_user_id=target_id, project_id=pid
    )
    # Rewrite the routed signal so its target points at `other_id`
    # who never had a DM with source. The dispatched DM still
    # exists between source/target, but the lookup is for source/
    # other → None expected.
    from workgraph_persistence import RoutedSignalRow as _Row
    async with session_scope(maker) as session:
        row = await session.get(_Row, signal_id)
        assert row is not None
        row.target_user_id = other_id

    # Add `other_id` to the project so visibility still passes for
    # source viewing the rewritten row.
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=pid, user_id=other_id, role="member"
        )

    r = await client.get(f"/api/flow-requests/route:{signal_id}")
    assert r.status_code == 200, r.text
    dm = r.json()["flow_request"]["dm"]
    assert dm["stream_id"] is None
    assert dm["href"] is None


# ---- B.4 invariant — memory decoupling stays locked after enrichment ----


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
