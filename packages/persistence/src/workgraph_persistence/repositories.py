from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .orm import EventRow, IntakeEventRow, ProjectRow, RequirementRow


class DuplicateIntakeError(Exception):
    """Raised when (source, source_event_id) already exists."""

    def __init__(self, source: str, source_event_id: str, existing_project_id: str) -> None:
        super().__init__(
            f"intake already recorded: source={source} source_event_id={source_event_id}"
        )
        self.source = source
        self.source_event_id = source_event_id
        self.existing_project_id = existing_project_id


def _new_id() -> str:
    return str(uuid4())


class IntakeRepository:
    """Creates project+requirement+intake_event atomically, deduped by source key."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_existing(
        self, source: str, source_event_id: str
    ) -> IntakeEventRow | None:
        stmt = select(IntakeEventRow).where(
            IntakeEventRow.source == source,
            IntakeEventRow.source_event_id == source_event_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        source: str,
        source_event_id: str,
        title: str,
        raw_text: str,
        payload: dict,
    ) -> tuple[ProjectRow, RequirementRow, IntakeEventRow]:
        existing = await self.find_existing(source, source_event_id)
        if existing is not None:
            raise DuplicateIntakeError(source, source_event_id, existing.project_id)

        project = ProjectRow(id=_new_id(), title=title)
        requirement = RequirementRow(
            id=_new_id(), project_id=project.id, raw_text=raw_text
        )
        intake = IntakeEventRow(
            id=_new_id(),
            source=source,
            source_event_id=source_event_id,
            project_id=project.id,
            payload=payload,
        )
        self._session.add_all([project, requirement, intake])
        try:
            await self._session.flush()
        except IntegrityError as e:
            await self._session.rollback()
            # Race: another request wrote the same source_event_id between find + flush.
            fresh = await self.find_existing(source, source_event_id)
            if fresh is not None:
                raise DuplicateIntakeError(source, source_event_id, fresh.project_id) from e
            raise
        return project, requirement, intake


class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self, *, name: str, trace_id: str | None, payload: dict
    ) -> EventRow:
        row = EventRow(id=_new_id(), name=name, trace_id=trace_id, payload=payload)
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_by_name(self, name: str) -> list[EventRow]:
        stmt = select(EventRow).where(EventRow.name == name).order_by(EventRow.created_at)
        return list((await self._session.execute(stmt)).scalars().all())
