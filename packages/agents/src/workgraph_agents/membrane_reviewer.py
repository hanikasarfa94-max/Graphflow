"""MembraneAgentReviewer — Slice M1 of `docs/membrane-agent-review-spec.md`.

Semantic reviewer that runs *inside* `MembraneService.review(...)` after
deterministic checks have run. Distinct from `MembraneAgent` (existing
ingest classifier in `membrane.py`): that agent classifies external
content arriving from the world; this one reviews internal candidates
(KB promote in M1, task promote in M3, decision crystallize in M4)
that are about to enter shared team memory.

Contract per spec §3 / §6:
  - LLM recommends. MembraneService normalizes and enforces.
  - Don't write rows. Return structured review.
  - Return JSON only.
  - Refs cited in `conflict_with` MUST appear in the pretext.
  - Invalid output falls back to `request_review`, never `auto_merge`.

Recovery ladder mirrors EdgeAgent:
  1. JSON mode + Pydantic validation.
  2. On parse / schema error: re-prompt up to 3 attempts.
  3. After 3 attempts: deterministic fallback that requests review
     (fail-closed; never silently auto-merges).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.membrane_reviewer")

PROMPT_VERSION = "2026-05-05.M1.v1"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "membrane_reviewer"


def _load_prompt(version: str = "v1") -> str:
    return (_PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")


# Spec §4: keep the existing four actions. Don't widen the public
# vocabulary even though we may want to internally.
ReviewAction = Literal[
    "auto_merge",
    "request_review",
    "request_clarification",
    "reject",
]

Outcome = Literal["ok", "retry", "manual_review"]


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


class MembraneAgentReview(BaseModel):
    """Structured output of the Membrane Agent's semantic review.

    Service-side `MembraneReview` (in apps/api) is the *public* shape —
    this is the agent's *internal* shape. The service translates: e.g.
    drops `confidence` from the outward review, maps `conflict_with`
    refs into the existing tuple-of-ids field, etc.
    """

    model_config = ConfigDict(extra="forbid")

    action: ReviewAction
    reason: str = Field(min_length=1, max_length=120)
    diff_summary: str | None = Field(default=None, max_length=2000)
    clarify_question: str | None = Field(default=None, max_length=480)
    # Refs the agent says back the action. Format: `kb:<id>` /
    # `decision:<id>` / `task:<id>` / etc. Validated at the service
    # layer to ensure each ref appears in the pretext (the agent must
    # not invent ids).
    conflict_with: list[str] = Field(default_factory=list, max_length=12)
    warnings: list[str] = Field(default_factory=list, max_length=8)
    # Internal hint. The service uses it to map low-confidence
    # auto_merge → request_review when caution is warranted, but it
    # is NOT exposed in the public MembraneReview shape.
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("clarify_question")
    @classmethod
    def _clarify_required_for_clarification(
        cls, v: str | None, info
    ) -> str | None:
        # Note: we can't cross-validate against `action` here because
        # field_validator runs per-field. Cross-validation lives in
        # `_coerce_review_invariants` below, which the service applies
        # before mapping the agent review to the public shape.
        return v


@dataclass(slots=True)
class MembraneAgentReviewOutcome:
    review: MembraneAgentReview
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


# Fallback per spec §6: invalid output falls back to `request_review`,
# never `auto_merge`. Reason names the failure so logs can pinpoint
# why we degraded.
_FALLBACK_REVIEW = MembraneAgentReview(
    action="request_review",
    reason="agent_invalid_output_fallback",
    diff_summary=(
        "Membrane agent returned invalid output after retries; "
        "candidate held for owner review as a safety default."
    ),
    clarify_question=None,
    conflict_with=[],
    warnings=["agent_fallback"],
    confidence=0.0,
)


# ---------------------------------------------------------------------------
# Validation / coercion
# ---------------------------------------------------------------------------


def _coerce_review_invariants(
    review: MembraneAgentReview,
    *,
    pretext_refs: set[str],
) -> MembraneAgentReview:
    """Apply spec §6 invariants the agent might violate. Returns either
    the original review or a downgraded one.

    Rules applied here (vs. Pydantic field_validators):
      1. `request_clarification` MUST include `clarify_question`. If
         missing, downgrade to `request_review`.
      2. `request_review` SHOULD include `diff_summary`. If missing,
         keep action but synthesize a placeholder summary so logs
         don't show empty review reasons.
      3. Every ref in `conflict_with` MUST appear in the pretext set.
         Refs the agent invented are dropped (the agent prompt forbids
         this, but we don't trust unconditionally).
      4. Low confidence + `auto_merge` → upgrade to `request_review`.
         The threshold is 0.5; below that, fail-closed.
    """
    # Filter hallucinated refs.
    valid_refs = [r for r in review.conflict_with if r in pretext_refs]
    dropped = len(review.conflict_with) - len(valid_refs)
    warnings = list(review.warnings)
    if dropped > 0:
        warnings.append(f"agent_dropped_{dropped}_invented_refs")

    action = review.action
    diff = review.diff_summary
    clarify = review.clarify_question
    reason = review.reason

    # Rule 1: clarification without a question.
    if action == "request_clarification" and not (clarify and clarify.strip()):
        action = "request_review"
        reason = "clarification_without_question_downgraded"
        diff = (
            diff
            or "Agent requested clarification but did not provide a question."
        )

    # Rule 2: review without a diff summary.
    if action == "request_review" and not (diff and diff.strip()):
        diff = "Agent flagged for review without a diff summary."

    # Rule 4: low-confidence auto_merge fails closed.
    if action == "auto_merge" and review.confidence < 0.5:
        action = "request_review"
        reason = "low_confidence_auto_merge_downgraded"
        diff = (
            diff
            or f"Agent confidence {review.confidence:.2f} below auto_merge floor."
        )

    return MembraneAgentReview(
        action=action,
        reason=reason,
        diff_summary=diff,
        clarify_question=clarify,
        conflict_with=valid_refs,
        warnings=warnings,
        confidence=review.confidence,
    )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class MembraneAgentReviewer:
    """Owns the LLM call. The pretext is built by the service; this
    class is a thin wrapper around `complete_structured` + the recovery
    ladder + the invariant coercion.
    """

    prompt_version: str = PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt: str | None = None,
        *,
        temperature: float = 0.1,
    ) -> None:
        self._llm = llm or LLMClient()
        self._prompt = prompt or _load_prompt("v1")
        # Membrane review is classification, not chat — keep
        # temperature low. The recovery ladder drops to 0.0 on retries.
        self._temperature = temperature

    async def review_candidate(
        self,
        packet: dict[str, Any],
    ) -> MembraneAgentReviewOutcome:
        """Run the LLM on the review packet. Returns the outcome
        (review + LLM result + attempts + error).

        Caller (MembraneService) builds the packet per spec §5 and
        does NOT pass the full project state.
        """
        pretext_refs = _extract_pretext_refs(packet)

        messages = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": json.dumps(packet, ensure_ascii=False, default=str)},
        ]

        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=MembraneAgentReview,
                temperature=self._temperature,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.warning(
                "membrane_reviewer.invalid_output",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                    "candidate_kind": packet.get("candidate", {}).get("kind"),
                },
            )
            return MembraneAgentReviewOutcome(
                review=_FALLBACK_REVIEW,
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

        assert isinstance(parsed, MembraneAgentReview)
        coerced = _coerce_review_invariants(parsed, pretext_refs=pretext_refs)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "membrane_reviewer.reviewed",
            extra={
                "prompt_version": self.prompt_version,
                "attempts": attempts,
                "action": coerced.action,
                "confidence": coerced.confidence,
                "candidate_kind": packet.get("candidate", {}).get("kind"),
            },
        )
        return MembraneAgentReviewOutcome(
            review=coerced,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )


def _extract_pretext_refs(packet: dict[str, Any]) -> set[str]:
    """Collect every `ref` string the pretext exposed so we can filter
    hallucinated refs from `conflict_with`. Looks at the two sections
    that carry refs in the M1 KB packet (`retrieved_context`,
    `recent_decisions`); future packets can extend.
    """
    refs: set[str] = set()
    for entry in packet.get("retrieved_context") or []:
        ref = entry.get("ref") if isinstance(entry, dict) else None
        if isinstance(ref, str):
            refs.add(ref)
    for entry in packet.get("recent_decisions") or []:
        ref = entry.get("ref") if isinstance(entry, dict) else None
        if isinstance(ref, str):
            refs.add(ref)
    return refs


__all__ = [
    "MembraneAgentReviewer",
    "MembraneAgentReview",
    "MembraneAgentReviewOutcome",
    "PROMPT_VERSION",
]
