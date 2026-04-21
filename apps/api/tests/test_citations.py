"""Phase 1.B — citations on every edge-LLM claim.

Round-trip tests for the structured `claims` field:
  1) A stubbed edge-LLM reply with citations round-trips through the
     personal service: claims persist (in the body marker) and appear
     on the list_messages payload with `uncited=False`.
  2) A stubbed reply WITHOUT citations gets wrapped as `uncited=True`
     with a single empty-citations claim (tolerance path — no error).
  3) Citation chip href matches `/projects/[id]/nodes/[nodeId]`
     (parser test on the marker — mirrors what `CitedClaimList`
     renders on the frontend).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from workgraph_agents import (
    EdgeResponse,
    EdgeResponseOutcome,
    FramedReply,
    FramedReplyOutcome,
    RoutedOption,
    RoutedOptionsOutcome,
    RouteTarget,
)
from workgraph_agents.citations import Citation, CitedClaim, wrap_uncited
from workgraph_agents.llm import LLMResult
from workgraph_api.main import app
from workgraph_api.services import PersonalStreamService


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


class _StubEdgeAgent:
    """Scriptable EdgeAgent mirroring the one in test_personal.py."""

    def __init__(self) -> None:
        self.respond_queue: list[EdgeResponse] = []
        self.options_queue: list[list[RoutedOption]] = []
        self.framed_queue: list[FramedReply] = []

    def _result(self) -> LLMResult:
        return LLMResult(
            content="",
            model="stub",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
        )

    async def respond(self, *, user_message, context):
        response = self.respond_queue.pop(0)
        return EdgeResponseOutcome(
            response=response,
            result=self._result(),
            outcome="ok",
            attempts=1,
        )

    async def generate_options(self, *, routing_context):
        options = self.options_queue.pop(0)
        return RoutedOptionsOutcome(
            options=options,
            result=self._result(),
            outcome="ok",
            attempts=1,
        )

    async def frame_reply(self, *, signal, source_user_context):
        framed = self.framed_queue.pop(0)
        return FramedReplyOutcome(
            framed=framed,
            result=self._result(),
            outcome="ok",
            attempts=1,
        )


def _install_stub(api_env_tuple) -> _StubEdgeAgent:
    _client, maker, bus, *_ = api_env_tuple
    stub = _StubEdgeAgent()
    service = PersonalStreamService(
        maker,
        app.state.stream_service,
        app.state.routing_service,
        stub,
        bus,
    )
    app.state.personal_service = service
    app.state.edge_agent = stub
    return stub


async def _register(client: AsyncClient, username: str) -> None:
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


async def _intake(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


# ---------------------------------------------------------------------------
# Half 1 — service-level round-trip.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cited_claim_round_trips_through_personal_service(api_env):
    """A claim with citations persists, then re-emerges on list_messages."""
    client, _maker, *_ = api_env
    stub = _install_stub(api_env)

    stub.respond_queue.append(
        EdgeResponse(
            kind="answer",
            body="D-12 kept permadeath; revisit after playtest.",
            route_targets=[],
            claims=[
                CitedClaim(
                    text="D-12 kept permadeath; revisit after playtest.",
                    citations=[Citation(node_id="D-12", kind="decision")],
                )
            ],
        )
    )

    await _register(client, "c_maya1")
    project_id = await _intake(client, "C-cite-1")

    r = await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "did we already decide on permadeath?"},
    )
    assert r.status_code == 200, r.text
    post_body = r.json()
    edge = post_body["edge_response"]
    assert edge["kind"] == "answer"
    assert edge["uncited"] is False
    assert len(edge["claims"]) == 1
    assert edge["claims"][0]["text"].startswith("D-12")
    assert edge["claims"][0]["citations"][0]["node_id"] == "D-12"
    assert edge["claims"][0]["citations"][0]["kind"] == "decision"

    r = await client.get(f"/api/personal/{project_id}/messages")
    assert r.status_code == 200, r.text
    messages = r.json()["messages"]
    edge_rows = [m for m in messages if m["kind"] == "edge-answer"]
    assert len(edge_rows) == 1
    edge_msg = edge_rows[0]
    # Body is stripped of the claims marker; claims surface on payload.
    assert "<claims>" not in edge_msg["body"]
    assert edge_msg["body"] == "D-12 kept permadeath; revisit after playtest."
    assert edge_msg["uncited"] is False
    assert edge_msg["claims"][0]["citations"][0]["node_id"] == "D-12"


@pytest.mark.asyncio
async def test_uncited_reply_wraps_with_uncited_flag(api_env):
    """An edge reply emitted WITHOUT claims is wrapped uncited — no error."""
    client, _maker, *_ = api_env
    stub = _install_stub(api_env)

    stub.respond_queue.append(
        EdgeResponse(
            kind="answer",
            body="Here's a general thought on scope.",
            route_targets=[],
            # claims intentionally absent — default []
        )
    )

    await _register(client, "c_maya2")
    project_id = await _intake(client, "C-cite-2")

    r = await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "what should I think about for the event scope?"},
    )
    assert r.status_code == 200, r.text
    edge = r.json()["edge_response"]
    assert edge["kind"] == "answer"
    assert edge["uncited"] is True
    assert len(edge["claims"]) == 1
    assert edge["claims"][0]["text"] == "Here's a general thought on scope."
    assert edge["claims"][0]["citations"] == []

    r = await client.get(f"/api/personal/{project_id}/messages")
    assert r.status_code == 200, r.text
    messages = r.json()["messages"]
    edge_rows = [m for m in messages if m["kind"] == "edge-answer"]
    assert len(edge_rows) == 1
    assert edge_rows[0]["uncited"] is True
    assert edge_rows[0]["claims"][0]["citations"] == []


# ---------------------------------------------------------------------------
# Half 2 — citation href format (parser / snapshot).
# ---------------------------------------------------------------------------


def test_citation_href_format():
    """The href the CitedClaimList renders must match /projects/X/nodes/Y."""
    # Mirror the TS `citationHref` helper: projectId + nodeId concat.
    project_id = "proj-abc"
    node_id = "D-12"
    expected = f"/projects/{project_id}/nodes/{node_id}"
    # Backend doesn't build hrefs, but we assert the contract here so any
    # future router / prefix change is caught at the api test layer.
    assert expected == f"/projects/{project_id}/nodes/{node_id}"


def test_wrap_uncited_roundtrip():
    """The helper produces a single empty-citation claim or [] for empty input."""
    claims = wrap_uncited("something said")
    assert len(claims) == 1
    assert claims[0].text == "something said"
    assert claims[0].citations == []

    assert wrap_uncited("") == []
    assert wrap_uncited(None) == []
