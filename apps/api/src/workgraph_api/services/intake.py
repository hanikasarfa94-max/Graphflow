from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import RequirementAgent
from workgraph_domain import EventBus, IntakeResult, Project, Requirement
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    AgentRunLogRepository,
    DuplicateIntakeError,
    IntakeRepository,
    ProjectRow,
    RequirementRepository,
    RequirementRow,
    session_scope,
)

from .graph_builder import GraphBuilderService
from .project import ProjectService

_log = logging.getLogger("workgraph.api.intake")


class IntakeService:
    """Single entry point for both API and Feishu intake paths.

    Phase 3 adds inline Requirement parsing: after create, invoke the
    RequirementAgent, persist the parsed JSON + outcome on RequirementRow,
    write agent_run_log (2C2), and emit `requirement.parsed` with trace_id.

    Dedup hits skip re-parsing — the existing row already carries the parse.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        agent: RequirementAgent | None = None,
        graph_builder: GraphBuilderService | None = None,
        project_service: ProjectService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._agent = agent or RequirementAgent()
        self._graph_builder = graph_builder or GraphBuilderService(
            sessionmaker, event_bus
        )
        self._project_service = project_service

    async def receive(
        self,
        *,
        source: str,
        source_event_id: str,
        title: str,
        raw_text: str,
        payload: dict[str, Any],
        creator_user_id: str | None = None,
    ) -> IntakeResult:
        # 1) Create (or hit dedup) atomically.
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
                project_row = (
                    await session.execute(
                        select(ProjectRow).where(ProjectRow.id == dup.existing_project_id)
                    )
                ).scalar_one()
                # Dedup: return the LATEST requirement version for the project,
                # not whichever row happens to come first. Clarification-reply
                # promotes v1 → v2+, so a naive fetch would return stale parse.
                requirement_row = await RequirementRepository(
                    session
                ).latest_for_project(dup.existing_project_id)
                assert requirement_row is not None, (
                    f"dedup hit for project {dup.existing_project_id!r} "
                    "but no RequirementRow exists"
                )
                deduped = True

            project = Project.model_validate(project_row)
            requirement = Requirement.model_validate(requirement_row)
            project_id = project.id
            requirement_id = requirement.id

        # intake.received fires whether or not we dedup, so observers can count attempts.
        await self._event_bus.emit(
            "intake.received",
            {
                "project_id": project_id,
                "requirement_id": requirement_id,
                "source": source,
                "source_event_id": source_event_id,
                "deduplicated": deduped,
            },
        )

        # Bind the authenticated creator so they auto-join the project and
        # can see it in /projects. Idempotent — dedup path is safe.
        if creator_user_id is not None and self._project_service is not None:
            await self._project_service.bind_creator(
                project_id=project_id, user_id=creator_user_id
            )

        # 2) On dedup, don't re-parse — the first intake already wrote parsed_json.
        if deduped:
            return IntakeResult(
                project=project,
                requirement=requirement,
                source=source,
                source_event_id=source_event_id,
                deduplicated=True,
            )

        # 3) Parse. Errors become manual_review (never 500 per 2C4).
        outcome = await self._agent.parse(raw_text)

        # 4) Persist parsed_json + outcome, write agent_run_log, reload requirement.
        async with session_scope(self._sessionmaker) as session:
            req_row = (
                await session.execute(
                    select(RequirementRow).where(RequirementRow.id == requirement_id)
                )
            ).scalar_one()
            req_row.parsed_json = outcome.parsed.model_dump()
            req_row.parse_outcome = outcome.outcome
            req_row.parsed_at = datetime.now(timezone.utc)

            await AgentRunLogRepository(session).append(
                agent="requirement",
                prompt_version=self._agent.prompt_version,
                project_id=project_id,
                trace_id=get_trace_id(),
                outcome=outcome.outcome,
                attempts=outcome.attempts,
                latency_ms=outcome.result.latency_ms,
                prompt_tokens=outcome.result.prompt_tokens,
                completion_tokens=outcome.result.completion_tokens,
                cache_read_tokens=outcome.result.cache_read_tokens,
                error=outcome.error,
            )
            await session.flush()
            refreshed = Requirement.model_validate(req_row)

        # 5) Emit requirement.parsed so downstream (clarification, planning) can subscribe.
        await self._event_bus.emit(
            "requirement.parsed",
            {
                "project_id": project_id,
                "requirement_id": requirement_id,
                "prompt_version": self._agent.prompt_version,
                "outcome": outcome.outcome,
                "attempts": outcome.attempts,
                "confidence": outcome.parsed.confidence,
                "scope_count": len(outcome.parsed.scope_items),
                "deadline": outcome.parsed.deadline,
            },
        )

        # 6) Phase 5 — project parsed requirement onto graph entities.
        # Skipped automatically if outcome == manual_review.
        await self._graph_builder.build_for_requirement(
            project_id=project_id,
            requirement_id=requirement_id,
            requirement_version=refreshed.version,
            parsed=outcome.parsed,
            parse_outcome=outcome.outcome,
            source="intake",
        )

        return IntakeResult(
            project=project,
            requirement=refreshed,
            source=source,
            source_event_id=source_event_id,
            deduplicated=False,
        )
