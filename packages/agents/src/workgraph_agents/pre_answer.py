"""PreAnswerAgent — Stage 2 of the skill atlas rollout.

The sender's edge asks the target's edge: "given the target's role +
profile skills, what's a first-pass answer to this question?" The sender
sees the pre-answer + confidence + matched skills. If it's enough, they
cancel the route. If not, the original routing still fires and the
pre-answer goes in as a framing hint.

This is the group-layer test for routing: before we interrupt a human,
let their sub-agent draft what they'd probably say. Interruption cost
drops the most when the target is senior (expensive time) or the
question is low-stakes (quick lookup). Both cases are exactly where a
skill-anchored pre-answer earns its keep.

Contract matches the other agents: load prompt, call LLMClient in JSON
mode, fall back to manual-review with a safe payload on repeated parse
failures.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .citations import CitedClaim
from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.pre_answer")

PRE_ANSWER_PROMPT_VERSION = "2026-04-21.stage2.v2"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "edge"


def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


Confidence = Literal["high", "medium", "low"]
Outcome = Literal["ok", "retry", "manual_review"]


class PreAnswerDraft(BaseModel):
    """Structured output of PreAnswerAgent.draft().

    Phase 1.B — `claims` carries structured `{text, citations[]}` so the
    pre-answer's substantive sentences can be chip-linked to graph/KB
    nodes. Empty `claims` tolerated: the service wraps `body` and flags
    the card `uncited` for the UI.
    """

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)
    confidence: Confidence = "low"
    matched_skills: list[str] = Field(default_factory=list, max_length=12)
    uncovered_topics: list[str] = Field(default_factory=list, max_length=6)
    recommend_route: bool = True
    rationale: str = Field(default="", max_length=400)
    claims: list[CitedClaim] = Field(default_factory=list, max_length=8)


_MANUAL_REVIEW_DRAFT = PreAnswerDraft(
    body=(
        "Could not generate a pre-answer automatically. The sender should "
        "route the question directly — the target will see it in their "
        "stream."
    ),
    confidence="low",
    matched_skills=[],
    uncovered_topics=[],
    recommend_route=True,
    rationale="manual_review fallback",
)


@dataclass(slots=True)
class PreAnswerOutcome:
    draft: PreAnswerDraft
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


def _build_payload(
    *,
    question: str,
    target_context: dict[str, Any],
    sender_context: dict[str, Any],
    project_context: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "question": question,
            "target": target_context,
            "sender": sender_context,
            "project": project_context,
        },
        ensure_ascii=False,
        default=str,
    )


class PreAnswerAgent:
    """Target-edge pre-answer drafter.

    Stateless beyond the prompt + LLM client. One instance serves all
    (sender, target) pairs — the target's context is passed in per call.
    """

    prompt_version = PRE_ANSWER_PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        *,
        prompt: str | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._prompt = prompt or _load_prompt("pre_answer_v1")

    async def draft(
        self,
        *,
        question: str,
        target_context: dict[str, Any],
        sender_context: dict[str, Any] | None = None,
        project_context: dict[str, Any] | None = None,
    ) -> PreAnswerOutcome:
        messages = [
            {"role": "system", "content": self._prompt},
            {
                "role": "user",
                "content": _build_payload(
                    question=question,
                    target_context=target_context,
                    sender_context=sender_context or {},
                    project_context=project_context or {},
                ),
            },
        ]
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=PreAnswerDraft,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "pre_answer.draft failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return PreAnswerOutcome(
                draft=_MANUAL_REVIEW_DRAFT,
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

        assert isinstance(parsed, PreAnswerDraft)
        parsed = _sanitize_matched_skills(parsed, target_context)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "pre_answer.drafted",
            extra={
                "prompt_version": self.prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "confidence": parsed.confidence,
                "recommend_route": parsed.recommend_route,
                "matched": len(parsed.matched_skills),
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return PreAnswerOutcome(
            draft=parsed, result=result, outcome=outcome, attempts=attempts
        )


def _sanitize_matched_skills(
    draft: PreAnswerDraft, target_context: dict[str, Any]
) -> PreAnswerDraft:
    """Enforce: matched_skills ⊆ role_skills ∪ declared ∪ validated.

    The prompt states this as a rule but prompts are soft. Drop any
    skill that wasn't actually attributed to the target so the UI
    doesn't display fabricated credentials."""
    allowed: set[str] = set()
    for key in ("role_skills", "declared_abilities", "validated_skills"):
        for s in target_context.get(key, []) or []:
            allowed.add(str(s).strip().lower())
    if not allowed:
        return draft.model_copy(update={"matched_skills": []})
    kept = [s for s in draft.matched_skills if str(s).strip().lower() in allowed]
    if kept == draft.matched_skills:
        return draft
    return draft.model_copy(update={"matched_skills": kept})


__all__ = [
    "PreAnswerAgent",
    "PreAnswerDraft",
    "PreAnswerOutcome",
    "PRE_ANSWER_PROMPT_VERSION",
]
