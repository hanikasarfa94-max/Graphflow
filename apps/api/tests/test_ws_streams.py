"""Phase O — WebSocket tests for the per-stream channel.

Mirrors `test_ws.py` (starlette TestClient for sync WS) but targets
`/ws/streams/{stream_id}`. Verifies:

  * unauthenticated connect is rejected
  * non-member of the stream is rejected
  * authed member receives a hello + broadcast of a POST-ed message
  * ping/pong round-trips
  * subscriber count decrements on disconnect

Uses the same in-process CollabHub; the parallel stream namespace means
project-channel broadcasts do NOT leak into stream subscribers.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from workgraph_agents import EdgeResponse, EdgeResponseOutcome
from workgraph_agents.llm import LLMResult
from workgraph_agents.testing import (
    StubClarificationAgent,
    StubIMAssistAgent,
    StubPlanningAgent,
    StubRequirementAgent,
)
from workgraph_domain import EventBus
from workgraph_persistence import (
    build_engine,
    build_sessionmaker,
    create_all,
)

from workgraph_api.main import app
from workgraph_api.services import (
    AssignmentService,
    AuthService,
    ClarificationService,
    CollabHub,
    CommentService,
    IMService,
    IntakeService,
    MessageService,
    NotificationService,
    PersonalStreamService,
    PlanningService,
    ProjectService,
    RoutingService,
    StreamService,
)


class _SilenceEdgeAgent:
    async def respond(self, *, user_message, context):
        return EdgeResponseOutcome(
            response=EdgeResponse(kind="silence", body=None, route_targets=[]),
            result=LLMResult(
                content="",
                model="stub",
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
            ),
            outcome="ok",
            attempts=1,
        )

    async def generate_options(self, *, routing_context):  # pragma: no cover
        raise NotImplementedError

    async def frame_reply(self, *, signal, source_user_context):  # pragma: no cover
        raise NotImplementedError


def _wire_stubs(client: TestClient) -> dict:
    """Install in-memory DB + stub agents, same shape as test_ws.py's
    helper but with StreamService/RoutingService/PersonalStreamService
    wired so stream endpoints work.
    """
    import asyncio

    loop = asyncio.new_event_loop()

    engine = build_engine("sqlite+aiosqlite:///:memory:")
    loop.run_until_complete(create_all(engine))
    maker = build_sessionmaker(engine)
    bus = EventBus(maker)

    req_agent = StubRequirementAgent()
    clar_agent = StubClarificationAgent()
    plan_agent = StubPlanningAgent()
    im_agent = StubIMAssistAgent()

    hub = CollabHub(redis_url=None)
    loop.run_until_complete(hub.start())

    auth_service = AuthService(maker, bus)
    project_service = ProjectService(maker, bus)
    notification_service = NotificationService(maker, bus, hub)
    assignment_service = AssignmentService(maker, bus, hub, notification_service)
    comment_service = CommentService(maker, bus, hub, notification_service)
    message_service = MessageService(maker, bus, hub, notification_service)
    im_service = IMService(
        maker, bus, hub, notification_service, message_service, im_agent
    )
    stream_service = StreamService(maker, bus, hub)
    routing_service = RoutingService(maker, bus, stream_service)
    personal_service = PersonalStreamService(
        maker, stream_service, routing_service, _SilenceEdgeAgent(), bus
    )

    app.state.engine = engine
    app.state.sessionmaker = maker
    app.state.event_bus = bus
    app.state.intake_service = IntakeService(
        maker, bus, agent=req_agent, project_service=project_service
    )
    app.state.clarification_service = ClarificationService(
        maker, bus, clarification_agent=clar_agent, requirement_agent=req_agent
    )
    app.state.planning_service = PlanningService(maker, bus, agent=plan_agent)
    app.state.auth_service = auth_service
    app.state.project_service = project_service
    app.state.collab_hub = hub
    app.state.notification_service = notification_service
    app.state.assignment_service = assignment_service
    app.state.comment_service = comment_service
    app.state.message_service = message_service
    app.state.im_service = im_service
    app.state.stream_service = stream_service
    app.state.routing_service = routing_service
    app.state.personal_service = personal_service
    app.state.edge_agent = _SilenceEdgeAgent()
    return {"hub": hub, "stream_service": stream_service}


def _register(client: TestClient, username: str) -> None:
    r = client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


def _login(client: TestClient, username: str) -> None:
    client.cookies.clear()
    r = client.post(
        "/api/auth/login",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


def _create_dm(client: TestClient, other_user_id: str) -> str:
    r = client.post(
        "/api/streams/dm", json={"other_user_id": other_user_id}
    )
    assert r.status_code == 200, r.text
    return r.json()["stream"]["id"]


def _me_id(client: TestClient) -> str:
    r = client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_stream_ws_rejects_unauthenticated():
    with TestClient(app) as client:
        _wire_stubs(client)
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/streams/some-id"):
                pass


def test_stream_ws_rejects_non_member():
    with TestClient(app) as client:
        _wire_stubs(client)
        _register(client, "stream-ws-a")
        a_id = _me_id(client)
        _register(client, "stream-ws-b")
        b_id = _me_id(client)
        _login(client, "stream-ws-a")
        stream_id = _create_dm(client, b_id)
        # Log in as a third user who isn't a stream member.
        _register(client, "stream-ws-outsider")
        with pytest.raises(Exception):
            with client.websocket_connect(f"/ws/streams/{stream_id}"):
                pass


def test_stream_ws_hello_and_message_broadcast():
    with TestClient(app) as client:
        _wire_stubs(client)
        _register(client, "stream-ws-maya")
        maya_id = _me_id(client)
        _register(client, "stream-ws-raj")
        raj_id = _me_id(client)
        _login(client, "stream-ws-maya")
        stream_id = _create_dm(client, raj_id)

        with client.websocket_connect(f"/ws/streams/{stream_id}") as ws:
            hello = json.loads(ws.receive_text())
            assert hello["type"] == "hello"
            assert hello["payload"]["stream_id"] == stream_id
            assert hello["payload"]["user_id"] == maya_id

            # Maya POSTs a message into the DM — the WS should see it.
            r = client.post(
                f"/api/streams/{stream_id}/messages",
                json={"body": "hello from the http side"},
            )
            assert r.status_code == 200, r.text
            seen = False
            for _ in range(5):
                frame = json.loads(ws.receive_text())
                if frame["type"] == "message":
                    assert frame["payload"]["body"] == "hello from the http side"
                    assert frame["payload"]["stream_id"] == stream_id
                    seen = True
                    break
            assert seen, "expected a 'message' frame after POST"


def test_stream_ws_ping_pong():
    with TestClient(app) as client:
        _wire_stubs(client)
        _register(client, "stream-ws-ping-a")
        a_id = _me_id(client)
        _register(client, "stream-ws-ping-b")
        b_id = _me_id(client)
        _login(client, "stream-ws-ping-a")
        stream_id = _create_dm(client, b_id)

        with client.websocket_connect(f"/ws/streams/{stream_id}") as ws:
            assert json.loads(ws.receive_text())["type"] == "hello"
            ws.send_text(json.dumps({"type": "ping"}))
            frame = json.loads(ws.receive_text())
            assert frame["type"] == "pong"


def test_stream_ws_subscriber_count_decrements_on_close():
    with TestClient(app) as client:
        env = _wire_stubs(client)
        hub: CollabHub = env["hub"]
        _register(client, "stream-ws-count-a")
        _register(client, "stream-ws-count-b")
        b_id = _me_id(client)
        _login(client, "stream-ws-count-a")
        stream_id = _create_dm(client, b_id)

        assert hub.stream_subscriber_count(stream_id) == 0
        with client.websocket_connect(f"/ws/streams/{stream_id}") as ws:
            assert json.loads(ws.receive_text())["type"] == "hello"
            assert hub.stream_subscriber_count(stream_id) == 1
        assert hub.stream_subscriber_count(stream_id) == 0
