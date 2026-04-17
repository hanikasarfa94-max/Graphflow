from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .llm import LLMClient, LLMResult

_log = logging.getLogger("workgraph.agents.requirement")

# Prompt version — bump when the prompt changes so drift metrics can track it.
PROMPT_VERSION = "2026-04-17.phase2_5.v1"

SYSTEM_PROMPT = """You are a requirement intake analyst for a coordination platform.

Given a short raw requirement message, return a structured parse as JSON with these fields:

{
  "goal": string — one short sentence capturing the primary outcome,
  "scope_items": string[] — distinct deliverables or features mentioned (3-8 items),
  "deadline": string | null — deadline phrase as written (e.g. "next week", "2026-04-24") or null if none,
  "open_questions": string[] — clarification questions a reasonable engineer would ask (1-5),
  "confidence": number — 0.0 to 1.0, how confidently the parse reflects the input
}

Rules:
- Output ONLY the JSON object. No prose, no markdown fences.
- Every scope_item should be a concrete noun phrase (not a full sentence).
- Open questions must be specific, not generic ("What are the invitation code rules?" not "Can you clarify?").
- If the input is too vague to parse meaningfully, lower confidence and surface that in open_questions.
"""


class ParsedRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1)
    scope_items: list[str] = Field(default_factory=list)
    deadline: str | None = None
    open_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class RequirementAgent:
    """Baseline parser. Phase 3 replaces with the fully-engineered prompt +
    Instructor fallback + per-field confidence + caching.
    """

    prompt_version = PROMPT_VERSION

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm or LLMClient()

    async def parse(self, text: str) -> tuple[ParsedRequirement, LLMResult]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        data, result = await self._llm.complete_json(messages)
        try:
            parsed = ParsedRequirement.model_validate(data)
        except ValidationError as e:
            _log.warning(
                "requirement parse schema fail",
                extra={"prompt_version": self.prompt_version, "errors": e.errors()},
            )
            raise
        _log.info(
            "requirement parsed",
            extra={
                "prompt_version": self.prompt_version,
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "confidence": parsed.confidence,
                "scope_count": len(parsed.scope_items),
            },
        )
        return parsed, result
