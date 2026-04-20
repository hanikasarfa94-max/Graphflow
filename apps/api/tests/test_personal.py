"""Phase N — PersonalStreamService glue tests.

Drives the user-post → EdgeAgent → reply flow through the HTTP surface,
with a stub EdgeAgent so no LLM is called. Covers:

  * silence response — user message persists, no edge follow-up
  * answer response  — user message + edge-answer follow-up
  * clarify response — user message + edge-clarify follow-up
  * route_proposal   — user message + edge-route-proposal with the
                       target payload round-trippable from the body marker
  * confirm_route    — source clicks "Ask X" → RoutingService dispatch +
                       inbound card in target personal stream
  * messages GET     — returns messages with route-proposal metadata parsed
  * auth guard       — endpoints require a session cookie
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from workgraph_agents import (
    EdgeResponse,
    EdgeResponseOutcome,
    FramedReply,
    FramedReplyOutcome,
    RoutedOption,
    RoutedOptionsOutcome,
    RouteTarget,
)
from workgraph_agents.llm import LLMResult
from workgraph_api.main import app
from workgraph_api.services import PersonalStreamService
from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    MessageRow,
    RoutedSignalRow,
    StreamRow,
    backfill_streams_from_projects,
    session_scope,
)


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


# ---------------------------------------------------------------------------
# Stub EdgeAgent — scriptable per-method outputs.
# ---------------------------------------------------------------------------


class _StubEdgeAgent:
    """Scriptable EdgeAgent. Each of the three methods reads from its own
    queue and returns a prebuilt outcome. Tests populate the queues they
    need.
    """

    def __init__(self) -> None:
        self.respond_queue: list[EdgeResponse] = []
        self.options_queue: list[list[RoutedOption]] = []
        self.framed_queue: list[FramedReply] = []
        self.respond_calls: list[dict] = []
        self.options_calls: list[dict] = []
        self.framed_calls: list[dict] = []

    def _result(self) -> LLMResult:
        return LLMResult(
            content="",
            model="stub",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
        )

    async def respond(self, *, user_message, context):
        self.respond_calls.append({"user_message": user_message, "context": context})
        response = self.respond_queue.pop(0)
        return EdgeResponseOutcome(
            response=response,
            result=self._result(),
            outcome="ok",
            attempts=1,
        )

    async def generate_options(self, *, routing_context):
        self.options_calls.append({"routing_context": routing_context})
        options = self.options_queue.pop(0)
        return RoutedOptionsOutcome(
            options=options,
            result=self._result(),
            outcome="ok",
            attempts=1,
        )

    async def frame_reply(self, *, signal, source_user_context):
        self.framed_calls.append(
            {"signal": signal, "source_user_context": source_user_context}
        )
        framed = self.framed_queue.pop(0)
        return FramedReplyOutcome(
            framed=framed,
            result=self._result(),
            outcome="ok",
            attempts=1,
        )


def _install_stub(api_env_tuple) -> _StubEdgeAgent:
    """Swap app.state.personal_service for one wired to a scriptable stub."""
    _client, maker, bus, *_ = api_env_tuple
    stub = _StubEdgeAgent()
    personal_service = PersonalStreamService(
        maker,
        app.state.stream_service,
        app.state.routing_service,
        stub,
        bus,
    )
    app.state.personal_service = personal_service
    app.state.edge_agent = stub
    return stub


# ---------------------------------------------------------------------------
# Shared helpers (match test_routing.py style).
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# post — silence / answer / clarify / route_proposal.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_silence_creates_only_user_message(api_env):
    client, maker, *_ = api_env
    stub = _install_stub(api_env)
    stub.respond_queue.append(
        EdgeResponse(kind="silence", body=None, route_targets=[])
    )

    await _register(client, "n_maya")
    project_id = await _intake(client, "N-silence-1")
    maya_id = await _me_id(client)
    await backfill_streams_from_projects(maker)

    r = await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "standup note, no follow-up needed"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["edge_response"]["kind"] == "silence"

    async with session_scope(maker) as session:
        stream = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == maya_id,
                )
            )
        ).scalar_one()
        rows = list(
            (
                await session.execute(
                    select(MessageRow).where(MessageRow.stream_id == stream.id)
                )
            )
            .scalars()
            .all()
        )
    # Only the user's own message — no edge follow-up.
    assert len(rows) == 1
    assert rows[0].author_id == maya_id
    assert rows[0].kind == "text"


@pytest.mark.asyncio
async def test_post_answer_creates_edge_answer_message(api_env):
    client, maker, *_ = api_env
    stub = _install_stub(api_env)
    stub.respond_queue.append(
        EdgeResponse(
            kind="answer",
            body="Sofia's playtest from Tuesday shows 40% rage-quit on boss 1.",
            route_targets=[],
        )
    )

    await _register(client, "n_maya2")
    project_id = await _intake(client, "N-answer-1")
    maya_id = await _me_id(client)
    await backfill_streams_from_projects(maker)

    r = await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "What was the boss-1 rage-quit rate last playtest?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["edge_response"]["kind"] == "answer"
    assert "40%" in body["edge_response"]["body"]

    async with session_scope(maker) as session:
        stream = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == maya_id,
                )
            )
        ).scalar_one()
        rows = list(
            (
                await session.execute(
                    select(MessageRow)
                    .where(MessageRow.stream_id == stream.id)
                    .order_by(MessageRow.created_at)
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 2
    assert rows[0].author_id == maya_id and rows[0].kind == "text"
    assert rows[1].author_id == EDGE_AGENT_SYSTEM_USER_ID
    assert rows[1].kind == "edge-answer"
    assert "40%" in rows[1].body


@pytest.mark.asyncio
async def test_post_clarify_creates_edge_clarify_message(api_env):
    client, maker, *_ = api_env
    stub = _install_stub(api_env)
    stub.respond_queue.append(
        EdgeResponse(
            kind="clarify",
            body="Do you mean drop permadeath entirely, or only for bosses?",
            route_targets=[],
        )
    )

    await _register(client, "n_maya_cl")
    project_id = await _intake(client, "N-clarify-1")
    maya_id = await _me_id(client)
    await backfill_streams_from_projects(maker)

    r = await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "Should we drop permadeath?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["edge_response"]["kind"] == "clarify"

    async with session_scope(maker) as session:
        stream = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == maya_id,
                )
            )
        ).scalar_one()
        edge_rows = list(
            (
                await session.execute(
                    select(MessageRow).where(
                        MessageRow.stream_id == stream.id,
                        MessageRow.kind == "edge-clarify",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(edge_rows) == 1
    assert "bosses" in edge_rows[0].body


@pytest.mark.asyncio
async def test_post_route_proposal_encodes_targets_in_body(api_env):
    client, maker, *_ = api_env
    stub = _install_stub(api_env)

    await _register(client, "n_src_rp")
    project_id = await _intake(client, "N-route-1")
    src_id = await _me_id(client)
    await _register(client, "n_raj_rp")
    raj_id = await _me_id(client)
    await _login(client, "n_src_rp")
    await _invite(client, project_id, "n_raj_rp")
    await backfill_streams_from_projects(maker)

    stub.respond_queue.append(
        EdgeResponse(
            kind="route_proposal",
            body="This is a design call. Want me to ask Raj with the playtest attached?",
            route_targets=[
                RouteTarget(
                    user_id=raj_id,
                    username="n_raj_rp",
                    display_name="",
                    rationale="Raj owns combat design.",
                )
            ],
        )
    )

    r = await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "Should we drop permadeath for the boss rooms?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["edge_response"]["kind"] == "route_proposal"
    proposal_id = body["edge_response"]["route_proposal_id"]
    assert proposal_id
    assert body["edge_response"]["targets"][0]["user_id"] == raj_id

    # The stored message body contains the <route-proposal> marker with
    # targets encoded so the frontend can parse without a new ORM table.
    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(MessageRow).where(MessageRow.id == proposal_id)
            )
        ).scalar_one()
    assert row.kind == "edge-route-proposal"
    assert row.author_id == EDGE_AGENT_SYSTEM_USER_ID
    assert "<route-proposal>" in row.body
    assert raj_id in row.body


# ---------------------------------------------------------------------------
# confirm_route — dispatch via RoutingService.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_route_dispatches_via_routing_service(api_env):
    client, maker, *_ = api_env
    stub = _install_stub(api_env)

    await _register(client, "n_src_cr")
    project_id = await _intake(client, "N-confirm-1")
    src_id = await _me_id(client)
    await _register(client, "n_raj_cr")
    raj_id = await _me_id(client)
    await _login(client, "n_src_cr")
    await _invite(client, project_id, "n_raj_cr")
    await backfill_streams_from_projects(maker)

    # First, the source's sub-agent surfaces a route proposal.
    stub.respond_queue.append(
        EdgeResponse(
            kind="route_proposal",
            body="Design call — ask Raj?",
            route_targets=[
                RouteTarget(
                    user_id=raj_id,
                    username="n_raj_cr",
                    display_name="Raj",
                    rationale="",
                )
            ],
        )
    )
    post_result = await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "Drop permadeath for bosses?"},
    )
    proposal_id = post_result.json()["edge_response"]["route_proposal_id"]

    # Second, the target's sub-agent produces options when the source
    # confirms.
    stub.options_queue.append(
        [
            RoutedOption(
                id="accept-id",
                label="Accept",
                kind="accept",
                background="",
                reason="matches data",
                tradeoff="loses stakes",
                weight=0.7,
            ),
            RoutedOption(
                id="counter-id",
                label="Counter: boss-only",
                kind="counter",
                background="",
                reason="preserves normal stakes",
                tradeoff="more QA",
                weight=0.3,
            ),
        ]
    )

    r = await client.post(
        f"/api/personal/route/{proposal_id}/confirm",
        json={"target_user_id": raj_id},
    )
    assert r.status_code == 200, r.text
    signal_id = r.json()["signal_id"]

    # A RoutedSignalRow now exists with status='pending' targeting Raj.
    async with session_scope(maker) as session:
        signal = (
            await session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.id == signal_id)
            )
        ).scalar_one()
        assert signal.source_user_id == src_id
        assert signal.target_user_id == raj_id
        assert signal.status == "pending"
        assert len(signal.options_json) == 2

        # Raj's personal stream got a 'routed-inbound' card.
        raj_personal = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == raj_id,
                )
            )
        ).scalar_one()
        inbound = list(
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
        assert len(inbound) == 1
        assert inbound[0].linked_id == signal_id

        # Source's personal stream got a follow-up confirm turn.
        src_personal = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == src_id,
                )
            )
        ).scalar_one()
        confirms = list(
            (
                await session.execute(
                    select(MessageRow).where(
                        MessageRow.stream_id == src_personal.id,
                        MessageRow.kind == "edge-route-confirmed",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(confirms) == 1
        assert confirms[0].linked_id == signal_id


@pytest.mark.asyncio
async def test_confirm_route_rejects_wrong_target(api_env):
    client, maker, *_ = api_env
    stub = _install_stub(api_env)

    await _register(client, "n_src_wt")
    project_id = await _intake(client, "N-confirm-wrong")
    src_id = await _me_id(client)
    await _register(client, "n_raj_wt")
    raj_id = await _me_id(client)
    await _register(client, "n_third_wt")
    third_id = await _me_id(client)
    await _login(client, "n_src_wt")
    await _invite(client, project_id, "n_raj_wt")
    await _invite(client, project_id, "n_third_wt")
    await backfill_streams_from_projects(maker)

    stub.respond_queue.append(
        EdgeResponse(
            kind="route_proposal",
            body="ask Raj?",
            route_targets=[
                RouteTarget(
                    user_id=raj_id,
                    username="n_raj_wt",
                    display_name="Raj",
                    rationale="",
                )
            ],
        )
    )
    post_result = await client.post(
        f"/api/personal/{project_id}/post", json={"body": "design call"}
    )
    proposal_id = post_result.json()["edge_response"]["route_proposal_id"]

    # Try to confirm for someone the proposal never named.
    r = await client.post(
        f"/api/personal/route/{proposal_id}/confirm",
        json={"target_user_id": third_id},
    )
    assert r.status_code == 400, r.text


# ---------------------------------------------------------------------------
# list messages — parsed route-proposal metadata.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_messages_returns_parsed_route_proposal(api_env):
    client, maker, *_ = api_env
    stub = _install_stub(api_env)

    await _register(client, "n_src_ls")
    project_id = await _intake(client, "N-list-1")
    src_id = await _me_id(client)
    await _register(client, "n_raj_ls")
    raj_id = await _me_id(client)
    await _login(client, "n_src_ls")
    await _invite(client, project_id, "n_raj_ls")
    await backfill_streams_from_projects(maker)

    stub.respond_queue.append(
        EdgeResponse(
            kind="route_proposal",
            body="ask Raj?",
            route_targets=[
                RouteTarget(
                    user_id=raj_id,
                    username="n_raj_ls",
                    display_name="Raj",
                    rationale="combat design owner",
                )
            ],
        )
    )
    await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "should we drop permadeath?"},
    )

    r = await client.get(f"/api/personal/{project_id}/messages")
    assert r.status_code == 200, r.text
    body = r.json()
    msgs = body["messages"]
    proposal_msgs = [m for m in msgs if m["kind"] == "edge-route-proposal"]
    assert len(proposal_msgs) == 1
    meta = proposal_msgs[0].get("route_proposal")
    assert meta is not None
    assert meta["targets"][0]["user_id"] == raj_id
    assert meta["status"] == "pending"
    # The body returned to the frontend is the human text, not the marker.
    assert "<route-proposal>" not in proposal_msgs[0]["body"]


# ---------------------------------------------------------------------------
# Auth guard.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_post_requires_auth(api_env):
    client, *_ = api_env
    client.cookies.clear()
    r = await client.post(
        "/api/personal/anything/post", json={"body": "hi"}
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_personal_messages_requires_auth(api_env):
    client, *_ = api_env
    client.cookies.clear()
    r = await client.get("/api/personal/anything/messages")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# preview — pre-commit rehearsal (vision.md §5.3).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_returns_edge_response_shape(api_env):
    """preview() returns the EdgeResponse shape the real post() would
    emit, without persisting anything.
    """
    client, maker, *_ = api_env
    stub = _install_stub(api_env)

    await _register(client, "n_src_pv")
    project_id = await _intake(client, "N-preview-1")
    src_id = await _me_id(client)
    await _register(client, "n_raj_pv")
    raj_id = await _me_id(client)
    await _login(client, "n_src_pv")
    await _invite(client, project_id, "n_raj_pv")
    await backfill_streams_from_projects(maker)

    # Simulate the canonical "should I drop permadeath" rehearsal — the
    # edge stub returns a route_proposal so the UI can render the "↗"
    # preview card.
    stub.respond_queue.append(
        EdgeResponse(
            kind="route_proposal",
            body="This is a design call. Want me to ask Raj with the playtest attached?",
            reasoning="40% rage-quit rate + permadeath decision three weeks old",
            route_targets=[
                RouteTarget(
                    user_id=raj_id,
                    username="n_raj_pv",
                    display_name="Raj",
                    rationale="combat design owner",
                )
            ],
        )
    )

    r = await client.post(
        f"/api/personal/{project_id}/preview",
        json={"body": "should I drop permadeath given the rage-quit data?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    preview = body["preview"]
    assert preview["kind"] == "route_proposal"
    assert "Raj" in preview["body"]
    assert preview["targets"][0]["user_id"] == raj_id
    assert preview["targets"][0]["display_name"] == "Raj"
    assert preview["targets"][0]["rationale"] == "combat design owner"
    # reasoning is exposed for the devil's-advocate affordance.
    assert "rage-quit" in preview["reasoning"]


@pytest.mark.asyncio
async def test_preview_short_body_short_circuits_without_llm(api_env):
    """<10 char drafts must return silent_preview without invoking the
    edge agent (token budget guard).
    """
    client, maker, *_ = api_env
    stub = _install_stub(api_env)

    await _register(client, "n_src_short")
    project_id = await _intake(client, "N-preview-short")
    await backfill_streams_from_projects(maker)

    # Nothing queued — if the service touches the stub we'd pop from an
    # empty list and raise.
    r = await client.post(
        f"/api/personal/{project_id}/preview",
        json={"body": "hi"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["preview"] == {"kind": "silent_preview"}
    assert stub.respond_calls == []


@pytest.mark.asyncio
async def test_preview_rate_limit_returns_429(api_env):
    """Two previews within PREVIEW_RATE_LIMIT_SECONDS must 429 with
    retry_after_ms so the frontend can back off.
    """
    client, maker, *_ = api_env
    stub = _install_stub(api_env)

    await _register(client, "n_src_rl")
    project_id = await _intake(client, "N-preview-rl")
    await backfill_streams_from_projects(maker)

    # Queue one silence response — second call should NOT reach the stub.
    stub.respond_queue.append(
        EdgeResponse(kind="silence", body=None, route_targets=[])
    )

    body_payload = {"body": "a long enough draft to pass the short-circuit"}
    r1 = await client.post(
        f"/api/personal/{project_id}/preview", json=body_payload
    )
    assert r1.status_code == 200, r1.text

    r2 = await client.post(
        f"/api/personal/{project_id}/preview", json=body_payload
    )
    assert r2.status_code == 429, r2.text
    body = r2.json()
    assert body["detail"] == "rate_limited"
    assert "retry_after_ms" in body
    assert body["retry_after_ms"] >= 0
    # Only one real respond() call — the second was throttled before it
    # hit the LLM.
    assert len(stub.respond_calls) == 1


@pytest.mark.asyncio
async def test_preview_does_not_persist_messages(api_env):
    """N previews must leave zero messages in the personal stream — this
    is the load-bearing invariant of pre-commit rehearsal.
    """
    client, maker, *_ = api_env
    stub = _install_stub(api_env)

    await _register(client, "n_src_nopersist")
    project_id = await _intake(client, "N-preview-nopersist")
    src_id = await _me_id(client)
    await backfill_streams_from_projects(maker)

    # Run several previews across separate (time-shifted) rate-limit
    # windows by manually clearing the last-seen cache between calls so
    # we exercise the persistence-free path repeatedly.
    personal_service = app.state.personal_service
    for idx in range(3):
        stub.respond_queue.append(
            EdgeResponse(
                kind="answer",
                body=f"preview answer {idx}",
                route_targets=[],
            )
        )
        # Clear the rate-limit cache between calls — this is the test-
        # equivalent of waiting >2s between keystrokes.
        personal_service._preview_last_seen.clear()
        r = await client.post(
            f"/api/personal/{project_id}/preview",
            json={"body": f"draft number {idx} is long enough"},
        )
        assert r.status_code == 200, r.text

    async with session_scope(maker) as session:
        stream = (
            await session.execute(
                select(StreamRow).where(
                    StreamRow.project_id == project_id,
                    StreamRow.type == "personal",
                    StreamRow.owner_user_id == src_id,
                )
            )
        ).scalar_one()
        rows = list(
            (
                await session.execute(
                    select(MessageRow).where(MessageRow.stream_id == stream.id)
                )
            )
            .scalars()
            .all()
        )
    # Zero messages: preview is read-only. If any row leaked, that's the
    # exact regression this test exists to catch.
    assert rows == []


@pytest.mark.asyncio
async def test_preview_requires_auth(api_env):
    client, *_ = api_env
    client.cookies.clear()
    r = await client.post(
        "/api/personal/anything/preview",
        json={"body": "a long enough draft to pass the short-circuit"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_preview_rejects_non_member(api_env):
    client, maker, *_ = api_env
    _install_stub(api_env)

    await _register(client, "n_owner_pv")
    project_id = await _intake(client, "N-preview-authz")
    await _register(client, "n_outsider_pv")
    await _login(client, "n_outsider_pv")

    r = await client.post(
        f"/api/personal/{project_id}/preview",
        json={"body": "a long enough draft to pass the short-circuit"},
    )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_personal_post_rejects_non_member(api_env):
    """A user who is not a member of the project can't post into its
    personal stream.
    """
    client, maker, *_ = api_env
    _install_stub(api_env)

    await _register(client, "n_owner_nm")
    project_id = await _intake(client, "N-auth-1")
    await _register(client, "n_outsider_nm")
    await _login(client, "n_outsider_nm")

    r = await client.post(
        f"/api/personal/{project_id}/post", json={"body": "intruder"}
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Deterministic why-chain fire.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_with_why_prefix_auto_fires_why_chain(api_env):
    """When the user's message starts with 'why', PersonalStreamService
    pre-invokes the why_chain skill BEFORE calling EdgeAgent. Two system
    messages (edge-tool-call + edge-tool-result) are persisted and the
    tool result lands in the response's tool_messages payload so the
    frontend renders the lineage card. This is the Sprint 1a + node-
    detail-page completion step — without it the card-render path is
    LLM-discretion and inconsistent.
    """
    client, maker, *_ = api_env
    stub = _install_stub(api_env)
    # EdgeAgent immediately settles on silence — we just want to observe
    # the pre-seed, not a synthesized answer.
    stub.respond_queue.append(
        EdgeResponse(kind="silence", body=None, route_targets=[])
    )

    await _register(client, "n_why_maya")
    project_id = await _intake(client, "N-why-1")
    await backfill_streams_from_projects(maker)

    r = await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "Why did we choose this registration flow?"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    tool_msgs = body.get("tool_messages") or []
    kinds = [m["kind"] for m in tool_msgs]
    assert "edge-tool-call" in kinds
    assert "edge-tool-result" in kinds
    # Both must reference why_chain — no other skill should auto-fire.
    names = {m["name"] for m in tool_msgs}
    assert names == {"why_chain"}
    # Tool result envelope — SkillsService returns ok=True even on
    # empty match (the chain walk is pure); the `result` list may be
    # empty if no decisions exist yet, which is fine.
    result_msg = next(m for m in tool_msgs if m["kind"] == "edge-tool-result")
    assert result_msg["result"]["ok"] is True
    assert result_msg["result"]["skill"] == "why_chain"
    # EdgeAgent was called AFTER the pre-seed, with the tool result
    # threaded into recent_messages.
    assert len(stub.respond_calls) == 1
    ctx = stub.respond_calls[0]["context"]
    recent = ctx.get("recent_messages") or []
    assert any(
        r.get("kind") == "edge-tool-result" for r in recent
    ), "tool result must be injected into context before EdgeAgent.respond"


@pytest.mark.asyncio
async def test_post_without_why_prefix_does_not_auto_fire(api_env):
    """A normal message does NOT pre-fire why_chain. EdgeAgent is free
    to choose answer/clarify/tool_call on its own terms."""
    client, maker, *_ = api_env
    stub = _install_stub(api_env)
    stub.respond_queue.append(
        EdgeResponse(kind="silence", body=None, route_targets=[])
    )

    await _register(client, "n_no_why")
    project_id = await _intake(client, "N-nowhy-1")
    await backfill_streams_from_projects(maker)

    r = await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "Let's schedule a standup tomorrow."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # No tool_messages — the loop exits on the first silence response.
    assert body.get("tool_messages") == []
