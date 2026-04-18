from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .llm import LLMClient, LLMResult, ParseFailure
from .requirement import ParsedRequirement

_log = logging.getLogger("workgraph.agents.clarification")

PROMPT_VERSION = "2026-04-17.phase4.v1"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "clarification"

MAX_QUESTIONS = 3


def _load_prompt(version: str = "v1") -> str:
    path = _PROMPT_DIR / f"{version}.md"
    return path.read_text(encoding="utf-8")


Outcome = Literal["ok", "retry", "manual_review"]

TargetRole = Literal[
    "pm", "frontend", "backend", "qa", "design", "business", "approver", "unknown"
]
BlockingLevel = Literal["low", "medium", "high"]


class ClarificationQuestionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    target_role: TargetRole = "unknown"
    blocking_level: BlockingLevel = "medium"
    reason: str = Field(default="", max_length=500)


class ClarificationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[ClarificationQuestionItem] = Field(default_factory=list)

    @field_validator("questions")
    @classmethod
    def _cap(cls, v: list[ClarificationQuestionItem]) -> list[ClarificationQuestionItem]:
        # Hard cap enforced at the schema layer. If the LLM hands back 5,
        # we keep the top 3 — de-dup first, then prefer higher blocking.
        if len(v) <= MAX_QUESTIONS:
            return v
        order = {"high": 0, "medium": 1, "low": 2}
        sorted_qs = sorted(v, key=lambda q: order.get(q.blocking_level, 3))
        return sorted_qs[:MAX_QUESTIONS]


@dataclass(slots=True)
class ClarificationOutcome:
    """Batch of generated questions + LLM result envelope.

    On manual_review we return an empty batch and the service persists no
    questions; the requirement-row stays unchanged so a human can intervene.
    """

    batch: ClarificationBatch
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


_MANUAL_REVIEW_FALLBACK = ClarificationBatch(questions=[])


def _build_user_payload(raw_text: str, parsed: ParsedRequirement) -> str:
    return json.dumps(
        {"raw_text": raw_text, "parsed": parsed.model_dump()},
        ensure_ascii=False,
    )


class ClarificationAgent:
    """Generate 0-3 focused questions from a parsed requirement.

    Recovery ladder matches RequirementAgent (decision 2C4):
      1) JSON mode.
      2) On JSON/schema error: re-prompt with the error (up to 3 attempts total).
      3) After 3 attempts: emit empty batch with outcome=manual_review.

    The hard cap of 3 questions is enforced at the Pydantic layer
    (ClarificationBatch validator) so a chatty model cannot bypass it.
    """

    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt: str | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._prompt = prompt or _load_prompt("v1")

    async def generate(
        self, *, raw_text: str, parsed: ParsedRequirement
    ) -> ClarificationOutcome:
        messages = [
            {"role": "system", "content": self._prompt},
            {"role": "user", "content": _build_user_payload(raw_text, parsed)},
        ]
        try:
            batch, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=ClarificationBatch,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "clarification generation failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return ClarificationOutcome(
                batch=_MANUAL_REVIEW_FALLBACK,
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

        assert isinstance(batch, ClarificationBatch)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "clarification generated",
            extra={
                "prompt_version": self.prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
                "question_count": len(batch.questions),
            },
        )
        return ClarificationOutcome(
            batch=batch,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )
