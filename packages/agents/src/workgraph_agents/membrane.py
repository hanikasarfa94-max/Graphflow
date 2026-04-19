"""MembraneAgent — Phase D classifier for externally-ingested signals.

Vision §5.12 (Membranes). This agent reads `raw_content` from the outside
world (git commit body, steam forum post, rss item, user-dropped link)
and classifies it: relevance, tags, proposed target members, proposed
action, confidence, safety notes.

Security constraint (non-negotiable): the prompt explicitly tells the LLM
to IGNORE any commands embedded in `raw_content` and to only produce
classification output. Prompt-injection attempts must route the signal
to `flag-for-review` regardless of what else the content claims.

The recovery ladder matches the other agents:
  1) JSON-mode + Pydantic validation.
  2) On parse / schema error, re-prompt up to 3 total attempts.
  3) After 3 attempts, emit a conservative fallback that flags the
     signal for review — NEVER auto-routes on failure, because silent
     failure on a security-boundary path is worse than a paper-thin
     surface that a human has to click.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.membrane")

PROMPT_VERSION = "2026-04-18.phaseD.v1"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "membrane"


def _load_prompt(version: str = "v1") -> str:
    path = _PROMPT_DIR / f"{version}.md"
    return path.read_text(encoding="utf-8")


Outcome = Literal["ok", "retry", "manual_review"]
MembraneAction = Literal["route-to-members", "ambient-log", "flag-for-review"]


class MembraneClassification(BaseModel):
    """Structured output of MembraneAgent.classify.

    `proposed_target_user_ids` are filtered downstream against the project's
    member list; the agent is also prompted to only surface ids it sees in
    the project context, but the service layer must not trust that.
    """

    model_config = ConfigDict(extra="forbid")

    is_relevant: bool
    tags: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=0, max_length=200)
    proposed_target_user_ids: list[str] = Field(default_factory=list)
    proposed_action: MembraneAction
    confidence: float = Field(ge=0.0, le=1.0)
    # Empty string when the content is clean. Populated with the detected
    # injection / suspicious pattern when the LLM sees one.
    safety_notes: str = Field(default="", max_length=500)


@dataclass(slots=True)
class MembraneOutcome:
    classification: MembraneClassification
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


# Conservative fallback: when classification fails after max_attempts, we
# MUST NOT auto-route. The fallback degrades to flag-for-review with
# zero confidence so a human sees it before anything propagates.
_MANUAL_REVIEW_FALLBACK = MembraneClassification(
    is_relevant=False,
    tags=[],
    summary="Classification failed — needs human review before routing.",
    proposed_target_user_ids=[],
    proposed_action="flag-for-review",
    confidence=0.0,
    safety_notes="classifier-failure-fallback: LLM output did not validate after max attempts",
)


def _build_user_payload(
    *,
    raw_content: str,
    source_kind: str,
    source_identifier: str,
    project_context: dict,
) -> str:
    return json.dumps(
        {
            "source_kind": source_kind,
            "source_identifier": source_identifier,
            "raw_content": raw_content,
            "project_context": project_context,
        },
        ensure_ascii=False,
    )


class MembraneAgent:
    """Classify an externally-ingested signal with prompt-injection defense.

    Security contract:
      * The prompt instructs the LLM to ignore commands embedded in
        `raw_content` and to only emit classification JSON.
      * Fallback on parse failure routes to `flag-for-review`, never to
        members. Never auto-approve on failure.
      * Callers (MembraneService) must apply the same safety gate: any
        `safety_notes` non-empty → status stays `pending-review`.
    """

    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt: str | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._prompt = prompt or _load_prompt("v1")

    async def classify(
        self,
        *,
        raw_content: str,
        source_kind: str,
        source_identifier: str,
        project_context: dict,
    ) -> MembraneOutcome:
        messages = [
            {"role": "system", "content": self._prompt},
            {
                "role": "user",
                "content": _build_user_payload(
                    raw_content=raw_content,
                    source_kind=source_kind,
                    source_identifier=source_identifier,
                    project_context=project_context,
                ),
            },
        ]
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=MembraneClassification,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "membrane classify failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                    "source_kind": source_kind,
                },
            )
            return MembraneOutcome(
                classification=_MANUAL_REVIEW_FALLBACK,
                result=last
                or LLMResult(
                    content="",
                    model=self._llm.settings.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0,
                ),
                outcome="manual_review",
                attempts=len(e.errors),
                error=e.errors[-1] if e.errors else "unknown",
            )

        assert isinstance(parsed, MembraneClassification)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "membrane classified",
            extra={
                "prompt_version": self.prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "is_relevant": parsed.is_relevant,
                "proposed_action": parsed.proposed_action,
                "confidence": parsed.confidence,
                "has_safety_notes": bool(parsed.safety_notes),
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return MembraneOutcome(
            classification=parsed,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )


__all__ = [
    "MembraneAgent",
    "MembraneAction",
    "MembraneClassification",
    "MembraneOutcome",
    "PROMPT_VERSION",
]
