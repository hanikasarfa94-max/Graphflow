from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.requirement")

# Prompt version — bump when the prompt changes so drift metrics can track it.
PROMPT_VERSION = "2026-04-17.phase3.v1"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "requirement"


def _load_prompt(version: str = "v1") -> str:
    path = _PROMPT_DIR / f"{version}.md"
    return path.read_text(encoding="utf-8")


Outcome = Literal["ok", "retry", "manual_review"]


class ParsedRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1)
    scope_items: list[str] = Field(default_factory=list)
    deadline: str | None = None
    open_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


@dataclass(slots=True)
class ParseOutcome:
    """Structured result from RequirementAgent.parse().

    `parsed` is always set: on manual_review we emit a placeholder so
    downstream code can still persist something; `outcome` + `error`
    signal that human attention is needed.
    """

    parsed: ParsedRequirement
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


# Placeholder used when all automatic parsing attempts fail (2C4).
_MANUAL_REVIEW_FALLBACK = ParsedRequirement(
    goal="[manual review required — automatic parsing failed]",
    scope_items=[],
    deadline=None,
    open_questions=[
        "We could not automatically understand your request. "
        "Could you rephrase it, including the deliverable and any deadline?",
    ],
    confidence=0.0,
)


class RequirementAgent:
    """Parse raw requirement text into ParsedRequirement.

    Recovery ladder (decision 2C4):
      1) JSON mode.
      2) On JSON/schema error: re-prompt with the error (one retry).
      3) On second failure: re-prompt with the error again.
      4) After 3 attempts: emit placeholder with outcome=manual_review.

    Emits a structured log per call including prompt_version,
    latency_ms, token counts, cache_read_tokens, confidence, outcome.
    """

    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt: str | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._prompt = prompt or _load_prompt("v1")

    async def parse(self, text: str) -> ParseOutcome:
        messages = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": text},
        ]
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=ParsedRequirement,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "requirement parse failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return ParseOutcome(
                parsed=_MANUAL_REVIEW_FALLBACK,
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

        outcome: Outcome = "ok" if attempts == 1 else "retry"
        # ParsedRequirement is the static return type of complete_structured
        # when pydantic_cls=ParsedRequirement.
        assert isinstance(parsed, ParsedRequirement)
        _log.info(
            "requirement parsed",
            extra={
                "prompt_version": self.prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
                "confidence": parsed.confidence,
                "scope_count": len(parsed.scope_items),
            },
        )
        return ParseOutcome(
            parsed=parsed,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )
