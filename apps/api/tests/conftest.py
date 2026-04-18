from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from workgraph_agents.testing import (
    StubClarificationAgent,
    StubConflictExplanationAgent,
    StubDeliveryAgent,
    StubIMAssistAgent,
    StubPlanningAgent,
    StubRequirementAgent,
)
from workgraph_domain import EventBus
from workgraph_persistence import (
    build_engine,
    build_sessionmaker,
    create_all,
    drop_all,
)

from workgraph_api.main import app
from workgraph_api.services import (
    AssignmentService,
    AuthService,
    ClarificationService,
    CollabHub,
    CommentService,
    ConflictService,
    DecisionService,
    DeliveryService,
    IMService,
    IntakeService,
    MessageService,
    NotificationService,
    PlanningService,
    ProjectService,
)


@pytest_asyncio.fixture
async def api_env():
    """Fresh in-memory DB + fully wired app.state for integration tests.

    Every Phase 7'/7'' service is instantiated against stubs so tests neither
    hit DeepSeek nor a real Redis. Tuple shape stays 6-long so pre-existing
    tests that unpack `(client, maker, bus, req_agent, clar_agent, plan_agent)`
    keep working; new collab services reach tests via `app.state`.
    """
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    maker = build_sessionmaker(engine)
    bus = EventBus(maker)

    req_agent = StubRequirementAgent()
    clar_agent = StubClarificationAgent()
    plan_agent = StubPlanningAgent()
    im_agent = StubIMAssistAgent()
    conflict_agent = StubConflictExplanationAgent()
    delivery_agent = StubDeliveryAgent()

    collab_hub = CollabHub(redis_url=None)
    await collab_hub.start()

    auth_service = AuthService(maker, bus)
    project_service = ProjectService(maker, bus)
    notification_service = NotificationService(maker, bus, collab_hub)
    assignment_service = AssignmentService(
        maker, bus, collab_hub, notification_service
    )
    comment_service = CommentService(
        maker, bus, collab_hub, notification_service
    )
    message_service = MessageService(
        maker, bus, collab_hub, notification_service
    )
    im_service = IMService(
        maker,
        bus,
        collab_hub,
        notification_service,
        message_service,
        im_agent,
    )
    conflict_service = ConflictService(maker, bus, collab_hub, conflict_agent)
    decision_service = DecisionService(
        maker, bus, collab_hub, conflict_service, assignment_service
    )
    delivery_service = DeliveryService(
        maker, bus, collab_hub, delivery_agent
    )

    intake_service = IntakeService(
        maker, bus, agent=req_agent, project_service=project_service
    )
    clar_service = ClarificationService(
        maker,
        bus,
        clarification_agent=clar_agent,
        requirement_agent=req_agent,
    )
    planning_service = PlanningService(maker, bus, agent=plan_agent)

    app.state.engine = engine
    app.state.sessionmaker = maker
    app.state.event_bus = bus
    app.state.intake_service = intake_service
    app.state.clarification_service = clar_service
    app.state.planning_service = planning_service
    app.state.requirement_agent = req_agent
    app.state.clarification_agent = clar_agent
    app.state.planning_agent = plan_agent
    app.state.im_agent = im_agent
    app.state.conflict_agent = conflict_agent
    app.state.auth_service = auth_service
    app.state.project_service = project_service
    app.state.collab_hub = collab_hub
    app.state.notification_service = notification_service
    app.state.assignment_service = assignment_service
    app.state.comment_service = comment_service
    app.state.message_service = message_service
    app.state.im_service = im_service
    app.state.conflict_service = conflict_service
    app.state.decision_service = decision_service
    app.state.delivery_service = delivery_service
    app.state.delivery_agent = delivery_agent

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, maker, bus, req_agent, clar_agent, plan_agent
    try:
        await im_service.drain()
    except Exception:
        pass
    try:
        await conflict_service.drain()
    except Exception:
        pass
    await collab_hub.stop()
    await drop_all(engine)
    await engine.dispose()
