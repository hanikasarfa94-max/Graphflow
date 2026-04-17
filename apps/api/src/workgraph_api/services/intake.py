from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus, IntakeResult, Project, Requirement
from workgraph_persistence import (
    DuplicateIntakeError,
    IntakeRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.intake")


class IntakeService:
    """Single entry point for both API and Feishu intake paths.

    Per Phase 2 AC: "API path and Feishu path produce the same domain result."
    Both routers construct a normalized tuple (source, source_event_id, title,
    raw_text, payload) and call `receive`. The shape returned is identical.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus

    async def receive(
        self,
        *,
        source: str,
        source_event_id: str,
        title: str,
        raw_text: str,
        payload: dict[str, Any],
    ) -> IntakeResult:
        async with session_scope(self._sessionmaker) as session:
            repo = IntakeRepository(session)
            try:
                project_row, requirement_row, _ = await repo.create(
                    source=source,
                    source_event_id=source_event_id,
                    title=title,
                    raw_text=raw_text,
                    payload=payload,
                )
                deduped = False
            except DuplicateIntakeError as dup:
                _log.info(
                    "intake dedup hit",
                    extra={
                        "source": source,
                        "source_event_id": source_event_id,
                        "project_id": dup.existing_project_id,
                    },
                )
                # Reload existing project + requirement for identical return shape.
                from sqlalchemy import select

                from workgraph_persistence import ProjectRow, RequirementRow

                project_row = (
                    await session.execute(
                        select(ProjectRow).where(ProjectRow.id == dup.existing_project_id)
                    )
                ).scalar_one()
                requirement_row = (
                    await session.execute(
                        select(RequirementRow).where(
                            RequirementRow.project_id == dup.existing_project_id
                        )
                    )
                ).scalar_one()
                deduped = True

            project = Project.model_validate(project_row)
            requirement = Requirement.model_validate(requirement_row)

        # Emit AFTER commit. Dedup still emits so observers see every attempt.
        await self._event_bus.emit(
            "intake.received",
            {
                "project_id": project.id,
                "requirement_id": requirement.id,
                "source": source,
                "source_event_id": source_event_id,
                "deduplicated": deduped,
            },
        )

        return IntakeResult(
            project=project,
            requirement=requirement,
            source=source,
            source_event_id=source_event_id,
            deduplicated=deduped,
        )
