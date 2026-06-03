"""Phase L — sub-agent routing tests.

Covers:
  * Personal stream backfill — every (project, member) pair gets a
    type='personal' stream with owner + edge-agent as members.
  * Edge-agent system user seeded at boot.
  * RoutingService.dispatch — creates signal, posts 'routed-inbound' in
    target's personal stream, mirrors into source↔target DM.
  * RoutingService.reply — flips status to 'replied', posts
    'routed-reply' in source's personal stream, DM log updated.
  * GET /api/routing/inbox — pending signals for current user.
  * Permissions — non-target cannot reply (403); non-participant cannot
    GET the signal (403).

All paths go through the HTTP surface so auth + role guards are exercised
alongside the service logic.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    EventRepository,
    MessageRow,
    RoutedSignalRow,
    StreamMemberRow,
    StreamRow,
    UserRow,
    backfill_streams_from_projects,
    session_scope,
)


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _register(client: AsyncClient, username: str, password: str = "hunter22"):
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _login(client: AsyncClient, username: str, password: str = "hunter22"):
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text


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


async def _me_id(client: AsyncClient) -> str:
    r = await client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------- edge-agent system user seed ---------------------------------


@pytest.mark.asyncio
async def test_edge_agent_system_user_exists(api_env):
    """Boot backfill seeds the shared edge-agent UserRow."""
    _, maker, _, _, _, _ = api_env

    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(UserRow).where(UserRow.id == EDGE_AGENT_SYSTEM_USER_ID)
            )
        ).scalar_one_or_none()

    assert row is not None
    assert row.username == "edge"
    # Display name is user-visible (FE may surface it as author label),
    # so it tracks the project-assistant rename. Internal id +
    # username stay "edge-agent-system" / "edge".
    assert row.display_name == "项目助手"


# ---------- personal stream backfill ------------------------------------


@pytest.mark.asyncio
async def test_project_creation_backfills_personal_stream_for_creator(api_env):
    """Creator auto-joins the project + also gets a personal stream
    with owner + edge-agent as its members.
    """
    client, maker, _, _, _, _ = api_env
    await _register(client, "l_maya")
    project_id = await _intake(client, "L-personal-seed-1")

    creator_id = await _me_id(client)

    # Run backfill so the test-only environment mirrors the prod boot path
    # (boot backfill creates streams for pre-existing members; we hit the
    # same code path for members added after the initial boot).
    await backfill_streams_from_projects(maker)

    async with session_scope(maker) as session:
        personal_streams = list(
            (
                await session.execute(
                    select(StreamRow).where(
                        StreamRow.project_id == project_id,
                        StreamRow.type == "personal",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(personal_streams) == 1
        ps = personal_streams[0]
        assert ps.owner_user_id == creator_id

        members = list(
            (
                await session.execute(
                    select(StreamMemberRow).where(
                        StreamMemberRow.stream_id == ps.id
                    )
                )
            )
            .scalars()
            .all()
        )
        member_ids = {m.user_id for m in members}
        assert member_ids == {creator_id, EDGE_AGENT_SYSTEM_USER_ID}


@pytest.mark.asyncio
async def test_invited_member_gets_personal_stream_after_backfill(api_env):
    """Inviting a user, then running backfill, yields a personal stream
    for the invitee too.
    """
    client, maker, _, _, _, _ = api_env
    await _register(client, "l_owner")
    project_id = await _intake(client, "L-personal-invite-1")
    await _register(client, "l_raj")
    raj_id = await _me_id(client)
    await _login(client, "l_owner")
    await _invite(client, project_id, "l_raj")

    await backfill_streams_from_projects(maker)

    async with session_scope(maker) as session:
        raj_personal = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == raj_id,
                )
            )
        ).scalar_one_or_none()
    assert raj_personal is not None


# ---------- dispatch: signal + inbound card + DM mirror -----------------


@pytest.mark.asyncio
async def test_dispatch_creates_signal_with_inbound_and_dm_mirror(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "l_maya2")
    project_id = await _intake(client, "L-dispatch-1")
    maya_id = await _me_id(client)
    await _register(client, "l_raj2")
    raj_id = await _me_id(client)
    await _login(client, "l_maya2")
    await _invite(client, project_id, "l_raj2")
    await backfill_streams_from_projects(maker)

    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": project_id,
            "framing": "Should we drop permadeath for the boss rooms?",
            "background": [
                {
                    "source": "graph",
                    "snippet": "Sofia playtest shows 40% rage-quit on boss 1",
                }
            ],
            "options": [
                {
                    "id": "drop",
                    "label": "Drop permadeath",
                    "kind": "action",
                    "background": "Aligns with playtest data",
                    "reason": "Removes churn",
                    "tradeoff": "Loses some stakes",
                    "weight": 0.7,
                },
                {
                    "id": "keep",
                    "label": "Keep permadeath",
                    "kind": "action",
                    "background": "",
                    "reason": "Preserves tension",
                    "tradeoff": "May cause churn",
                    "weight": 0.3,
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    signal = r.json()["signal"]
    assert signal["source_user_id"] == maya_id
    assert signal["target_user_id"] == raj_id
    assert signal["status"] == "pending"
    assert len(signal["options"]) == 2

    # Inbound message landed in Raj's personal stream, authored by edge-agent.
    async with session_scope(maker) as session:
        raj_personal = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == raj_id,
                )
            )
        ).scalar_one()
        inbound_msgs = list(
            (
                await session.execute(
                    select(MessageRow).where(
                        MessageRow.stream_id == raj_personal.id,
                        MessageRow.kind == "routed-inbound",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(inbound_msgs) == 1
        assert inbound_msgs[0].author_id == EDGE_AGENT_SYSTEM_USER_ID
        assert inbound_msgs[0].linked_id == signal["id"]

        # DM mirror: a dm stream between maya + raj should now exist
        # with a `routed-prompt` message authored by the source human.
        # Previously we also wrote a `routed-dm-log` audit line that
        # repeated the framing — dropped because it was a visual dup
        # next to routed-prompt. Routing fact stays in the
        # RoutedSignalRow itself.
        dm_msgs = list(
            (
                await session.execute(
                    select(MessageRow).where(
                        MessageRow.kind == "routed-prompt",
                        MessageRow.linked_id == signal["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(dm_msgs) == 1
        dm_stream = (
            await session.execute(
                select(StreamRow).where(StreamRow.id == dm_msgs[0].stream_id)
            )
        ).scalar_one()
        assert dm_stream.type == "dm"


@pytest.mark.asyncio
async def test_dispatch_to_self_rejected(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "l_solo")
    project_id = await _intake(client, "L-dispatch-self")
    me_id = await _me_id(client)

    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": me_id,
            "project_id": project_id,
            "framing": "talking to myself",
            "background": [],
            "options": [],
        },
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_dispatch_non_member_source_rejected(api_env):
    """A user who is not a project member cannot dispatch into that
    project's routing graph.
    """
    client, maker, _, _, _, _ = api_env
    await _register(client, "l_owner2")
    project_id = await _intake(client, "L-dispatch-outsider")
    await _register(client, "l_outsider")
    outsider_id = await _me_id(client)
    await _register(client, "l_other")
    other_id = await _me_id(client)
    # Owner invites only `other` — outsider stays out.
    await _login(client, "l_owner2")
    await _invite(client, project_id, "l_other")

    await _login(client, "l_outsider")
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": other_id,
            "project_id": project_id,
            "framing": "not my project",
            "background": [],
            "options": [],
        },
    )
    assert r.status_code == 403, r.text


# ---------- reply: status flip + reply card + DM log --------------------


@pytest.mark.asyncio
async def test_reply_posts_reply_card_and_flips_status(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "l_maya3")
    project_id = await _intake(client, "L-reply-1")
    maya_id = await _me_id(client)
    await _register(client, "l_raj3")
    raj_id = await _me_id(client)
    await _login(client, "l_maya3")
    await _invite(client, project_id, "l_raj3")
    await backfill_streams_from_projects(maker)

    # Maya dispatches.
    dispatch = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": project_id,
            "framing": "boss tuning ask",
            "background": [],
            "options": [
                {
                    "id": "halve",
                    "label": "Halve boss HP",
                    "kind": "action",
                    "background": "",
                    "reason": "reduces grind",
                    "tradeoff": "less epic",
                    "weight": 0.6,
                }
            ],
        },
    )
    signal_id = dispatch.json()["signal"]["id"]

    # Raj replies.
    await _login(client, "l_raj3")
    r = await client.post(
        f"/api/routing/{signal_id}/reply",
        json={"option_id": "halve"},
    )
    assert r.status_code == 200, r.text
    signal = r.json()["signal"]
    assert signal["status"] == "replied"
    assert signal["reply"]["option_id"] == "halve"
    assert signal["responded_at"] is not None

    # The /reply endpoint goes through PersonalStreamService.handle_reply,
    # which suppresses the routed-reply summary in source's stream
    # (skip_source_post=True) and lets the LLM-framed edge-reply-frame
    # be the only card. So routed-reply should be ABSENT here. Direct
    # callers of RoutingService.reply (without the frame layer) still
    # get routed-reply via the default skip_source_post=False — covered
    # in the dedicated test below.
    async with session_scope(maker) as session:
        maya_personal = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == maya_id,
                )
            )
        ).scalar_one()
        reply_msgs = list(
            (
                await session.execute(
                    select(MessageRow).where(
                        MessageRow.stream_id == maya_personal.id,
                        MessageRow.kind == "routed-reply",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(reply_msgs) == 0

        # DM log on reply still posts a routed-dm-log (the dispatch path
        # dropped its log, but the reply path keeps one summary line so
        # the DM has the "B answered" beat). Exactly one for this signal.
        dm_logs = list(
            (
                await session.execute(
                    select(MessageRow).where(
                        MessageRow.kind == "routed-dm-log",
                        MessageRow.linked_id == signal_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(dm_logs) == 1

        # Signal row persisted the reply_json.
        row = (
            await session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.id == signal_id)
            )
        ).scalar_one()
        assert row.status == "replied"
        assert row.reply_json["option_id"] == "halve"


@pytest.mark.asyncio
async def test_reply_empty_payload_rejected(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "l_src_e")
    project_id = await _intake(client, "L-reply-empty")
    await _register(client, "l_tgt_e")
    tgt_id = await _me_id(client)
    await _login(client, "l_src_e")
    await _invite(client, project_id, "l_tgt_e")
    await backfill_streams_from_projects(maker)

    dispatch = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": project_id,
            "framing": "empty reply test",
            "background": [],
            "options": [
                {
                    "id": "a",
                    "label": "A",
                    "kind": "action",
                    "background": "",
                    "reason": "",
                    "tradeoff": "",
                    "weight": 0.5,
                }
            ],
        },
    )
    signal_id = dispatch.json()["signal"]["id"]

    await _login(client, "l_tgt_e")
    r = await client.post(
        f"/api/routing/{signal_id}/reply",
        json={"option_id": None, "custom_text": None},
    )
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_reply_twice_returns_409(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "l_src_2")
    project_id = await _intake(client, "L-reply-twice")
    await _register(client, "l_tgt_2")
    tgt_id = await _me_id(client)
    await _login(client, "l_src_2")
    await _invite(client, project_id, "l_tgt_2")
    await backfill_streams_from_projects(maker)

    dispatch = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": project_id,
            "framing": "double reply",
            "background": [],
            "options": [
                {
                    "id": "x",
                    "label": "X",
                    "kind": "action",
                    "background": "",
                    "reason": "",
                    "tradeoff": "",
                    "weight": 0.5,
                }
            ],
        },
    )
    signal_id = dispatch.json()["signal"]["id"]

    await _login(client, "l_tgt_2")
    first = await client.post(
        f"/api/routing/{signal_id}/reply", json={"option_id": "x"}
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/api/routing/{signal_id}/reply", json={"option_id": "x"}
    )
    assert second.status_code == 409, second.text


# ---------- inbox / outbox / fetch --------------------------------------


@pytest.mark.asyncio
async def test_inbox_returns_pending_signals_for_target(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "l_src_in")
    project_id = await _intake(client, "L-inbox-1")
    await _register(client, "l_tgt_in")
    tgt_id = await _me_id(client)
    await _login(client, "l_src_in")
    await _invite(client, project_id, "l_tgt_in")
    await backfill_streams_from_projects(maker)

    await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": project_id,
            "framing": "inbox test 1",
            "background": [],
            "options": [],
        },
    )

    await _login(client, "l_tgt_in")
    r = await client.get("/api/routing/inbox?status=pending")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["signals"]) == 1
    assert body["signals"][0]["framing"] == "inbox test 1"
    assert body["signals"][0]["status"] == "pending"

    # Outbox for the target should be empty.
    out = await client.get("/api/routing/outbox")
    assert out.status_code == 200
    assert out.json()["signals"] == []


@pytest.mark.asyncio
async def test_non_participant_cannot_fetch_signal(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "l_src_p")
    project_id = await _intake(client, "L-perm-1")
    await _register(client, "l_tgt_p")
    tgt_id = await _me_id(client)
    await _register(client, "l_third")
    await _login(client, "l_src_p")
    await _invite(client, project_id, "l_tgt_p")
    await _invite(client, project_id, "l_third")  # same project, but not part of routing
    await backfill_streams_from_projects(maker)

    dispatch = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": project_id,
            "framing": "private to src+tgt",
            "background": [],
            "options": [],
        },
    )
    signal_id = dispatch.json()["signal"]["id"]

    await _login(client, "l_third")
    r = await client.get(f"/api/routing/{signal_id}")
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_non_target_cannot_reply(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "l_src_nr")
    project_id = await _intake(client, "L-perm-2")
    await _register(client, "l_tgt_nr")
    tgt_id = await _me_id(client)
    await _register(client, "l_other_nr")
    await _login(client, "l_src_nr")
    await _invite(client, project_id, "l_tgt_nr")
    await _invite(client, project_id, "l_other_nr")
    await backfill_streams_from_projects(maker)

    dispatch = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": project_id,
            "framing": "only target can reply",
            "background": [],
            "options": [
                {
                    "id": "k",
                    "label": "K",
                    "kind": "action",
                    "background": "",
                    "reason": "",
                    "tradeoff": "",
                    "weight": 0.5,
                }
            ],
        },
    )
    signal_id = dispatch.json()["signal"]["id"]

    # Someone who is neither source nor target tries to reply.
    await _login(client, "l_other_nr")
    r = await client.post(
        f"/api/routing/{signal_id}/reply", json={"option_id": "k"}
    )
    assert r.status_code == 403, r.text

    # Even the source cannot reply to their own signal.
    await _login(client, "l_src_nr")
    r2 = await client.post(
        f"/api/routing/{signal_id}/reply", json={"option_id": "k"}
    )
    assert r2.status_code == 403, r2.text


# ---------- auth guard --------------------------------------------------


@pytest.mark.asyncio
async def test_inbox_requires_auth(api_env):
    client, _, _, _, _, _ = api_env
    client.cookies.clear()
    r = await client.get("/api/routing/inbox")
    assert r.status_code == 401, r.text


# ---------- reply framing (Phase O wiring) ------------------------------


@pytest.mark.asyncio
async def test_reply_posts_edge_reply_frame_in_source_stream(api_env):
    """After `POST /api/routing/{id}/reply`, the router delegates through
    `PersonalStreamService.handle_reply` which calls `EdgeAgent.frame_reply`
    and posts an `edge-reply-frame` system message into the source's
    personal stream. This test uses a stub EdgeAgent that produces a
    scripted FramedReply so we can verify the wiring without an LLM.
    """
    from workgraph_agents import (
        EdgeResponse,
        EdgeResponseOutcome,
        FramedReply,
        FramedReplyOutcome,
        RoutedOption,
        RoutedOptionsOutcome,
    )
    from workgraph_agents.llm import LLMResult
    from workgraph_api.main import app
    from workgraph_api.services import PersonalStreamService

    class _FrameStub:
        def __init__(self) -> None:
            self.frame_calls: list[dict] = []

        def _result(self) -> LLMResult:
            return LLMResult(
                content="",
                model="stub",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
            )

        async def respond(self, *, user_message, context):
            return EdgeResponseOutcome(
                response=EdgeResponse(kind="silence", body=None, route_targets=[]),
                result=self._result(),
                outcome="ok",
                attempts=1,
            )

        async def generate_options(self, *, routing_context):
            raise NotImplementedError

        async def frame_reply(self, *, signal, source_user_context):
            self.frame_calls.append(
                {"signal": signal, "source_user_context": source_user_context}
            )
            return FramedReplyOutcome(
                framed=FramedReply(
                    body="Raj said: halve boss HP. That reduces grind.",
                    action_hint="accept",
                    attach_options=False,
                    reasoning="direct option pick",
                ),
                result=self._result(),
                outcome="ok",
                attempts=1,
            )

    client, maker, bus, *_ = api_env
    stub = _FrameStub()
    # Wire the personal service to our frame-capable stub without losing
    # the real RoutingService + StreamService from api_env.
    app.state.personal_service = PersonalStreamService(
        maker,
        app.state.stream_service,
        app.state.routing_service,
        stub,
        bus,
    )
    app.state.edge_agent = stub

    await _register(client, "o_maya")
    project_id = await _intake(client, "O-frame-1")
    maya_id = await _me_id(client)
    await _register(client, "o_raj")
    raj_id = await _me_id(client)
    await _login(client, "o_maya")
    await _invite(client, project_id, "o_raj")
    await backfill_streams_from_projects(maker)

    dispatch = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": project_id,
            "framing": "boss tuning ask",
            "background": [],
            "options": [
                {
                    "id": "halve",
                    "label": "Halve boss HP",
                    "kind": "action",
                    "background": "",
                    "reason": "reduces grind",
                    "tradeoff": "less epic",
                    "weight": 0.6,
                }
            ],
        },
    )
    signal_id = dispatch.json()["signal"]["id"]

    # Raj replies. The router delegates to PersonalStreamService.handle_reply
    # which in turn calls RoutingService.reply + EdgeAgent.frame_reply.
    await _login(client, "o_raj")
    reply = await client.post(
        f"/api/routing/{signal_id}/reply",
        json={"option_id": "halve"},
    )
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["signal"]["status"] == "replied"
    assert body["framed"] is not None
    assert "halve" in body["framed"]["body"].lower() or "boss" in body["framed"]["body"].lower()
    assert body["framed"]["action_hint"] == "accept"

    # frame_reply was called with the shaped signal payload (contains
    # source context). Source's personal stream gets ONLY the framed
    # card now — the routed-reply summary is suppressed via
    # skip_source_post=True so the user doesn't see the same reply
    # rendered twice. (Pre-2026-04-25 both kinds landed and the
    # frontend deduped; the dual-write was the real bug.)
    assert len(stub.frame_calls) == 1
    call = stub.frame_calls[0]
    assert call["signal"]["id"] == signal_id
    assert call["source_user_context"]["id"] == maya_id

    async with session_scope(maker) as session:
        maya_personal = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == maya_id,
                )
            )
        ).scalar_one()
        rows_by_kind: dict[str, list[MessageRow]] = {}
        rows = list(
            (
                await session.execute(
                    select(MessageRow)
                    .where(MessageRow.stream_id == maya_personal.id)
                    .order_by(MessageRow.created_at)
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            rows_by_kind.setdefault(r.kind, []).append(r)

        # No routed-reply mirror — suppressed via skip_source_post.
        routed_reply_msgs = rows_by_kind.get("routed-reply", [])
        assert len(routed_reply_msgs) == 0
        # The source-side framed card landed.
        frame_msgs = rows_by_kind.get("edge-reply-frame", [])
        assert len(frame_msgs) == 1
        assert frame_msgs[0].linked_id == signal_id
        assert frame_msgs[0].author_id == EDGE_AGENT_SYSTEM_USER_ID
        assert "halve" in frame_msgs[0].body.lower() or "boss" in frame_msgs[0].body.lower()


# ---------- R2 — backend route grounding gate ---------------------------


@pytest.mark.asyncio
async def test_r2_dispatch_persists_routing_basis_when_no_signal(api_env):
    """Cold-start project (no graph state for routing_suggest to score
    against) → dispatch still succeeds with grounded=False in
    routing_basis. Audit-visible but not blocking."""
    client, maker, *_ = api_env
    await _register(client, "r2_a_maya")
    project_id = await _intake(client, "R2-cold-start")
    maya_id = await _me_id(client)
    await _register(client, "r2_a_raj")
    raj_id = await _me_id(client)
    await _login(client, "r2_a_maya")
    await _invite(client, project_id, "r2_a_raj")
    await backfill_streams_from_projects(maker)

    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": project_id,
            "framing": "Should we keep the boss permadeath rule?",
            "background": [],
            "options": [
                {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                {"id": "n", "label": "No", "kind": "action", "weight": 0.5},
            ],
        },
    )
    assert r.status_code == 200, r.text
    signal_id = r.json()["signal"]["id"]

    # Inspect persisted background_json — the routing_basis envelope
    # must be there, marked grounded=False because the cold-start
    # project has no scoreable activity.
    async with session_scope(maker) as session:
        from workgraph_persistence import RoutedSignalRow

        signal = (
            await session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.id == signal_id)
            )
        ).scalar_one()
        bg = list(signal.background_json or [])
    basis_entries = [e for e in bg if e.get("source") == "routing_basis"]
    assert len(basis_entries) == 1, bg
    basis = basis_entries[0]["routing_basis"]
    assert basis["grounded"] is False
    assert basis["reason"] in (
        "no_signal_in_project_state",
        "skills_service_unattached",
    )


@pytest.mark.asyncio
async def test_r2_dispatch_blocks_target_not_in_suggestions(api_env):
    """When routing_suggest returns a non-empty set that does NOT
    include the chosen target_user_id, dispatch must reject with 422
    target_not_grounded. The error payload returns the alternatives
    so the FE can re-prompt with one of them."""
    from workgraph_api.main import app

    client, maker, *_ = api_env
    await _register(client, "r2_b_maya")
    project_id = await _intake(client, "R2-blocks")
    maya_id = await _me_id(client)
    await _register(client, "r2_b_raj")
    raj_id = await _me_id(client)
    await _register(client, "r2_b_aiko")
    aiko_id = await _me_id(client)
    await _login(client, "r2_b_maya")
    await _invite(client, project_id, "r2_b_raj")
    await _invite(client, project_id, "r2_b_aiko")
    await backfill_streams_from_projects(maker)

    # Stub SkillsService.suggest_routing to return Aiko but NOT Raj —
    # simulating a real-graph case where the BE scorer would only
    # surface the qualified target. The proposer (Maya) tries to
    # route to Raj anyway; gate must reject.
    saved_skills = app.state.routing_service._skills_service

    class _StubSkills:
        async def suggest_routing(self, **kwargs):
            return [
                {
                    "user_id": aiko_id,
                    "display_name": "Aiko",
                    "role": "engineer",
                    "score": 0.9,
                    "graph_score": 0.9,
                    "activity_score": 0.5,
                    "profile_score": 0.7,
                    "reason": "graph-adjacent work",
                },
            ]

    app.state.routing_service._skills_service = _StubSkills()
    try:
        r = await client.post(
            "/api/routing/dispatch",
            json={
                "target_user_id": raj_id,
                "project_id": project_id,
                "framing": "Boss tuning calibration ask.",
                "background": [],
                "options": [
                    {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                ],
            },
        )
        assert r.status_code == 422, r.text
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "target_not_grounded"
        assert any(a.get("user_id") == aiko_id for a in body["alternatives"])
    finally:
        app.state.routing_service._skills_service = saved_skills


@pytest.mark.asyncio
async def test_r2_dispatch_grounds_when_target_in_suggestions(api_env):
    """When the chosen target IS in the suggestion set, dispatch
    succeeds and persists the matched suggestion as routing_basis."""
    from workgraph_api.main import app

    client, maker, *_ = api_env
    await _register(client, "r2_c_maya")
    project_id = await _intake(client, "R2-grounded")
    maya_id = await _me_id(client)
    await _register(client, "r2_c_raj")
    raj_id = await _me_id(client)
    await _login(client, "r2_c_maya")
    await _invite(client, project_id, "r2_c_raj")
    await backfill_streams_from_projects(maker)

    saved_skills = app.state.routing_service._skills_service

    class _StubSkills:
        async def suggest_routing(self, **kwargs):
            return [
                {
                    "user_id": raj_id,
                    "display_name": "Raj",
                    "role": "designer",
                    "score": 0.85,
                    "graph_score": 0.7,
                    "activity_score": 0.6,
                    "profile_score": 0.9,
                    "reason": "self-declared expertise",
                },
            ]

    app.state.routing_service._skills_service = _StubSkills()
    try:
        r = await client.post(
            "/api/routing/dispatch",
            json={
                "target_user_id": raj_id,
                "project_id": project_id,
                "framing": "Boss permadeath calibration ask.",
                "background": [],
                "options": [
                    {"id": "y", "label": "Yes", "kind": "action", "weight": 0.5},
                ],
            },
        )
        assert r.status_code == 200, r.text
        signal_id = r.json()["signal"]["id"]

        async with session_scope(maker) as session:
            from workgraph_persistence import RoutedSignalRow

            signal = (
                await session.execute(
                    select(RoutedSignalRow).where(
                        RoutedSignalRow.id == signal_id
                    )
                )
            ).scalar_one()
            bg = list(signal.background_json or [])
        basis_entries = [e for e in bg if e.get("source") == "routing_basis"]
        assert len(basis_entries) == 1, bg
        basis = basis_entries[0]["routing_basis"]
        assert basis["grounded"] is True
        assert basis["matched_suggestion"]["user_id"] == raj_id
    finally:
        app.state.routing_service._skills_service = saved_skills


# ---------- routed-inbound source-human attribution ---------------------
# RoutedInboundCard used to read message.author_id (which is the shared
# EDGE_AGENT_SYSTEM_USER_ID), causing "from 🧠 Edge" to render as the
# asker. Fix: PersonalStreamService.list_messages now hydrates
# routed_signal_source_user_id / display_name / username from the
# linked RoutedSignalRow. These tests pin both the new contract and
# the regression on an existing Edge-authored row.


@pytest.mark.asyncio
async def test_routed_inbound_payload_carries_source_human_fields(api_env):
    """PersonalStreamService.list_messages must surface
    routed_signal_source_* on every routed-inbound message so the FE
    never has to render the EDGE_AGENT_SYSTEM_USER_ID author."""
    client, maker, _, _, _, _ = api_env
    await _register(client, "ria_maya")
    project_id = await _intake(client, "RIA-attr-1")
    maya_id = await _me_id(client)
    await _register(client, "ria_raj")
    raj_id = await _me_id(client)
    await _login(client, "ria_maya")
    await _invite(client, project_id, "ria_raj")

    await backfill_streams_from_projects(maker)

    # Maya routes a question to Raj.
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": raj_id,
            "project_id": project_id,
            "framing": "Should we drop permadeath for the boss rooms?",
            "background": [],
            "options": [
                {
                    "id": "drop",
                    "label": "Drop permadeath",
                    "kind": "action",
                    "background": "",
                    "reason": "",
                    "tradeoff": "",
                    "weight": 0.6,
                },
            ],
        },
    )
    assert r.status_code == 200, r.text

    # Raj reads his personal stream — the routed-inbound payload must
    # name MAYA, not the edge-agent.
    await _login(client, "ria_raj")
    r = await client.get(f"/api/personal/{project_id}/messages")
    assert r.status_code == 200, r.text
    msgs = r.json()["messages"]
    inbound = [m for m in msgs if m["kind"] == "routed-inbound"]
    assert len(inbound) == 1, msgs
    pkt = inbound[0]
    # The MessageRow author IS the edge-agent — that part is intentional.
    assert pkt["author_id"] == EDGE_AGENT_SYSTEM_USER_ID
    # But the source-human fields name Maya.
    assert pkt["routed_signal_source_user_id"] == maya_id
    assert pkt["routed_signal_source_username"] == "ria_maya"
    # display_name may be None if the user hasn't set one — assert
    # presence-of-key (the FE will fall back to username) rather than
    # value, since display_name is optional on UserRow.
    assert "routed_signal_source_display_name" in pkt


@pytest.mark.asyncio
async def test_routed_inbound_legacy_row_still_resolves_source_human(api_env):
    """Regression: a routed-inbound MessageRow that was written BEFORE
    the hydration fix (still authored by EDGE_AGENT_SYSTEM_USER_ID) must
    still resolve the source human via the linked RoutedSignalRow.

    Simulated by dispatching, then asserting the payload independently of
    any author_display_name fallback."""
    client, maker, _, _, _, _ = api_env
    await _register(client, "ria_legacy_src")
    project_id = await _intake(client, "RIA-legacy-1")
    src_id = await _me_id(client)
    await _register(client, "ria_legacy_tgt")
    tgt_id = await _me_id(client)
    await _login(client, "ria_legacy_src")
    await _invite(client, project_id, "ria_legacy_tgt")
    await backfill_streams_from_projects(maker)

    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": tgt_id,
            "project_id": project_id,
            "framing": "Legacy attribution check",
            "background": [],
            "options": [
                {
                    "id": "ack",
                    "label": "Ack",
                    "kind": "action",
                    "background": "",
                    "reason": "",
                    "tradeoff": "",
                    "weight": 1.0,
                },
            ],
        },
    )
    assert r.status_code == 200, r.text

    # Confirm the underlying row is the legacy shape (authored by
    # EDGE_AGENT_SYSTEM_USER_ID, source truth on RoutedSignalRow).
    async with session_scope(maker) as session:
        msg_row = (
            await session.execute(
                select(MessageRow).where(
                    MessageRow.kind == "routed-inbound",
                    MessageRow.project_id == project_id,
                )
            )
        ).scalar_one()
        assert msg_row.author_id == EDGE_AGENT_SYSTEM_USER_ID
        signal = (
            await session.execute(
                select(RoutedSignalRow).where(
                    RoutedSignalRow.id == msg_row.linked_id
                )
            )
        ).scalar_one()
        assert signal.source_user_id == src_id

    await _login(client, "ria_legacy_tgt")
    r = await client.get(f"/api/personal/{project_id}/messages")
    assert r.status_code == 200, r.text
    inbound = next(
        m for m in r.json()["messages"] if m["kind"] == "routed-inbound"
    )
    # The fix lifts the source human onto the payload regardless of
    # who authored the MessageRow.
    assert inbound["routed_signal_source_user_id"] == src_id
    assert inbound["routed_signal_source_username"] == "ria_legacy_src"


def test_locales_have_no_user_visible_edge_attribution():
    """i18n guard — every user-facing routed-inbound / reply / preview
    string must say "项目助手" or "Project assistant", never raw "Edge"
    or "🧠 Edge". The internal kind keys (edge-answer, edge-clarify,
    discussWithEdge as a translation KEY name) are fine — they don't
    render to users."""
    import json
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    locales_dir = repo_root / "apps" / "web" / "src" / "i18n" / "locales"

    banned_substrings = (
        "🧠 Edge",
        "🤖 Edge",
        "Edge 的新路由",
        "Edge的新路由",
        "via edge",
        "边缘代理",
    )

    def visit(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                visit(v, f"{path}.{k}")
        elif isinstance(node, str):
            for b in banned_substrings:
                assert b not in node, (
                    f"locale string {path} still contains banned "
                    f"user-visible Edge attribution: {b!r} — value: {node!r}"
                )

    for locale_file in ("zh.json", "en.json"):
        with (locales_dir / locale_file).open(encoding="utf-8") as fh:
            data = json.load(fh)
        visit(data, locale_file)


@pytest.mark.asyncio
async def test_edge_agent_legacy_display_name_migrated(api_env):
    """Boot migrates a legacy `🧠 Edge` display name to `项目助手` so
    any FE path that surfaces author_display_name reads cleanly."""
    from workgraph_persistence import ensure_edge_agent_system_user

    _, maker, _, _, _, _ = api_env

    # Force the row back to the legacy display name to simulate a prod
    # row seeded before the rename.
    async with session_scope(maker) as session:
        legacy = (
            await session.execute(
                select(UserRow).where(UserRow.id == EDGE_AGENT_SYSTEM_USER_ID)
            )
        ).scalar_one()
        legacy.display_name = "🧠 Edge"
        await session.flush()

    # Re-running the seeder must migrate the legacy name.
    await ensure_edge_agent_system_user(maker)

    async with session_scope(maker) as session:
        migrated = (
            await session.execute(
                select(UserRow).where(UserRow.id == EDGE_AGENT_SYSTEM_USER_ID)
            )
        ).scalar_one()
    assert migrated.display_name == "项目助手"


# ---------------------------------------------------------------------------
# C-min telemetry — routing.opened on GET, routing.accepted on accept.
# ---------------------------------------------------------------------------


async def _dispatch_signal(client, project_id, target_id, framing="ask"):
    r = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": target_id,
            "project_id": project_id,
            "framing": framing,
            "background": [],
            "options": [
                {
                    "id": "ok",
                    "label": "Sounds good",
                    "kind": "action",
                    "background": "",
                    "reason": "r",
                    "tradeoff": "t",
                    "weight": 0.6,
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["signal"]["id"]


@pytest.mark.asyncio
async def test_get_signal_emits_routing_opened(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "tel_src")
    project_id = await _intake(client, "TEL-opened")
    await _register(client, "tel_tgt")
    tgt_id = await _me_id(client)
    await _login(client, "tel_src")
    await _invite(client, project_id, "tel_tgt")
    await backfill_streams_from_projects(maker)

    signal_id = await _dispatch_signal(client, project_id, tgt_id)

    # Target opens the routed ask.
    await _login(client, "tel_tgt")
    r = await client.get(f"/api/routing/{signal_id}")
    assert r.status_code == 200, r.text

    async with session_scope(maker) as session:
        opened = await EventRepository(session).list_by_name("routing.opened")
    mine = [e for e in opened if e.payload["signal_id"] == signal_id]
    assert mine, "routing.opened was not emitted"
    assert mine[-1].payload["is_target"] is True


@pytest.mark.asyncio
async def test_accept_emits_routing_accepted_once(api_env):
    client, maker, _, _, _, _ = api_env
    await _register(client, "tel_src2")
    project_id = await _intake(client, "TEL-accepted")
    src_id = await _me_id(client)
    await _register(client, "tel_tgt2")
    tgt_id = await _me_id(client)
    await _login(client, "tel_src2")
    await _invite(client, project_id, "tel_tgt2")
    await backfill_streams_from_projects(maker)

    signal_id = await _dispatch_signal(client, project_id, tgt_id)

    # Target replies → status becomes 'replied'.
    await _login(client, "tel_tgt2")
    rep = await client.post(
        f"/api/routing/{signal_id}/reply", json={"option_id": "ok"}
    )
    assert rep.status_code == 200, rep.text

    # Source accepts → routing.accepted emitted exactly once.
    await _login(client, "tel_src2")
    acc = await client.post(f"/api/routing/{signal_id}/accept")
    assert acc.status_code == 200, acc.text
    # Idempotent re-accept must NOT emit a second event.
    acc2 = await client.post(f"/api/routing/{signal_id}/accept")
    assert acc2.status_code == 200, acc2.text

    async with session_scope(maker) as session:
        accepted = await EventRepository(session).list_by_name("routing.accepted")
    mine = [e for e in accepted if e.payload["signal_id"] == signal_id]
    assert len(mine) == 1, f"expected exactly one routing.accepted, got {len(mine)}"
    assert mine[0].payload["source_user_id"] == src_id
