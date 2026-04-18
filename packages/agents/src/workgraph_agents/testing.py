"""Test-only stubs. Import only from tests/conftest; never from prod code."""

from __future__ import annotations

from typing import Literal

from .clarification import (
    ClarificationBatch,
    ClarificationOutcome,
    ClarificationQuestionItem,
)
from .conflict_explanation import (
    ConflictExplanation,
    ConflictOption,
    ExplanationOutcome,
)
from .delivery import (
    CompletedScopeItem,
    DeferredScopeItem,
    DeliveryEvidence,
    DeliveryOutcome,
    DeliverySummaryDoc,
    KeyDecision,
    RemainingRisk,
)
from .im_assist import IMOutcome, IMProposal, IMSuggestion
from .llm import LLMResult
from .planning import (
    ParsedPlan,
    PlanOutcome,
    PlannedDependency,
    PlannedMilestone,
    PlannedRisk,
    PlannedTask,
)
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


_DEFAULT_QUESTIONS = [
    ClarificationQuestionItem(
        question="Who is the approver for launch readiness?",
        target_role="approver",
        blocking_level="high",
        reason="stub",
    ),
    ClarificationQuestionItem(
        question="What are the acceptance criteria for the export feature?",
        target_role="pm",
        blocking_level="medium",
        reason="stub",
    ),
]


class StubClarificationAgent:
    """Deterministic stand-in for ClarificationAgent — no network calls."""

    prompt_version = "stub.clarification.v1"

    def __init__(
        self,
        questions: list[ClarificationQuestionItem] | None = None,
        outcome: Literal["ok", "retry", "manual_review"] = "ok",
        attempts: int = 1,
        latency_ms: int = 5,
        prompt_tokens: int = 200,
        completion_tokens: int = 80,
        cache_read_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        self._questions = questions if questions is not None else _DEFAULT_QUESTIONS
        self._outcome = outcome
        self._attempts = attempts
        self._latency_ms = latency_ms
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._cache_read_tokens = cache_read_tokens
        self._error = error
        self.calls: list[dict] = []

    async def generate(
        self, *, raw_text: str, parsed: ParsedRequirement
    ) -> ClarificationOutcome:
        self.calls.append({"raw_text": raw_text, "parsed": parsed})
        return ClarificationOutcome(
            batch=ClarificationBatch(questions=list(self._questions)),
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


def _default_plan_for(deliverables: list[dict]) -> ParsedPlan:
    """Build a stub plan that covers every provided deliverable + an OTP task.

    The StubRequirementAgent default yields two deliverables ("stub item 1/2").
    Canonical-E2E live tests use a different agent. For unit tests we just
    need deterministic shape: 1 task per deliverable + a cross-cutting
    "configure OTP service" task so the task count is ≥3 even when a
    requirement produces only two deliverables.
    """
    tasks: list[PlannedTask] = []
    for idx, d in enumerate(deliverables, start=1):
        tasks.append(
            PlannedTask(
                ref=f"T{idx}",
                title=f"Build {d['title']}",
                description="Stub task",
                deliverable_ref=d["id"],
                assignee_role="backend" if idx % 2 == 0 else "frontend",
                estimate_hours=4,
                acceptance_criteria=["stub criterion"],
            )
        )
    tasks.append(
        PlannedTask(
            ref=f"T{len(deliverables) + 1}",
            title="Configure OTP service",
            description="Cross-cutting task covering auth setup",
            deliverable_ref=None,
            assignee_role="backend",
            estimate_hours=6,
            acceptance_criteria=["otp service returns tokens"],
        )
    )
    deps: list[PlannedDependency] = []
    # Simple chain: T1 → T2 → ... → OTP. Avoids cycles, keeps a critical path.
    for i in range(len(tasks) - 1):
        deps.append(
            PlannedDependency.model_validate(
                {"from": tasks[i].ref, "to": tasks[i + 1].ref}
            )
        )
    milestones = [
        PlannedMilestone(
            title="Internal preview",
            target_date=None,
            related_task_refs=[t.ref for t in tasks[:-1]],
        )
    ]
    return ParsedPlan(
        tasks=tasks,
        dependencies=deps,
        milestones=milestones,
        risks=[PlannedRisk(title="Stub risk", content="for tests", severity="low")],
    )


class StubPlanningAgent:
    """Deterministic stand-in for PlanningAgent — no network calls.

    If no explicit plan is supplied, the agent synthesizes one from the
    deliverables it sees at call time (1 task per deliverable + an OTP task).
    This keeps canonical-flow unit tests meaningful even when the fixture
    does not pre-build a plan.
    """

    prompt_version = "stub.planning.v1"

    def __init__(
        self,
        plan: ParsedPlan | None = None,
        outcome: Literal["ok", "retry", "manual_review"] = "ok",
        attempts: int = 1,
        latency_ms: int = 5,
        prompt_tokens: int = 300,
        completion_tokens: int = 120,
        cache_read_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        self._plan = plan
        self._outcome = outcome
        self._attempts = attempts
        self._latency_ms = latency_ms
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._cache_read_tokens = cache_read_tokens
        self._error = error
        self.calls: list[dict] = []

    async def plan(
        self,
        *,
        goal: str,
        deliverables: list[dict],
        constraints: list[dict],
        existing_risks: list[dict] | None = None,
    ) -> PlanOutcome:
        self.calls.append(
            {
                "goal": goal,
                "deliverables": deliverables,
                "constraints": constraints,
                "existing_risks": existing_risks or [],
            }
        )
        plan = self._plan if self._plan is not None else _default_plan_for(deliverables)
        return PlanOutcome(
            plan=plan,
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


def _classify_stub(message: str, project: dict) -> IMSuggestion:
    """Keyword-based classification used when no explicit suggestion is set.

    Heuristics are intentionally narrow — tests that care about specific
    classifications pass an explicit `suggestion` to the stub constructor.
    """
    body = (message or "").strip().lower()
    if len(body) < 5:
        return IMSuggestion(
            kind="none", confidence=0.9, reasoning="stub: too short"
        )

    deliverables = project.get("deliverables") if isinstance(project, dict) else []
    tasks = project.get("tasks") if isinstance(project, dict) else []
    first_del_id = deliverables[0]["id"] if deliverables else None
    first_task_id = tasks[0]["id"] if tasks else None

    if any(k in body for k in ("blocked", "blocker", "stuck", "can't")):
        return IMSuggestion(
            kind="blocker",
            confidence=0.85,
            targets=[first_task_id] if first_task_id else [],
            proposal=IMProposal(
                action="open_risk",
                summary="Stub blocker",
                detail={"title": message[:80] or "blocker", "severity": "medium"},
            ),
            reasoning="stub: blocker keyword",
        )
    if any(k in body for k in ("cut ", "drop ", "defer", "skip the")):
        return IMSuggestion(
            kind="decision",
            confidence=0.8,
            targets=[first_del_id] if first_del_id else [],
            proposal=IMProposal(
                action="drop_deliverable",
                summary="Stub scope cut",
                detail={"deliverable_id": first_del_id or "stub-del"},
            ),
            reasoning="stub: scope cut keyword",
        )
    if "?" in body and (tasks or deliverables):
        targets = [first_task_id] if first_task_id else ([first_del_id] if first_del_id else [])
        return IMSuggestion(
            kind="tag",
            confidence=0.7,
            targets=targets,
            reasoning="stub: question about known entity",
        )
    return IMSuggestion(kind="none", confidence=0.6, reasoning="stub: default none")


class StubIMAssistAgent:
    """Deterministic stand-in for IMAssistAgent — no network calls.

    If a `suggestion` is passed at construction time, it is returned for
    every call. Otherwise the stub applies a tiny keyword heuristic that
    lets the intake/UI plumbing be tested without pinning arbitrary
    message strings to arbitrary classifications.
    """

    prompt_version = "stub.im_assist.v1"

    def __init__(
        self,
        suggestion: IMSuggestion | None = None,
        outcome: Literal["ok", "retry", "manual_review"] = "ok",
        attempts: int = 1,
        latency_ms: int = 5,
        prompt_tokens: int = 150,
        completion_tokens: int = 60,
        cache_read_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        self._suggestion = suggestion
        self._outcome = outcome
        self._attempts = attempts
        self._latency_ms = latency_ms
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._cache_read_tokens = cache_read_tokens
        self._error = error
        self.calls: list[dict] = []

    async def classify(
        self,
        *,
        message: str,
        author: dict,
        project: dict,
        recent_messages: list[dict] | None = None,
    ) -> IMOutcome:
        self.calls.append(
            {
                "message": message,
                "author": author,
                "project": project,
                "recent_messages": list(recent_messages or []),
            }
        )
        suggestion = (
            self._suggestion
            if self._suggestion is not None
            else _classify_stub(message, project)
        )
        return IMOutcome(
            suggestion=suggestion,
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


class StubConflictExplanationAgent:
    """Deterministic stand-in for ConflictExplanationAgent — no network.

    Always returns a 2-option explanation whose severity_review matches the
    rule severity. Tests that need specific wording can pass a custom
    explanation at construction time.
    """

    prompt_version = "stub.conflict_explanation.v1"

    def __init__(
        self,
        explanation: ConflictExplanation | None = None,
        outcome: Literal["ok", "retry", "manual_review"] = "ok",
        attempts: int = 1,
        latency_ms: int = 3,
        prompt_tokens: int = 120,
        completion_tokens: int = 90,
        cache_read_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        self._explanation = explanation
        self._outcome = outcome
        self._attempts = attempts
        self._latency_ms = latency_ms
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._cache_read_tokens = cache_read_tokens
        self._error = error
        self.calls: list[dict] = []

    async def explain(
        self,
        *,
        rule: str,
        severity: str,
        detail: dict,
        project: dict,
        targets: list[str],
    ) -> ExplanationOutcome:
        self.calls.append(
            {
                "rule": rule,
                "severity": severity,
                "detail": dict(detail),
                "project": project,
                "targets": list(targets),
            }
        )
        explanation = self._explanation or ConflictExplanation(
            summary=f"Stub summary for {rule} ({severity}).",
            severity_review=severity if severity in {"low", "medium", "high", "critical"} else "medium",
            options=[
                ConflictOption(
                    label="Acknowledge",
                    detail="Mark the conflict as seen; no graph change.",
                    impact="No changes to scope, ownership, or deadline.",
                ),
                ConflictOption(
                    label="Escalate",
                    detail="Route to the project owner for decision.",
                    impact="Unblocks by forcing a human call; adds one day of delay.",
                ),
            ],
        )
        return ExplanationOutcome(
            explanation=explanation,
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


class StubDeliveryAgent:
    """Deterministic stand-in for DeliveryAgent — no network.

    Synthesizes a summary from the inputs: every scope_item in
    `covered_refs` becomes a completed entry citing those task ids,
    the rest become deferred. Key decisions mirror the input decision
    list. Risks pass through from the graph. The narrative names the
    goal and counts so the QA pre-check + UI have real strings to
    assert on.
    """

    prompt_version = "stub.delivery.v1"

    def __init__(
        self,
        doc: DeliverySummaryDoc | None = None,
        outcome: Literal["ok", "retry", "manual_review"] = "ok",
        attempts: int = 1,
        latency_ms: int = 4,
        prompt_tokens: int = 400,
        completion_tokens: int = 200,
        cache_read_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        self._doc = doc
        self._outcome = outcome
        self._attempts = attempts
        self._latency_ms = latency_ms
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens
        self._cache_read_tokens = cache_read_tokens
        self._error = error
        self.calls: list[dict] = []

    async def generate(
        self,
        *,
        requirement: dict,
        graph: dict,
        plan: dict,
        assignments: list[dict],
        decisions: list[dict],
        conflicts: list[dict],
        covered_refs: dict[str, list[str]] | None = None,
    ) -> DeliveryOutcome:
        self.calls.append(
            {
                "requirement": requirement,
                "graph": graph,
                "plan": plan,
                "assignments": assignments,
                "decisions": decisions,
                "conflicts": conflicts,
                "covered_refs": covered_refs,
            }
        )
        doc = self._doc or _default_delivery_doc(
            requirement=requirement,
            graph=graph,
            plan=plan,
            assignments=assignments,
            decisions=decisions,
            conflicts=conflicts,
            covered_refs=covered_refs or {},
        )
        return DeliveryOutcome(
            doc=doc,
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


def _default_delivery_doc(
    *,
    requirement: dict,
    graph: dict,
    plan: dict,
    assignments: list[dict],
    decisions: list[dict],
    conflicts: list[dict],
    covered_refs: dict[str, list[str]],
) -> DeliverySummaryDoc:
    scope_items: list[str] = list(requirement.get("scope_items") or [])
    completed: list[CompletedScopeItem] = []
    deferred: list[DeferredScopeItem] = []
    deferred_by_item: dict[str, str] = {}
    for d in decisions:
        text = d.get("custom_text") or ""
        if text and ("defer" in text.lower() or "cut" in text.lower()):
            for item in scope_items:
                if item.lower() in text.lower():
                    deferred_by_item[item] = d.get("id") or ""
    for item in scope_items:
        task_ids = covered_refs.get(item, [])
        if task_ids and item not in deferred_by_item:
            completed.append(
                CompletedScopeItem(scope_item=item, evidence_task_ids=task_ids)
            )
        else:
            deferred.append(
                DeferredScopeItem(
                    scope_item=item,
                    reason=(
                        "Deferred per team decision."
                        if item in deferred_by_item
                        else "No task covers this scope item yet."
                    ),
                    decision_id=deferred_by_item.get(item) or None,
                )
            )
    key_decisions = [
        KeyDecision(
            decision_id=d["id"],
            headline=(
                f"Chose option {d['option_index'] + 1}"
                if d.get("option_index") is not None
                else (d.get("custom_text") or "Custom resolution")[:160]
            ),
            rationale=(d.get("rationale") or "")[:500],
        )
        for d in decisions
        if d.get("id")
    ]
    remaining_risks = [
        RemainingRisk(
            title=r.get("title") or "risk",
            content=r.get("content") or "",
            severity=(
                r.get("severity")
                if r.get("severity") in ("low", "medium", "high")
                else "medium"
            ),
        )
        for r in (graph.get("risks") or [])
    ]
    milestones_ids = [m.get("id") for m in (plan.get("milestones") or []) if m.get("id")]
    resolved_conflict_ids = [
        c.get("id")
        for c in conflicts
        if c.get("status") == "resolved" and c.get("id")
    ]
    assigned_task_ids = [a.get("task_id") for a in assignments if a.get("task_id")]
    goal = requirement.get("goal") or "the project"
    narrative = (
        f"{goal}. "
        f"Completed {len(completed)} of {len(scope_items)} scope items; "
        f"{len(deferred)} deferred. "
        f"{len(key_decisions)} key decisions recorded."
    )
    headline = (
        f"Shipped {len(completed)}/{len(scope_items)} scope items for {goal}."
    )
    return DeliverySummaryDoc(
        headline=headline,
        narrative=narrative,
        completed_scope=completed,
        deferred_scope=deferred,
        key_decisions=key_decisions,
        remaining_risks=remaining_risks,
        evidence=DeliveryEvidence(
            milestones=milestones_ids,
            conflicts_resolved=resolved_conflict_ids,
            assignments=assigned_task_ids,
        ),
    )
