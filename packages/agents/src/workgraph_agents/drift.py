"""Drift detection agent — vision.md §5.8.

Continuously checks whether recently crystallized decisions + active work
still match the committed thesis. Surfaces drift as in-stream cards so
owners see divergence on day 2, not at final review.

v1 note: a formal ThesisRow doesn't exist yet (thesis-commit §5.2 is still
pending). We use the latest RequirementRow text as the proxy for "what was
committed" — the orchestrating DriftService is responsible for fetching it
and passing it in.

Recovery ladder matches every other phase-3+ agent (decision 2C4):
  1) JSON mode with Pydantic validation.
  2) On JSON / schema error: reprompt with the error, up to 3 attempts.
  3) After 3 attempts: deterministic no-drift fallback + outcome=
     "manual_review" so the caller can surface a chip. We choose a
     no-drift fallback (rather than "drift of unknown shape") because
     posting a fabricated alert on a failed parse is worse UX than
     staying quiet — the agent log captures the failure for the
     dashboard.

Prompt contracts stay provider-agnostic (DeepSeek in dev per project
memory). The prompt body is static; per-call context changes, so prompt
caching pays off under the standard LLMClient.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.drift")

PROMPT_VERSION = "2026-04-18.drift.v1"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "drift"


def _load_prompt(version: str = "v1") -> str:
    return (_PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")


Outcome = Literal["ok", "retry", "manual_review"]
Severity = Literal["low", "medium", "high"]


class DriftItem(BaseModel):
    """One piece of drift the agent flagged.

    `affected_user_ids` is the list the DriftService fans out to — each
    listed user's personal stream gets a drift-alert card.
    """

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1, max_length=160)
    severity: Severity
    what_drifted: str = Field(min_length=1, max_length=500)
    vs_thesis_or_decision: str = Field(min_length=1, max_length=500)
    suggested_next_step: str = Field(min_length=1, max_length=320)
    affected_user_ids: list[str] = Field(default_factory=list, max_length=10)


class DriftCheckResult(BaseModel):
    """Structured output of DriftAgent.check.

    If `has_drift=False`, `drift_items` must be empty (enforced by a
    model-level validator so a chatty model can't claim "no drift" while
    returning items). `reasoning` is a short observability note — not
    user-facing; logged for dashboards.
    """

    model_config = ConfigDict(extra="forbid")

    has_drift: bool
    drift_items: list[DriftItem] = Field(default_factory=list, max_length=5)
    reasoning: str = Field(default="", max_length=500)

    def model_post_init(self, __context: Any) -> None:
        # Cross-field invariant: has_drift=False ↔ drift_items=[].
        # We coerce rather than raise so the recovery ladder stays smooth;
        # an inconsistent response gets normalised, not retried.
        if not self.has_drift and self.drift_items:
            object.__setattr__(self, "drift_items", [])
        if self.has_drift and not self.drift_items:
            object.__setattr__(self, "has_drift", False)


@dataclass(slots=True)
class DriftCheckOutcome:
    result_payload: DriftCheckResult
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


_MANUAL_REVIEW_FALLBACK = DriftCheckResult(
    has_drift=False,
    drift_items=[],
    reasoning="drift agent manual review fallback (no alerts posted)",
)


def _build_user_payload(context: dict[str, Any]) -> str:
    return json.dumps(context, ensure_ascii=False, default=str)


class DriftAgent:
    """Detects drift between committed thesis and recent work.

    Input `context` keys (DriftService populates these):
      * project_id, title
      * committed_thesis — latest requirement text (v1 proxy for thesis)
      * recent_decisions — last 20, each {id, option_index, custom_text,
        rationale, created_at, apply_outcome}
      * active_tasks — {id, title, description, status, assignee_role}
      * recent_completed_deliverables — {id, title, kind}

    Output: `DriftCheckResult`. On parse failure after 3 attempts the agent
    returns a deterministic no-drift fallback with outcome=manual_review so
    the service logs it but doesn't spam users with fabricated alerts.
    """

    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt: str | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._prompt = prompt or _load_prompt("v1")

    async def check(self, context: dict[str, Any]) -> DriftCheckOutcome:
        messages = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": _build_user_payload(context)},
        ]
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=DriftCheckResult,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "drift check failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return DriftCheckOutcome(
                result_payload=_MANUAL_REVIEW_FALLBACK,
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

        assert isinstance(parsed, DriftCheckResult)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "drift checked",
            extra={
                "prompt_version": self.prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "has_drift": parsed.has_drift,
                "drift_count": len(parsed.drift_items),
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return DriftCheckOutcome(
            result_payload=parsed,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )


__all__ = [
    "PROMPT_VERSION",
    "DriftAgent",
    "DriftCheckOutcome",
    "DriftCheckResult",
    "DriftItem",
]
