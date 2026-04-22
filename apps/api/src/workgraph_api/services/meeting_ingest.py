"""MeetingIngestService — Phase 2.B uploaded meeting transcript metabolism.

Meetings still happen even when the platform is wired end-to-end. The
plan's take: accept uploaded text (Feishu Minutes export, Zoom transcript,
typed notes), let the edge LLM pull out the four signal kinds that
matter — decisions reached, action items, risks raised, participants'
stances — and surface them as *proposals*. The human clicks "Accept"
to route a proposal through the existing DecisionRow / TaskRow / RiskRow
creation paths; nothing flows into the graph silently.

Design choices:
  * Upload-only. No ASR in v1 (voice capture is an explicit v5 concern).
    Clients that can export text (Feishu Minutes, Zoom, Otter, plus
    typed notes) cover ~80% of meetings that matter.
  * Fire-and-forget background metabolism. Upload completes as soon as
    the row is written; the LLM pass runs in an `asyncio.create_task`.
    Same pattern as DriftService — keeps the POST fast, and a failed
    LLM pass doesn't fail the upload. The row's `metabolism_status`
    reflects progress so the UI can poll or refresh.
  * Proposals only. `extracted_signals` is a JSON blob on the
    MeetingTranscriptRow; nothing in graph_risks / plan_tasks / decisions
    changes until someone accepts a specific signal. The `accept`
    endpoint routes through the existing domain services so proposals
    become first-class rows with their usual invariants.
  * Malformed LLM output is survivable. If the metabolizer raises or
    returns non-conforming JSON after retries, status flips to 'failed'
    with `error_message` populated; the signals blob stays empty. An
    owner can re-run metabolism from the detail page.

The metabolizer protocol is intentionally minimal — anything with a
`metabolize(transcript_text, participant_context)` coroutine that
returns a `MetabolizedSignals`-shaped object works. The default impl
wraps `LLMClient.complete_structured`; tests pass a scripted stub
through `app.state.meeting_metabolizer`.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    MeetingTranscriptRepository,
    MeetingTranscriptRow,
    PlanRepository,
    ProjectGraphRepository,
    ProjectRow,
    RequirementRepository,
    UserRepository,
    session_scope,
)
from sqlalchemy import select

from workgraph_agents.llm import LLMClient, ParseFailure

_log = logging.getLogger("workgraph.api.meeting_ingest")

# Hard upper bound on transcript size. Matches the ORM column hint in
# the plan (≤50_000 chars). Anything longer than this is either the
# output of an ASR loop that's been running for hours or a paste of
# a wiki dump — either way, not a meeting.
MAX_TRANSCRIPT_CHARS = 50_000

# Minimum viable transcript length. Below this there's nothing the
# metabolizer could plausibly extract, so we reject at upload rather
# than burn an LLM call on it.
MIN_TRANSCRIPT_CHARS = 20


METABOLIZE_PROMPT_VERSION = "2026-04-22.phase2B.v1"


# ---------------------------------------------------------------------------
# Structured output schemas — the metabolize prompt returns these.
# ---------------------------------------------------------------------------


class MetabolizedDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    rationale: str = Field(default="", max_length=500)


class MetabolizedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=1000)
    # Free-text hint, not a user_id — the uploader may not even know
    # the platform user_ids for meeting attendees.
    suggested_owner_hint: str = Field(default="", max_length=120)


class MetabolizedRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    content: str = Field(default="", max_length=1000)
    severity: str = Field(default="medium", max_length=16)


class MetabolizedStance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_hint: str = Field(min_length=1, max_length=120)
    topic: str = Field(min_length=1, max_length=240)
    stance: str = Field(min_length=1, max_length=500)


class MetabolizedSignals(BaseModel):
    """Root pydantic class the metabolizer produces.

    All four lists are allowed to be empty — a 5-minute status meeting
    might genuinely have zero action items. Empty-everything is
    indistinguishable from "LLM returned nothing useful"; the service
    treats it as a successful metabolism regardless so the UI can
    render "no signals extracted" instead of presenting a failure.
    """

    model_config = ConfigDict(extra="forbid")

    decisions: list[MetabolizedDecision] = Field(default_factory=list, max_length=20)
    tasks: list[MetabolizedTask] = Field(default_factory=list, max_length=30)
    risks: list[MetabolizedRisk] = Field(default_factory=list, max_length=20)
    stances: list[MetabolizedStance] = Field(default_factory=list, max_length=30)


# ---------------------------------------------------------------------------
# Metabolizer protocol + default impl.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MetabolizeOutcome:
    signals: MetabolizedSignals
    outcome: str  # "ok" | "failed"
    error: str | None = None


class MeetingMetabolizer(Protocol):
    async def metabolize(
        self,
        *,
        transcript_text: str,
        participant_context: list[dict[str, Any]],
    ) -> MetabolizeOutcome:
        ...


_SYSTEM_PROMPT = (
    "You extract structured signals from an uploaded meeting transcript. "
    "Return ONLY a valid JSON object with these four keys, each a list:\n"
    "  * decisions — {text, rationale} items; explicit choices the group made.\n"
    "  * tasks — {title, description, suggested_owner_hint} action items; "
    "suggested_owner_hint is a human name / role / empty string (NOT a user id).\n"
    "  * risks — {title, content, severity} concerns raised; severity ∈ "
    "{low, medium, high}.\n"
    "  * stances — {participant_hint, topic, stance} recorded positions on "
    "unresolved topics; participant_hint is the speaker label from the "
    "transcript.\n"
    "If the transcript contains none of a given kind, return an empty list "
    "for that key. Do not hallucinate signals that aren't grounded in the "
    "transcript text. No markdown, no prose outside the JSON."
)


class LLMBackedMetabolizer:
    """Default metabolizer: calls LLMClient.complete_structured with the
    Phase 2.B extraction prompt. Tests inject a scripted stub instead."""

    prompt_version = METABOLIZE_PROMPT_VERSION

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm or LLMClient()

    async def metabolize(
        self,
        *,
        transcript_text: str,
        participant_context: list[dict[str, Any]],
    ) -> MetabolizeOutcome:
        participants_line = (
            "Known participants (best-effort from upload): "
            + ", ".join(
                p.get("display_name") or p.get("username") or ""
                for p in participant_context
                if p.get("display_name") or p.get("username")
            )
            if participant_context
            else "Participants: not provided; infer from speaker labels if any."
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{participants_line}\n\n"
                    f"Transcript:\n{transcript_text}"
                ),
            },
        ]
        try:
            parsed, _result, _attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=MetabolizedSignals,
                max_attempts=3,
            )
        except ParseFailure as e:
            _log.error(
                "meeting.metabolize failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return MetabolizeOutcome(
                signals=MetabolizedSignals(),
                outcome="failed",
                error=e.errors[-1] if e.errors else "unknown",
            )
        assert isinstance(parsed, MetabolizedSignals)
        return MetabolizeOutcome(signals=parsed, outcome="ok")


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class MeetingIngestError(Exception):
    """Raised for validation failures — routers map to 4xx."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class MeetingIngestService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        metabolizer: MeetingMetabolizer,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._metabolizer = metabolizer
        # Tests can `await service.drain()` to let background tasks
        # complete before assertions. Prod doesn't need to — the
        # lifecycle is short-lived and cancellation at shutdown is OK.
        self._inflight: set[asyncio.Task] = set()

    # ---- public upload / list / detail --------------------------------

    async def upload(
        self,
        *,
        project_id: str,
        uploader_user_id: str,
        title: str,
        transcript_text: str,
        participant_user_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        text = (transcript_text or "").strip()
        if len(text) < MIN_TRANSCRIPT_CHARS:
            raise MeetingIngestError("transcript_too_short")
        if len(text) > MAX_TRANSCRIPT_CHARS:
            # Truncate rather than reject — pastes from long meetings
            # hit the cap, but the first 50k chars is still plenty to
            # metabolize. Surface the truncation in the stored row
            # so the reader knows they're not seeing the whole thing
            # (UI shows a "truncated" chip off the length).
            text = text[:MAX_TRANSCRIPT_CHARS]

        participants = [p for p in (participant_user_ids or []) if p]

        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                raise MeetingIngestError("project_not_found", status=404)
            row = await MeetingTranscriptRepository(session).create(
                project_id=project_id,
                uploader_user_id=uploader_user_id,
                title=(title or "").strip()[:500],
                transcript_text=text,
                participant_user_ids=participants,
            )
            transcript_id = row.id
            payload = _transcript_list_payload(row)

        await self._event_bus.emit(
            "meeting.uploaded",
            {
                "transcript_id": transcript_id,
                "project_id": project_id,
                "uploader_user_id": uploader_user_id,
                "trace_id": get_trace_id(),
            },
        )

        self._spawn_metabolize(transcript_id=transcript_id)
        return {"ok": True, "transcript": payload}

    async def list_for_project(
        self, project_id: str
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            rows = await MeetingTranscriptRepository(
                session
            ).list_for_project(project_id, limit=200)
            return [_transcript_list_payload(r) for r in rows]

    async def detail(
        self, transcript_id: str, *, project_id: str
    ) -> dict[str, Any] | None:
        async with session_scope(self._sessionmaker) as session:
            row = await MeetingTranscriptRepository(session).get(
                transcript_id
            )
            if row is None or row.project_id != project_id:
                return None
            return _transcript_detail_payload(row)

    async def remetabolize(
        self, *, transcript_id: str, project_id: str
    ) -> dict[str, Any]:
        """Clear extracted_signals + re-run metabolism. Owner-only; the
        router checks role before calling. Idempotent-ish: if another
        metabolism is already running the second call just spawns a
        second task — the finalize write in the repo is last-wins,
        which is fine for an infrequent owner action."""
        async with session_scope(self._sessionmaker) as session:
            repo = MeetingTranscriptRepository(session)
            row = await repo.get(transcript_id)
            if row is None or row.project_id != project_id:
                raise MeetingIngestError("transcript_not_found", status=404)
            await repo.reset_for_remetabolism(transcript_id)

        self._spawn_metabolize(transcript_id=transcript_id)
        return {"ok": True, "transcript_id": transcript_id, "status": "pending"}

    # ---- accept a specific proposed signal ----------------------------

    async def accept_signal(
        self,
        *,
        transcript_id: str,
        project_id: str,
        signal_kind: str,
        signal_idx: int,
        actor_id: str,
    ) -> dict[str, Any]:
        """Convert one proposed signal into a real ORM row.

        Routes through the canonical repos so downstream invariants
        (requirement_id on Risks/Tasks, sort_order, etc.) stay honest.
        Returns a shape the UI can use to render the newly-created
        row inline (`{ok, kind, entity_id}`)."""
        if signal_kind not in {"decision", "task", "risk"}:
            raise MeetingIngestError("invalid_signal_kind")

        async with session_scope(self._sessionmaker) as session:
            repo = MeetingTranscriptRepository(session)
            row = await repo.get(transcript_id)
            if row is None or row.project_id != project_id:
                raise MeetingIngestError("transcript_not_found", status=404)
            if row.metabolism_status != "done":
                raise MeetingIngestError("not_metabolized", status=409)

            signals = dict(row.extracted_signals or {})
            bucket_name = {
                "decision": "decisions",
                "task": "tasks",
                "risk": "risks",
            }[signal_kind]
            bucket = list(signals.get(bucket_name) or [])
            if signal_idx < 0 or signal_idx >= len(bucket):
                raise MeetingIngestError("signal_not_found", status=404)
            signal = dict(bucket[signal_idx])

            created_entity_id: str | None = None

            if signal_kind == "decision":
                from workgraph_persistence import DecisionRepository

                text = (signal.get("text") or "").strip()
                rationale = (signal.get("rationale") or "").strip()
                if not text:
                    raise MeetingIngestError("signal_empty")
                decision = await DecisionRepository(session).create(
                    conflict_id=None,
                    project_id=project_id,
                    resolver_id=actor_id,
                    option_index=None,
                    custom_text=text[:4000],
                    rationale=(rationale or f"Accepted from meeting: {row.title or 'meeting'}")[:4000],
                    apply_actions=[
                        {
                            "kind": "advisory",
                            "source": "meeting_transcript",
                            "transcript_id": transcript_id,
                        }
                    ],
                    trace_id=get_trace_id(),
                    apply_outcome="advisory",
                )
                created_entity_id = decision.id
            elif signal_kind == "task":
                req = await RequirementRepository(
                    session
                ).latest_for_project(project_id)
                if req is None:
                    raise MeetingIngestError(
                        "requirement_not_ready", status=409
                    )
                # Append one TaskRow directly. We bypass PlanRepository's
                # idempotent append_plan because that's batch-scoped to
                # a fresh requirement version; single-row accept wants
                # an explicit insert with the next sort_order.
                from workgraph_persistence import TaskRow as _TaskRow
                from uuid import uuid4 as _uuid4

                existing = await PlanRepository(session).list_tasks(req.id)
                next_sort = (
                    max((t.sort_order for t in existing), default=-1) + 1
                )
                task_row = _TaskRow(
                    id=str(_uuid4()),
                    project_id=project_id,
                    requirement_id=req.id,
                    sort_order=next_sort,
                    deliverable_id=None,
                    title=(signal.get("title") or "")[:500] or "Action item",
                    description=(signal.get("description") or "")[:2000],
                    assignee_role="unknown",
                )
                session.add(task_row)
                await session.flush()
                created_entity_id = task_row.id
            else:  # risk
                req = await RequirementRepository(
                    session
                ).latest_for_project(project_id)
                if req is None:
                    raise MeetingIngestError(
                        "requirement_not_ready", status=409
                    )
                from workgraph_persistence import RiskRow as _RiskRow
                from uuid import uuid4 as _uuid4

                existing_risks = await ProjectGraphRepository(
                    session
                ).list_risks(req.id)
                next_sort = (
                    max((r.sort_order for r in existing_risks), default=-1)
                    + 1
                )
                severity = (signal.get("severity") or "medium").lower()
                if severity not in {"low", "medium", "high"}:
                    severity = "medium"
                risk_row = _RiskRow(
                    id=str(_uuid4()),
                    project_id=project_id,
                    requirement_id=req.id,
                    sort_order=next_sort,
                    title=(signal.get("title") or "")[:500] or "Risk raised in meeting",
                    content=(signal.get("content") or "")[:2000],
                    severity=severity,
                )
                session.add(risk_row)
                await session.flush()
                created_entity_id = risk_row.id

            # Mark the bucket item as accepted so the UI can grey it out
            # and prevent a double-accept. The transcript row owns its
            # extracted_signals, so this is a local state mutation.
            signal["_accepted_entity_id"] = created_entity_id
            signal["_accepted_by"] = actor_id
            bucket[signal_idx] = signal
            signals[bucket_name] = bucket
            row.extracted_signals = signals
            await session.flush()

        await self._event_bus.emit(
            "meeting.signal_accepted",
            {
                "transcript_id": transcript_id,
                "project_id": project_id,
                "signal_kind": signal_kind,
                "signal_idx": signal_idx,
                "entity_id": created_entity_id,
                "actor_id": actor_id,
                "trace_id": get_trace_id(),
            },
        )
        return {
            "ok": True,
            "signal_kind": signal_kind,
            "entity_id": created_entity_id,
        }

    # ---- lifecycle helpers --------------------------------------------

    async def drain(self) -> None:
        """Wait for in-flight metabolism tasks to finish. Used by tests
        so asserts can see the finalized row without sleeping."""
        if not self._inflight:
            return
        await asyncio.gather(*self._inflight, return_exceptions=True)

    # ---- internals -----------------------------------------------------

    def _spawn_metabolize(self, *, transcript_id: str) -> None:
        task = asyncio.create_task(self._metabolize(transcript_id))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def _metabolize(self, transcript_id: str) -> None:
        """Background metabolism: load the row, assemble participant
        context, call the metabolizer, persist the result. Failures
        are caught locally so the task never raises into the event
        loop unhandled."""
        try:
            async with session_scope(self._sessionmaker) as session:
                repo = MeetingTranscriptRepository(session)
                row = await repo.mark_metabolism_started(transcript_id)
                if row is None:
                    return
                transcript_text = row.transcript_text
                participant_ids = list(row.participant_user_ids or [])
                participant_context: list[dict[str, Any]] = []
                if participant_ids:
                    user_repo = UserRepository(session)
                    for uid in participant_ids:
                        u = await user_repo.get(uid)
                        if u is None:
                            continue
                        participant_context.append(
                            {
                                "user_id": u.id,
                                "username": u.username,
                                "display_name": u.display_name or u.username,
                            }
                        )
                project_id = row.project_id

            outcome = await self._metabolizer.metabolize(
                transcript_text=transcript_text,
                participant_context=participant_context,
            )
            extracted = outcome.signals.model_dump() if outcome.signals else {}

            async with session_scope(self._sessionmaker) as session:
                repo = MeetingTranscriptRepository(session)
                await repo.finalize_metabolism(
                    transcript_id,
                    status="done" if outcome.outcome == "ok" else "failed",
                    extracted_signals=extracted,
                    error_message=outcome.error,
                )

            await self._event_bus.emit(
                "meeting.metabolized",
                {
                    "transcript_id": transcript_id,
                    "project_id": project_id,
                    "status": "done" if outcome.outcome == "ok" else "failed",
                    "trace_id": get_trace_id(),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            _log.exception(
                "meeting.metabolize crashed",
                extra={"transcript_id": transcript_id},
            )
            try:
                async with session_scope(self._sessionmaker) as session:
                    await MeetingTranscriptRepository(session).finalize_metabolism(
                        transcript_id,
                        status="failed",
                        extracted_signals={},
                        error_message=f"{type(exc).__name__}: {exc}"[:2000],
                    )
            except Exception:
                _log.exception(
                    "meeting.metabolize: failed to record failure row",
                    extra={"transcript_id": transcript_id},
                )


# ---------------------------------------------------------------------------
# Row serialization helpers
# ---------------------------------------------------------------------------


def _transcript_list_payload(row: MeetingTranscriptRow) -> dict[str, Any]:
    """Compact payload for list views — no full transcript text."""
    return {
        "id": row.id,
        "project_id": row.project_id,
        "uploader_user_id": row.uploader_user_id,
        "title": row.title or "",
        "participant_user_ids": list(row.participant_user_ids or []),
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
        "metabolism_status": row.metabolism_status,
        "metabolism_completed_at": (
            row.metabolism_completed_at.isoformat()
            if row.metabolism_completed_at
            else None
        ),
        "transcript_length": len(row.transcript_text or ""),
    }


def _transcript_detail_payload(row: MeetingTranscriptRow) -> dict[str, Any]:
    base = _transcript_list_payload(row)
    base["transcript_text"] = row.transcript_text or ""
    base["extracted_signals"] = dict(row.extracted_signals or {})
    base["error_message"] = row.error_message
    base["metabolism_started_at"] = (
        row.metabolism_started_at.isoformat()
        if row.metabolism_started_at
        else None
    )
    return base


__all__ = [
    "MAX_TRANSCRIPT_CHARS",
    "MIN_TRANSCRIPT_CHARS",
    "METABOLIZE_PROMPT_VERSION",
    "LLMBackedMetabolizer",
    "MeetingIngestError",
    "MeetingIngestService",
    "MeetingMetabolizer",
    "MetabolizeOutcome",
    "MetabolizedDecision",
    "MetabolizedRisk",
    "MetabolizedSignals",
    "MetabolizedStance",
    "MetabolizedTask",
]
