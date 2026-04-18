"""Conflict-Explanation agent — Phase 8 (decisions 2C3, 2C4, 3A, 4A).

Takes a rule-engine match + project context, returns a PM-ready summary +
2–3 resolution options with trade-offs. Recovery ladder matches the other
agents: JSON mode → reprompt on bad output up to 3 attempts → deterministic
manual_review fallback so the UI can show the raw rule while flagging the
LLM miss.

Prompt caching is enabled via the standard LLMClient (the prompt body is
static; rule detail changes per call). Cache hit tokens appear in the
agent_run_log so dashboards can track p50 warm latency.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.conflict_explanation")

PROMPT_VERSION = "2026-04-17.phase8.v1"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "conflict_explanation"


def _load_prompt(version: str = "v1") -> str:
    return (_PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")


Outcome = Literal["ok", "retry", "manual_review"]
Severity = Literal["low", "medium", "high", "critical"]


class ConflictOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=320)
    impact: str = Field(min_length=1, max_length=280)


class ConflictExplanation(BaseModel):
    """Structured output of the ConflictExplanation agent.

    `severity_review` is the LLM's calibration of the rule's severity; the
    service keeps both for drift analysis but persists severity_review on
    the ConflictRow (rule severity is still in `detail`).
    """

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=320)
    severity_review: Severity
    options: list[ConflictOption] = Field(min_length=2, max_length=4)


@dataclass(slots=True)
class ExplanationOutcome:
    explanation: ConflictExplanation
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


def _manual_review_fallback(rule: str, severity: Severity) -> ConflictExplanation:
    """Deterministic fallback when the LLM can't produce a valid structure.

    The UI renders this with a "manual review" chip so the PM knows the
    agent bailed — they still see the conflict and can act, just without
    generated options.
    """
    return ConflictExplanation(
        summary=(
            f"A {severity} '{rule.replace('_', ' ')}' conflict was detected "
            "but auto-explanation failed. Review the raw rule detail below "
            "and decide next steps manually."
        ),
        severity_review=severity,
        options=[
            ConflictOption(
                label="Review manually",
                detail="Open the conflict detail, inspect the targets, and decide.",
                impact="The auto-generated option set is unavailable for this conflict.",
            ),
            ConflictOption(
                label="Dismiss if false positive",
                detail="If the rule over-fired on benign state, dismiss to clear the list.",
                impact="Dismissed conflicts do not re-open until the fingerprint changes.",
            ),
        ],
    )


def _build_user_payload(
    *,
    rule: str,
    severity: Severity,
    detail: dict[str, Any],
    project: dict[str, Any],
    targets: list[str],
) -> str:
    return json.dumps(
        {
            "rule": rule,
            "severity": severity,
            "detail": detail,
            "project": project,
            "targets": targets,
        },
        ensure_ascii=False,
    )


class ConflictExplanationAgent:
    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt: str | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._prompt = prompt or _load_prompt("v1")

    async def explain(
        self,
        *,
        rule: str,
        severity: Severity,
        detail: dict[str, Any],
        project: dict[str, Any],
        targets: list[str],
    ) -> ExplanationOutcome:
        messages = [
            {"role": "system", "content": self._prompt},
            {
                "role": "user",
                "content": _build_user_payload(
                    rule=rule,
                    severity=severity,
                    detail=detail,
                    project=project,
                    targets=targets,
                ),
            },
        ]
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=ConflictExplanation,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "conflict_explanation failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "rule": rule,
                    "severity": severity,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return ExplanationOutcome(
                explanation=_manual_review_fallback(rule, severity),
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

        assert isinstance(parsed, ConflictExplanation)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "conflict_explanation ok",
            extra={
                "prompt_version": self.prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "rule": rule,
                "severity": severity,
                "severity_review": parsed.severity_review,
                "options": len(parsed.options),
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return ExplanationOutcome(
            explanation=parsed,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )
