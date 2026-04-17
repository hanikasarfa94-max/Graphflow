from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from workgraph_agents.testing import StubRequirementAgent
from workgraph_domain import EventBus
from workgraph_persistence import (
    build_engine,
    build_sessionmaker,
    create_all,
    drop_all,
)

from workgraph_api.main import app
from workgraph_api.services import IntakeService


@pytest_asyncio.fixture
async def api_env():
    """Fresh in-memory DB + wired app.state for intake tests.

    Bypasses the real lifespan handler by instantiating state directly, so
    tests never touch the on-disk dev sqlite file. Injects StubRequirementAgent
    so the intake path never calls DeepSeek during unit tests.
    """
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    maker = build_sessionmaker(engine)
    bus = EventBus(maker)
    agent = StubRequirementAgent()
    service = IntakeService(maker, bus, agent=agent)

    app.state.engine = engine
    app.state.sessionmaker = maker
    app.state.event_bus = bus
    app.state.intake_service = service
    app.state.requirement_agent = agent

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, maker, bus, agent
    await drop_all(engine)
    await engine.dispose()
