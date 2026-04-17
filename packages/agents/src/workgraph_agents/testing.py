"""Test-only stubs. Import only from tests/conftest; never from prod code."""

from __future__ import annotations

from typing import Literal

from .llm import LLMResult
from .requirement import ParsedRequirement, ParseOutcome

_DEFAULT_PARSED = ParsedRequirement(
    goal="stub goal",
    scope_items=["stub item 1", "stub item 2"],
    deadline=None,
    open_questions=["stub question"],
    confidence=0.8,
)


class StubRequirementAgent:
    """Deterministic stand-in for RequirementAgent — no network calls.

    Use in tests that exercise intake plumbing (dedup, persistence, events)
    but don't care about LLM quality.
    """

    prompt_version = "stub.v1"

    def __init__(
        self,
        parsed: ParsedRequirement | None = None,
        outcome: Literal["ok", "retry", "manual_review"] = "ok",
        attempts: int = 1,
        latency_ms: int = 5,
        prompt_tokens: int = 100,
        completion_tokens: int = 50,
        cache_read_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        self._parsed = parsed or _DEFAULT_PARSED
        self._outcome = outcome
        self._attempts = attempts
        self._latency_ms = latency_ms
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._cache_read_tokens = cache_read_tokens
        self._error = error
        self.calls: list[str] = []

    async def parse(self, text: str) -> ParseOutcome:
        self.calls.append(text)
        return ParseOutcome(
            parsed=self._parsed,
            result=LLMResult(
                content="",
                model="stub",
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
                latency_ms=self._latency_ms,
                cache_read_tokens=self._cache_read_tokens,
            ),
            outcome=self._outcome,
            attempts=self._attempts,
            error=self._error,
        )
