from __future__ import annotations

import pytest
import pytest_asyncio

from workgraph_persistence import (
    DuplicateIntakeError,
    EventRepository,
    IntakeRepository,
    build_engine,
    build_sessionmaker,
    create_all,
    drop_all,
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
async def test_create_project_and_requirement(maker):
    async with maker() as session:
        repo = IntakeRepository(session)
        project, requirement, intake = await repo.create(
            source="api",
            source_event_id="evt-1",
            title="Event registration",
            raw_text="We need to launch an event registration page.",
            payload={"raw": "minimal"},
        )
        await session.commit()

        assert project.id
        assert requirement.project_id == project.id
        assert intake.project_id == project.id
        assert intake.source == "api"


@pytest.mark.asyncio
async def test_duplicate_source_event_raises(maker):
    async with maker() as session:
        repo = IntakeRepository(session)
        await repo.create(
            source="feishu",
            source_event_id="evt-42",
            title="Thing",
            raw_text="x",
            payload={},
        )
        await session.commit()

    async with maker() as session:
        repo = IntakeRepository(session)
        with pytest.raises(DuplicateIntakeError) as exc:
            await repo.create(
                source="feishu",
                source_event_id="evt-42",
                title="Thing 2",
                raw_text="y",
                payload={},
            )
        assert exc.value.source == "feishu"
        assert exc.value.source_event_id == "evt-42"
        assert exc.value.existing_project_id


@pytest.mark.asyncio
async def test_different_sources_not_conflated(maker):
    async with maker() as session:
        repo = IntakeRepository(session)
        await repo.create(
            source="api",
            source_event_id="evt-shared-id",
            title="from api",
            raw_text="x",
            payload={},
        )
        # same id, different source: fine
        await repo.create(
            source="feishu",
            source_event_id="evt-shared-id",
            title="from feishu",
            raw_text="y",
            payload={},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_event_repository_roundtrip(maker):
    async with maker() as session:
        repo = EventRepository(session)
        await repo.append(
            name="intake.received",
            trace_id="tr-123",
            payload={"project_id": "p-1"},
        )
        await session.commit()

    async with maker() as session:
        repo = EventRepository(session)
        rows = await repo.list_by_name("intake.received")
        assert len(rows) == 1
        assert rows[0].trace_id == "tr-123"
        assert rows[0].payload == {"project_id": "p-1"}
