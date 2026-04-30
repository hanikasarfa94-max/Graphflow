"""Delivery agent — Phase 10 (decisions 2C3, 2C4, 3A, 4A).

Takes the full project state (requirement + graph + plan + decisions +
conflicts + assignments) and produces a structured delivery summary.
Recovery ladder matches the other agents: JSON mode → reprompt on bad
output up to 3 attempts → deterministic manual_review fallback.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.delivery")

PROMPT_VERSION = "2026-04-26.phase10.v2"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "delivery"


def _load_prompt(version: str = "v1") -> str:
    return (_PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")


Outcome = Literal["ok", "retry", "manual_review"]
Severity = Literal["low", "medium", "high"]


class CompletedScopeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_item: str = Field(min_length=1, max_length=500)
    evidence_task_ids: list[str] = Field(default_factory=list)


class DeferredScopeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_item: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    decision_id: str | None = None


class KeyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    headline: str = Field(min_length=1, max_length=200)
    rationale: str = Field(default="", max_length=500)


class RemainingRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=500)
    severity: Severity = "medium"


class DeliveryEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milestones: list[str] = Field(default_factory=list)
    conflicts_resolved: list[str] = Field(default_factory=list)
    assignments: list[str] = Field(default_factory=list)


class DeliverySummaryDoc(BaseModel):
    """Structured output of the Delivery agent."""

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1, max_length=240)
    narrative: str = Field(default="", max_length=4000)
    completed_scope: list[CompletedScopeItem] = Field(default_factory=list)
    deferred_scope: list[DeferredScopeItem] = Field(default_factory=list)
    key_decisions: list[KeyDecision] = Field(default_factory=list)
    remaining_risks: list[RemainingRisk] = Field(default_factory=list)
    evidence: DeliveryEvidence = Field(default_factory=DeliveryEvidence)


@dataclass(slots=True)
class DeliveryOutcome:
    doc: DeliverySummaryDoc
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


def _manual_review_fallback(
    *, scope_items: list[str], covered_refs: dict[str, list[str]]
) -> DeliverySummaryDoc:
    """Deterministic fallback so the UI always has something to render.

    Split scope_items into covered/uncovered based on the graph → task
    mapping we already computed in the service's QA pre-check. Caller
    passes it in so the fallback text matches the pre-check verdict.
    """
    completed = [
        CompletedScopeItem(
            scope_item=item, evidence_task_ids=covered_refs.get(item, [])
        )
        for item in scope_items
        if covered_refs.get(item)
    ]
    deferred = [
        DeferredScopeItem(
            scope_item=item,
            reason="No task covers this scope item yet. Review required.",
        )
        for item in scope_items
        if not covered_refs.get(item)
    ]
    return DeliverySummaryDoc(
        headline="Delivery summary generation needs manual review.",
        narrative=(
            "The delivery agent could not produce a valid structured "
            "summary. Review the scope coverage below and write the "
            "narrative manually."
        ),
        completed_scope=completed,
        deferred_scope=deferred,
    )


def _build_user_payload(
    *,
    requirement: dict[str, Any],
    graph: dict[str, Any],
    plan: dict[str, Any],
    assignments: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    covered_refs: dict[str, list[str]],
) -> str:
    # `covered_refs` is the service-side authoritative scope→task mapping
    # (computed by _build_coverage_map in the delivery service). The
    # prompt v2 instructs the LLM to treat it as the source of truth for
    # the completed/deferred split — the LLM only writes the narrative
    # and decision rationale. v1 had the LLM re-derive coverage from the
    # graph, which occasionally returned semantically-empty output that
    # passed Pydantic but violated the prompt contract.
    return json.dumps(
        {
            "requirement": requirement,
            "graph": graph,
            "plan": plan,
            "assignments": assignments,
            "decisions": decisions,
            "conflicts": conflicts,
            "covered_refs": covered_refs,
        },
        ensure_ascii=False,
    )


class DeliveryAgent:
    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt: str | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._prompt = prompt or _load_prompt("v2")

    async def generate(
        self,
        *,
        requirement: dict[str, Any],
        graph: dict[str, Any],
        plan: dict[str, Any],
        assignments: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        conflicts: list[dict[str, Any]],
        covered_refs: dict[str, list[str]] | None = None,
    ) -> DeliveryOutcome:
        coverage = covered_refs or {}
        messages = [
            {"role": "system", "content": self._prompt},
            {
                "role": "user",
                "content": _build_user_payload(
                    requirement=requirement,
                    graph=graph,
                    plan=plan,
                    assignments=assignments,
                    decisions=decisions,
                    conflicts=conflicts,
                    covered_refs=coverage,
                ),
            },
        ]
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=DeliverySummaryDoc,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "delivery failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            scope_items = requirement.get("scope_items") or []
            return DeliveryOutcome(
                doc=_manual_review_fallback(
                    scope_items=list(scope_items),
                    covered_refs=covered_refs or {},
                ),
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

        assert isinstance(parsed, DeliverySummaryDoc)

        # Semantic contract enforcement (the prompt's "Hard rules" §2):
        # the union of completed_scope + deferred_scope MUST equal the
        # requirement's scope_items. Pydantic only validates structure;
        # this rule is semantic, so we check it post-parse.
        #
        # Why this matters in practice: the LLM was being asked to do
        # two jobs in one call — (a) deterministic mapping of scope
        # items to tasks (which the service layer already does via
        # _build_coverage_map), and (b) write the narrative. We
        # observed the LLM occasionally dropping all scope items into
        # neither bucket on early-stage projects (no tasks marked
        # done yet), producing semantically-empty output that passed
        # Pydantic but violated the prompt contract. Reproducer:
        # call POST /api/demo/seed twice on the same source_event_id
        # — the FIRST call's project state hasn't been re-summarized
        # yet, and the LLM occasionally returns both arrays empty.
        # The SECOND call (same project, more history in the prompt)
        # gets it right.
        #
        # Fix: when the LLM violates the contract, fall back to the
        # deterministic _manual_review_fallback which uses the
        # service-computed `covered_refs` map as the source of truth.
        # This anchors the agent on the same scope→task matching the
        # service already trusts for QA, so we can't drift into
        # silent-empty-output failures. Log + return outcome=
        # 'manual_review' so the QA pipeline downstream (and the
        # delivery_summaries.parse_outcome column) flag the row as
        # needing a human pass.
        scope_items = list(requirement.get("scope_items") or [])
        if scope_items:
            doc_items = {c.scope_item for c in parsed.completed_scope} | {
                d.scope_item for d in parsed.deferred_scope
            }
            expected = set(scope_items)
            if doc_items != expected:
                _log.warning(
                    "delivery: scope contract violation — falling back to coverage map",
                    extra={
                        "prompt_version": self.prompt_version,
                        "expected_scope": sorted(expected),
                        "got_scope": sorted(doc_items),
                        "missing": sorted(expected - doc_items),
                        "extra": sorted(doc_items - expected),
                    },
                )
                return DeliveryOutcome(
                    doc=_manual_review_fallback(
                        scope_items=scope_items,
                        covered_refs=covered_refs or {},
                    ),
                    result=result,
                    outcome="manual_review",
                    attempts=attempts,
                    error="scope_contract_violation",
                )

        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "delivery ok",
            extra={
                "prompt_version": self.prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "completed_scope": len(parsed.completed_scope),
                "deferred_scope": len(parsed.deferred_scope),
                "key_decisions": len(parsed.key_decisions),
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return DeliveryOutcome(
            doc=parsed,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )


__all__ = [
    "DeliveryAgent",
    "DeliveryOutcome",
    "DeliverySummaryDoc",
    "CompletedScopeItem",
    "DeferredScopeItem",
    "KeyDecision",
    "RemainingRisk",
    "DeliveryEvidence",
    "PROMPT_VERSION",
]
