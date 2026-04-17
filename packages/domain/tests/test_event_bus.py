from __future__ import annotations

import pytest
import pytest_asyncio

from workgraph_domain import EventBus
from workgraph_observability import bind_trace_id, new_trace_id
from workgraph_persistence import (
    EventRepository,
    build_engine,
    build_sessionmaker,
    create_all,
    drop_all,
    session_scope,
)


@pytest_asyncio.fixture
async def maker():
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    m = build_sessionmaker(engine)
    try:
        yield m
    finally:
        await drop_all(engine)
        await engine.dispose()


@pytest.mark.asyncio
async def test_event_bus_attaches_trace_id(maker):
    bus = EventBus(maker)
    tid = new_trace_id()
    bind_trace_id(tid)

    await bus.emit("intake.received", {"project_id": "p-1", "source": "api"})

    async with session_scope(maker) as session:
        rows = await EventRepository(session).list_by_name("intake.received")
    assert len(rows) == 1
    assert rows[0].trace_id == tid
    assert rows[0].payload["project_id"] == "p-1"


@pytest.mark.asyncio
async def test_event_bus_emits_without_trace_id(maker):
    bus = EventBus(maker)
    bind_trace_id(None)

    await bus.emit("intake.received", {"project_id": "p-2"})

    async with session_scope(maker) as session:
        rows = await EventRepository(session).list_by_name("intake.received")
    assert rows[0].trace_id is None
