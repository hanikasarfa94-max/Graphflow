"""Phase 7'' WebSocket tests.

Uses Starlette's synchronous TestClient because httpx doesn't drive ASGI
websockets. The `TestClient` context manager re-runs the app lifespan, so
we have to override services INSIDE the context, not before.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

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
    PlanningService,
    ProjectService,
)


def _wire_stubs(client: TestClient) -> dict:
    """Replace the lifespan-wired services with in-memory + stub variants.

    Needs to run AFTER the TestClient context entered; otherwise the real
    lifespan would just instantiate fresh real services on top of us.
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
    return {
        "hub": hub,
        "message_service": message_service,
        "im_service": im_service,
    }


def _register(client: TestClient, username: str) -> None:
    r = client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


def _intake(client: TestClient, event_id: str) -> str:
    r = client.post(
        "/api/intake/message",
        json={"text": "Build a test project quickly.", "source_event_id": event_id},
    )
    assert r.status_code == 200
    return r.json()["project"]["id"]


def test_ws_rejects_unauthenticated():
    with TestClient(app) as client:
        _wire_stubs(client)
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/projects/some-id"):
                pass


def test_ws_rejects_non_member():
    with TestClient(app) as owner_client:
        _wire_stubs(owner_client)
        _register(owner_client, "owner-ws")
        project_id = _intake(owner_client, "ws-1")
        # Same client, different user: log out, register outsider.
        owner_client.cookies.clear()
        _register(owner_client, "outsider-ws")
        with pytest.raises(Exception):
            with owner_client.websocket_connect(f"/ws/projects/{project_id}"):
                pass


def test_ws_hello_frame_and_message_fanout():
    with TestClient(app) as client:
        _wire_stubs(client)
        _register(client, "member-ws")
        project_id = _intake(client, "ws-2")
        with client.websocket_connect(f"/ws/projects/{project_id}") as ws:
            hello = json.loads(ws.receive_text())
            assert hello["type"] == "hello"
            assert hello["payload"]["project_id"] == project_id

            r = client.post(
                f"/api/projects/{project_id}/messages",
                json={"body": "hello from http"},
            )
            assert r.status_code == 200
            seen_message = False
            for _ in range(5):
                frame = json.loads(ws.receive_text())
                if frame["type"] == "message":
                    assert frame["payload"]["body"] == "hello from http"
                    seen_message = True
                    break
            assert seen_message, "expected a 'message' frame after POST"


def test_ws_ping_pong_round_trip():
    with TestClient(app) as client:
        _wire_stubs(client)
        _register(client, "pinger")
        project_id = _intake(client, "ws-3")
        with client.websocket_connect(f"/ws/projects/{project_id}") as ws:
            assert json.loads(ws.receive_text())["type"] == "hello"
            ws.send_text(json.dumps({"type": "ping"}))
            frame = json.loads(ws.receive_text())
            assert frame["type"] == "pong"


def test_ws_active_counter_reflects_subscribers():
    with TestClient(app) as client:
        env = _wire_stubs(client)
        hub: CollabHub = env["hub"]
        _register(client, "counter-ws")
        project_id = _intake(client, "ws-4")
        assert hub.subscriber_count(project_id) == 0
        with client.websocket_connect(f"/ws/projects/{project_id}") as ws:
            assert json.loads(ws.receive_text())["type"] == "hello"
            assert hub.subscriber_count(project_id) == 1
        # After the WS closes, the handler's finally runs and unsubscribes.
        # TestClient returns synchronously only after the handler exits.
        assert hub.subscriber_count(project_id) == 0
