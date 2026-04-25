from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.im_assist")

PROMPT_VERSION = "2026-04-25.wiki_entry.v2"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "im_assist"


def _load_prompt(version: str = "v1") -> str:
    path = _PROMPT_DIR / f"{version}.md"
    return path.read_text(encoding="utf-8")


Outcome = Literal["ok", "retry", "manual_review"]
SuggestionKind = Literal[
    "none",
    "tag",
    "decision",
    "blocker",
    "wiki_entry",
    # Stage 4 of docs/membrane-reorg.md. The membrane review pipeline
    # creates these directly (NOT the IM-assist agent — the LLM never
    # emits this kind). When MembraneService.review() returns
    # request_review for a candidate, an IMSuggestionRow with this
    # kind is inserted; accept = approve the staged write
    # (KbItemRow status='draft' → 'published'); dismiss = archive.
    "membrane_review",
]
ProposalAction = Literal[
    "drop_deliverable",
    "update_constraint",
    "reassign_task",
    "mark_task_done",
    "open_risk",
    # `save_to_wiki` is the v0 of the membrane "promote into the cell"
    # path — the agent nominates a load-bearing message as a group-scope
    # KB entry; an owner approves through the existing IM suggestion
    # accept/dismiss flow before it joins canonical group context.
    "save_to_wiki",
    # Stage 4 — the membrane reviews a candidate and wants an owner to
    # approve before it joins the cell. The proposal.detail carries
    # `{"candidate_kind": ..., "kb_item_id": ..., "diff_summary": ...,
    #   "conflict_with": [...]}` so the accept handler can flip the
    # staged draft to published.
    "approve_membrane_candidate",
    "other",
]


class IMProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ProposalAction
    summary: str = Field(min_length=1, max_length=240)
    detail: dict[str, Any] = Field(default_factory=dict)


class IMSuggestion(BaseModel):
    """Structured output of the IMAssistAgent.

    `kind` drives UI + eventual graph mutation. `targets` are ids from the
    project's task/deliverable/risk set — the agent never invents ids.
    `proposal` is required for decision/blocker kinds, forbidden for
    none/tag.
    """

    model_config = ConfigDict(extra="forbid")

    kind: SuggestionKind
    confidence: float = Field(ge=0.0, le=1.0)
    targets: list[str] = Field(default_factory=list)
    proposal: IMProposal | None = None
    reasoning: str = Field(default="", max_length=240)


@dataclass(slots=True)
class IMOutcome:
    suggestion: IMSuggestion
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


_MANUAL_REVIEW_FALLBACK = IMSuggestion(
    kind="none",
    confidence=0.0,
    targets=[],
    proposal=None,
    reasoning="im_assist manual review fallback",
)


def _build_user_payload(
    *,
    message: str,
    author: dict,
    project: dict,
    recent_messages: list[dict],
) -> str:
    return json.dumps(
        {
            "message": message,
            "author": author,
            "project": project,
            "recent_messages": recent_messages,
        },
        ensure_ascii=False,
    )


class IMAssistAgent:
    """Classify an IM message as chit-chat / tag / decision / blocker.

    Recovery ladder matches the other phase-3+ agents (2C4):
      1) JSON mode with pydantic validation.
      2) On JSON / schema error: reprompt up to 3 attempts.
      3) After 3 attempts: emit `none`-kind suggestion with
         outcome=manual_review. IM flow is non-blocking: the message is
         still posted.
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
        message: str,
        author: dict,
        project: dict,
        recent_messages: list[dict] | None = None,
    ) -> IMOutcome:
        messages = [
            {"role": "system", "content": self._prompt},
            {
                "role": "user",
                "content": _build_user_payload(
                    message=message,
                    author=author,
                    project=project,
                    recent_messages=recent_messages or [],
                ),
            },
        ]
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=IMSuggestion,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "im_assist failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return IMOutcome(
                suggestion=_MANUAL_REVIEW_FALLBACK,
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

        assert isinstance(parsed, IMSuggestion)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "im_assist classified",
            extra={
                "prompt_version": self.prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "kind": parsed.kind,
                "confidence": parsed.confidence,
                "targets": len(parsed.targets),
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return IMOutcome(
            suggestion=parsed,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )
