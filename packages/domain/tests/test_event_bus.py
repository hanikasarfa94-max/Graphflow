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


@pytest.mark.asyncio
async def test_subscriber_fires_after_db_write(maker):
    import asyncio

    bus = EventBus(maker)
    bind_trace_id(None)

    received: list[dict] = []

    async def handler(payload: dict) -> None:
        received.append(payload)

    bus.subscribe("decision.applied", handler)

    await bus.emit("decision.applied", {"project_id": "p-3", "decision_id": "d-7"})
    # Handler runs via asyncio.create_task — yield once so it executes.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert received == [{"project_id": "p-3", "decision_id": "d-7"}]

    # DB write still happened — contract unchanged.
    async with session_scope(maker) as session:
        rows = await EventRepository(session).list_by_name("decision.applied")
    assert rows[0].payload["decision_id"] == "d-7"


@pytest.mark.asyncio
async def test_subscriber_failure_is_swallowed_not_propagated(maker):
    import asyncio

    bus = EventBus(maker)
    bind_trace_id(None)

    saw_second = asyncio.Event()

    async def bad(_payload: dict) -> None:
        raise RuntimeError("boom")

    async def good(_payload: dict) -> None:
        saw_second.set()

    bus.subscribe("delivery.generated", bad)
    bus.subscribe("delivery.generated", good)

    # emit should not raise even though `bad` handler blows up.
    await bus.emit("delivery.generated", {"project_id": "p-4"})
    try:
        await asyncio.wait_for(saw_second.wait(), timeout=1.0)
    except asyncio.TimeoutError:
        pytest.fail("good subscriber never ran after bad one raised")


@pytest.mark.asyncio
async def test_subscriber_only_fires_for_matching_event(maker):
    import asyncio

    bus = EventBus(maker)
    bind_trace_id(None)

    received: list[str] = []

    async def handler(payload: dict) -> None:
        received.append(payload.get("name", ""))

    bus.subscribe("decision.applied", handler)

    await bus.emit("intake.received", {"name": "should-not-match"})
    await bus.emit("decision.applied", {"name": "should-match"})
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert received == ["should-match"]
