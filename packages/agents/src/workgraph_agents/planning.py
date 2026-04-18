from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.planning")

PROMPT_VERSION = "2026-04-17.phase6.v1"

_PROMPT_DIR = Path(__file__).parent / "prompts" / "planning"


def _load_prompt(version: str = "v1") -> str:
    path = _PROMPT_DIR / f"{version}.md"
    return path.read_text(encoding="utf-8")


Outcome = Literal["ok", "retry", "manual_review"]

AssigneeRole = Literal[
    "pm", "frontend", "backend", "qa", "design", "business", "approver", "unknown"
]
Severity = Literal["low", "medium", "high"]


class PlannedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str = Field(min_length=1, max_length=16)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=2000)
    deliverable_ref: str | None = None
    assignee_role: AssigneeRole = "unknown"
    estimate_hours: int | None = Field(default=None, ge=0, le=400)
    acceptance_criteria: list[str] = Field(default_factory=list)


class PlannedDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_ref: str = Field(alias="from", min_length=1)
    to_ref: str = Field(alias="to", min_length=1)


class PlannedMilestone(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    target_date: str | None = None
    related_task_refs: list[str] = Field(default_factory=list)


class PlannedRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=1000)
    severity: Severity = "medium"


class ParsedPlan(BaseModel):
    """Structured output of the Planning Agent (Phase 6).

    Validation-layer invariants (cycle / orphan detection) live in the
    PlanningService, not on this model — the schema enforces shape, the
    service enforces graph semantics so error reporting stays observable.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tasks: list[PlannedTask] = Field(default_factory=list)
    dependencies: list[PlannedDependency] = Field(default_factory=list)
    milestones: list[PlannedMilestone] = Field(default_factory=list)
    risks: list[PlannedRisk] = Field(default_factory=list)

    @field_validator("tasks")
    @classmethod
    def _unique_refs(cls, v: list[PlannedTask]) -> list[PlannedTask]:
        refs = [t.ref for t in v]
        if len(refs) != len(set(refs)):
            dupes = sorted({r for r in refs if refs.count(r) > 1})
            raise ValueError(f"duplicate task refs: {dupes}")
        return v


@dataclass(slots=True)
class PlanOutcome:
    plan: ParsedPlan
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


_MANUAL_REVIEW_FALLBACK = ParsedPlan()


def _build_user_payload(
    *,
    goal: str,
    deliverables: list[dict],
    constraints: list[dict],
    existing_risks: list[dict],
) -> str:
    return json.dumps(
        {
            "goal": goal,
            "deliverables": deliverables,
            "constraints": constraints,
            "existing_risks": existing_risks,
        },
        ensure_ascii=False,
    )


class PlanningAgent:
    """Generate a delivery plan from the confirmed requirement graph.

    Recovery ladder matches RequirementAgent / ClarificationAgent (2C4):
      1) JSON mode.
      2) On JSON or schema error: re-prompt with the error (up to 3 attempts).
      3) After 3 attempts: emit empty plan with outcome=manual_review.
    """

    prompt_version = PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        prompt: str | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._prompt = prompt or _load_prompt("v1")

    async def plan(
        self,
        *,
        goal: str,
        deliverables: list[dict],
        constraints: list[dict],
        existing_risks: list[dict] | None = None,
    ) -> PlanOutcome:
        messages = [
            {"role": "system", "content": self._prompt},
            {
                "role": "user",
                "content": _build_user_payload(
                    goal=goal,
                    deliverables=deliverables,
                    constraints=constraints,
                    existing_risks=existing_risks or [],
                ),
            },
        ]
        try:
            plan, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=ParsedPlan,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "planning failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return PlanOutcome(
                plan=_MANUAL_REVIEW_FALLBACK,
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

        assert isinstance(plan, ParsedPlan)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "planning produced",
            extra={
                "prompt_version": self.prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
                "task_count": len(plan.tasks),
                "dependency_count": len(plan.dependencies),
                "milestone_count": len(plan.milestones),
                "risk_count": len(plan.risks),
            },
        )
        return PlanOutcome(
            plan=plan,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )
