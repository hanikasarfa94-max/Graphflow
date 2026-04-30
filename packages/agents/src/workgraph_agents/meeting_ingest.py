"""MeetingIngestAgent — LLM extraction of meeting transcripts.

Phase 2.B metabolizer: read an uploaded transcript, return decisions,
action items, risks, and recorded stances as structured proposals.
The orchestration layer (`MeetingIngestService` in apps/api/services/)
owns DB writes, status lifecycle, event emission, and accept-as-row
plumbing; this module owns only the LLM call and its schema.

Lives in `packages/agents/` per the architectural invariant that
LLM orchestration is centralized here (CLAUDE.md §"Architectural
invariants"). Originally co-located with the service; split per
graphify diagnosis F6 (2026-04-27).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .llm import LLMClient, ParseFailure

_log = logging.getLogger("workgraph.agents.meeting_ingest")

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


__all__ = [
    "METABOLIZE_PROMPT_VERSION",
    "LLMBackedMetabolizer",
    "MeetingMetabolizer",
    "MetabolizeOutcome",
    "MetabolizedDecision",
    "MetabolizedRisk",
    "MetabolizedSignals",
    "MetabolizedStance",
    "MetabolizedTask",
]
