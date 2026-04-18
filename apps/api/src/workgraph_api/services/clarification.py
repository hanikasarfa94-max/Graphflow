from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import ClarificationAgent, ParsedRequirement, RequirementAgent
from workgraph_domain import ClarificationQuestion, EventBus, Requirement
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    AgentRunLogRepository,
    ClarificationQuestionRepository,
    ProjectRow,
    RequirementRepository,
    RequirementRow,
    session_scope,
)

from .graph_builder import GraphBuilderService

_log = logging.getLogger("workgraph.api.clarification")


class ProjectNotFound(Exception):
    def __init__(self, project_id: str) -> None:
        super().__init__(f"project not found: {project_id}")
        self.project_id = project_id


class ClarificationQuestionNotFound(Exception):
    def __init__(self, question_id: str) -> None:
        super().__init__(f"clarification question not found: {question_id}")
        self.question_id = question_id


class ClarificationService:
    """Phase 4 — generate/answer clarification loop on top of versioned Requirements.

    Lifecycle:
      1) /clarify (POST)       → generate batch, persist questions on latest req.
      2) /clarify-reply (POST) → record an answer; when all answers present,
                                 synthesize a v+1 Requirement from raw_text +
                                 Q/A pairs, re-parse it, persist parsed_json.

    Stage transitions are NOT written to a Project column — we derive stage
    from the graph (decision 1E). See workgraph_persistence.stage.project_stage.
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        clarification_agent: ClarificationAgent | None = None,
        requirement_agent: RequirementAgent | None = None,
        graph_builder: GraphBuilderService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._clarification_agent = clarification_agent or ClarificationAgent()
        self._requirement_agent = requirement_agent or RequirementAgent()
        self._graph_builder = graph_builder or GraphBuilderService(
            sessionmaker, event_bus
        )

    async def generate(self, project_id: str) -> dict[str, Any]:
        """Generate questions for the latest requirement on this project.

        Idempotent: if questions already exist for the current requirement
        version, return them as-is. Callers may want to re-run the clarifier;
        they should bump the requirement version first.
        """
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(select(ProjectRow).where(ProjectRow.id == project_id))
            ).scalar_one_or_none()
            if project is None:
                raise ProjectNotFound(project_id)

            latest_req = await RequirementRepository(session).latest_for_project(project_id)
            assert latest_req is not None, "project without requirement"
            parsed = _parsed_or_fallback(latest_req)
            raw_text = latest_req.raw_text
            requirement_id = latest_req.id
            requirement_version = latest_req.version

            existing = await ClarificationQuestionRepository(session).list_for_requirement(
                requirement_id
            )
            if existing:
                return {
                    "project_id": project_id,
                    "requirement_id": requirement_id,
                    "requirement_version": requirement_version,
                    "regenerated": False,
                    "questions": [
                        ClarificationQuestion.model_validate(q).model_dump(mode="json")
                        for q in existing
                    ],
                    "outcome": "ok",
                }

        outcome = await self._clarification_agent.generate(
            raw_text=raw_text, parsed=parsed
        )

        # Persist questions (empty list is valid — no questions needed).
        async with session_scope(self._sessionmaker) as session:
            repo = ClarificationQuestionRepository(session)
            rows = await repo.append_batch(
                requirement_id=requirement_id,
                questions=[q.question for q in outcome.batch.questions],
            )

            await AgentRunLogRepository(session).append(
                agent="clarification",
                prompt_version=self._clarification_agent.prompt_version,
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

            persisted = [
                ClarificationQuestion.model_validate(r).model_dump(mode="json")
                for r in rows
            ]

        await self._event_bus.emit(
            "clarification.generated",
            {
                "project_id": project_id,
                "requirement_id": requirement_id,
                "requirement_version": requirement_version,
                "prompt_version": self._clarification_agent.prompt_version,
                "outcome": outcome.outcome,
                "attempts": outcome.attempts,
                "question_count": len(rows),
            },
        )

        return {
            "project_id": project_id,
            "requirement_id": requirement_id,
            "requirement_version": requirement_version,
            "regenerated": True,
            "questions": persisted,
            "outcome": outcome.outcome,
        }

    async def answer(
        self, *, project_id: str, question_id: str, answer: str
    ) -> dict[str, Any]:
        """Record one answer. If all questions answered, promote to v+1."""
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(select(ProjectRow).where(ProjectRow.id == project_id))
            ).scalar_one_or_none()
            if project is None:
                raise ProjectNotFound(project_id)

            latest_req = await RequirementRepository(session).latest_for_project(project_id)
            assert latest_req is not None

            q_repo = ClarificationQuestionRepository(session)
            question = await q_repo.get(question_id)
            if question is None or question.requirement_id != latest_req.id:
                # Either nonexistent or belongs to a prior requirement version.
                raise ClarificationQuestionNotFound(question_id)

            await q_repo.record_answer(question_id=question_id, answer=answer)
            remaining = await q_repo.unanswered_count(latest_req.id)
            # Snapshot the Q/A history NOW so we can compose v+1 outside the session.
            answered_rows = await q_repo.list_for_requirement(latest_req.id)
            answered_snapshot = [
                {"question": r.question, "answer": r.answer} for r in answered_rows
            ]
            raw_text_v_current = latest_req.raw_text
            current_version = latest_req.version
            current_req_id = latest_req.id

        await self._event_bus.emit(
            "clarification.answered",
            {
                "project_id": project_id,
                "requirement_id": current_req_id,
                "requirement_version": current_version,
                "question_id": question_id,
                "remaining": remaining,
            },
        )

        if remaining > 0:
            return {
                "project_id": project_id,
                "requirement_id": current_req_id,
                "requirement_version": current_version,
                "remaining": remaining,
                "promoted": False,
            }

        # All answers present — promote to v+1.
        merged_raw = _merge_raw_with_answers(raw_text_v_current, answered_snapshot)
        outcome = await self._requirement_agent.parse(merged_raw)

        async with session_scope(self._sessionmaker) as session:
            new_row = await RequirementRepository(session).append_version(
                project_id=project_id,
                raw_text=merged_raw,
                parsed_json=outcome.parsed.model_dump(),
                parse_outcome=outcome.outcome,
                parsed_at=datetime.now(timezone.utc),
            )
            await AgentRunLogRepository(session).append(
                agent="requirement",
                prompt_version=self._requirement_agent.prompt_version,
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
            promoted_id = new_row.id
            promoted_version = new_row.version
            promoted_requirement = Requirement.model_validate(new_row).model_dump(mode="json")

        await self._event_bus.emit(
            "requirement.parsed",
            {
                "project_id": project_id,
                "requirement_id": promoted_id,
                "prompt_version": self._requirement_agent.prompt_version,
                "outcome": outcome.outcome,
                "attempts": outcome.attempts,
                "confidence": outcome.parsed.confidence,
                "scope_count": len(outcome.parsed.scope_items),
                "deadline": outcome.parsed.deadline,
                "requirement_version": promoted_version,
                "source": "clarification-reply",
            },
        )

        # Phase 5 — rebuild graph against v+1 so stage/planning see fresh scope.
        await self._graph_builder.build_for_requirement(
            project_id=project_id,
            requirement_id=promoted_id,
            requirement_version=promoted_version,
            parsed=outcome.parsed,
            parse_outcome=outcome.outcome,
            source="clarification-reply",
        )

        return {
            "project_id": project_id,
            "requirement_id": promoted_id,
            "requirement_version": promoted_version,
            "remaining": 0,
            "promoted": True,
            "requirement": promoted_requirement,
        }


def _parsed_or_fallback(row: RequirementRow) -> ParsedRequirement:
    """Read the parsed_json from a row; fall back to a minimal shape if absent.

    The minimal shape lets the clarification prompt run even when Phase 3 parse
    was skipped (e.g. dedup path in old data). Confidence is forced low so the
    clarifier errs toward asking rather than staying silent.
    """
    data = row.parsed_json
    if data:
        try:
            return ParsedRequirement.model_validate(data)
        except Exception:
            _log.warning(
                "parsed_json invalid, using fallback shape",
                extra={"requirement_id": row.id},
            )
    return ParsedRequirement(
        goal=row.raw_text[:120] or "(empty)",
        scope_items=[],
        deadline=None,
        open_questions=[],
        confidence=0.2,
    )


def _merge_raw_with_answers(raw: str, qa_pairs: list[dict[str, Any]]) -> str:
    """Compose a new raw_text from the original + the clarification transcript.

    The transcript is appended in a machine-friendly form so the v+1 re-parse
    can pick up the new facts without inventing them. We keep the original
    message intact so downstream systems can always trace back to the source.
    """
    lines = [raw.rstrip(), "", "Clarifications:"]
    for idx, pair in enumerate(qa_pairs, start=1):
        a = (pair.get("answer") or "").strip()
        q = (pair.get("question") or "").strip()
        lines.append(f"Q{idx}: {q}")
        lines.append(f"A{idx}: {a}")
    return "\n".join(lines)
