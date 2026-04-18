"""Eval runner — per PLAN.md Phase 2.5 (decision 3A).

Loads YAML fixtures from tests/eval/dataset/<agent>/*.yaml, invokes the
agent, scores outputs against constraints, emits structured logs, writes
a JSON summary. Called from pytest (@pytest.mark.eval) and from CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from workgraph_agents import (
    ClarificationAgent,
    ClarificationBatch,
    ConflictExplanation,
    ConflictExplanationAgent,
    IMAssistAgent,
    IMSuggestion,
    ParsedPlan,
    ParsedRequirement,
    PlanningAgent,
    RequirementAgent,
)
from workgraph_observability import configure_logging

_log = logging.getLogger("workgraph.eval")

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "tests" / "eval" / "dataset"
BASELINES_PATH = REPO_ROOT / "tests" / "eval" / "baselines.json"


@dataclass
class Fixture:
    id: str
    category: str
    input: Any  # str for requirement, dict (raw_text + parsed) for clarification
    expected: dict[str, Any]
    notes: str = ""


@dataclass
class CaseResult:
    fixture_id: str
    category: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    parsed: dict[str, Any] | None = None
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class AgentSummary:
    agent: str
    prompt_version: str
    total: int
    passed: int
    pass_rate: float
    cases: list[CaseResult]

    def as_dict(self) -> dict:
        return {
            "agent": self.agent,
            "prompt_version": self.prompt_version,
            "total": self.total,
            "passed": self.passed,
            "pass_rate": self.pass_rate,
            "cases": [asdict(c) for c in self.cases],
        }


def load_fixtures(agent: str) -> list[Fixture]:
    path = DATASET_DIR / agent
    if not path.exists():
        raise FileNotFoundError(f"no fixtures for agent={agent} at {path}")
    fixtures = []
    for f in sorted(path.glob("*.yaml")):
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        fixtures.append(
            Fixture(
                id=raw["id"],
                category=raw.get("category", "unspecified"),
                input=raw["input"],
                expected=raw.get("expected", {}),
                notes=raw.get("notes", ""),
            )
        )
    return fixtures


# ---------- Scoring --------------------------------------------------------


def _contains_any(haystack: str, needles: list[str]) -> bool:
    h = haystack.lower()
    return any(n.lower() in h for n in needles)


def _scope_covers(scope_items: list[str], required_groups: list[list[str]]) -> list[str]:
    """For each group (list of synonyms), at least one scope item must contain one synonym.
    Returns list of groups that are missing.
    """
    missing = []
    for group in required_groups:
        covered = any(
            _contains_any(item, group) for item in scope_items
        )
        if not covered:
            missing.append(group[0])
    return missing


def score_requirement(parsed: ParsedRequirement, expected: dict[str, Any]) -> list[str]:
    """Returns list of failure messages. Empty list == passed."""
    failures: list[str] = []

    if "goal_contains_any" in expected:
        if not _contains_any(parsed.goal, expected["goal_contains_any"]):
            failures.append(
                f"goal missing any of {expected['goal_contains_any']!r}: got {parsed.goal!r}"
            )

    if "min_scope_items" in expected and len(parsed.scope_items) < expected["min_scope_items"]:
        failures.append(
            f"scope_items count {len(parsed.scope_items)} < min {expected['min_scope_items']}"
        )
    if "max_scope_items" in expected and len(parsed.scope_items) > expected["max_scope_items"]:
        failures.append(
            f"scope_items count {len(parsed.scope_items)} > max {expected['max_scope_items']}"
        )

    if "scope_must_mention_any" in expected:
        missing = _scope_covers(parsed.scope_items, expected["scope_must_mention_any"])
        if missing:
            failures.append(f"scope missing coverage for: {missing}")

    if expected.get("deadline_not_null") and parsed.deadline is None:
        failures.append("deadline is null but fixture requires non-null")
    if expected.get("deadline_is_null") and parsed.deadline is not None:
        failures.append(f"deadline={parsed.deadline!r} but fixture requires null")
    if "deadline_contains_any" in expected and parsed.deadline is not None:
        if not _contains_any(parsed.deadline, expected["deadline_contains_any"]):
            failures.append(
                f"deadline {parsed.deadline!r} missing any of {expected['deadline_contains_any']!r}"
            )

    if "min_open_questions" in expected and len(parsed.open_questions) < expected["min_open_questions"]:
        failures.append(
            f"open_questions count {len(parsed.open_questions)} < min {expected['min_open_questions']}"
        )

    if "min_confidence" in expected and parsed.confidence < expected["min_confidence"]:
        failures.append(
            f"confidence {parsed.confidence} < min {expected['min_confidence']}"
        )
    if "max_confidence" in expected and parsed.confidence > expected["max_confidence"]:
        failures.append(
            f"confidence {parsed.confidence} > max {expected['max_confidence']}"
        )

    return failures


def score_planning(plan: ParsedPlan, expected: dict[str, Any], deliverable_ids: set[str]) -> list[str]:
    """Returns list of failure messages. Empty list == passed.

    Evaluates the plan for:
      - task count within [min_tasks, max_tasks]
      - required_mentions: each group is a list of synonyms; at least one
        task title/description must mention one synonym in every group.
      - forbid_cycle: run Kahn's reachability — fail on cycle.
      - every_deliverable_covered: every deliverable id appears on at least
        one task.deliverable_ref (matches PlanValidationError.uncovered_deliverable).
      - critical_path_any_of: for each group, the critical path (longest
        chain by estimate_hours) must mention at least one synonym.
    """
    failures: list[str] = []

    n = len(plan.tasks)
    if "min_tasks" in expected and n < expected["min_tasks"]:
        failures.append(f"task count {n} < min {expected['min_tasks']}")
    if "max_tasks" in expected and n > expected["max_tasks"]:
        failures.append(f"task count {n} > max {expected['max_tasks']}")

    text_corpus = [f"{t.title} {t.description}" for t in plan.tasks]

    if "required_mentions" in expected:
        missing = _scope_covers(text_corpus, expected["required_mentions"])
        if missing:
            failures.append(f"plan missing required mentions: {missing}")

    if expected.get("every_deliverable_covered"):
        covered = {t.deliverable_ref for t in plan.tasks if t.deliverable_ref is not None}
        missing_deliverables = deliverable_ids - covered
        if missing_deliverables:
            failures.append(
                f"deliverables not covered by any task: {sorted(missing_deliverables)}"
            )

    # Cycle detection (Kahn's) — also validates dependency endpoints exist.
    refs = {t.ref for t in plan.tasks}
    adj: dict[str, list[str]] = {ref: [] for ref in refs}
    indeg: dict[str, int] = {ref: 0 for ref in refs}
    dep_ok = True
    for d in plan.dependencies:
        if d.from_ref not in refs or d.to_ref not in refs:
            failures.append(
                f"dependency {d.from_ref} → {d.to_ref} has unknown endpoint"
            )
            dep_ok = False
            continue
        adj[d.from_ref].append(d.to_ref)
        indeg[d.to_ref] += 1
    if expected.get("forbid_cycle", True) and dep_ok:
        queue = [r for r, v in indeg.items() if v == 0]
        visited = 0
        while queue:
            x = queue.pop()
            visited += 1
            for m in adj[x]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)
        if visited != len(refs):
            failures.append("dependencies form a cycle")

    if "critical_path_any_of" in expected and dep_ok:
        path_text = _longest_path_text(plan)
        missing = _scope_covers([path_text], expected["critical_path_any_of"])
        if missing:
            failures.append(f"critical path missing any of: {missing}")

    return failures


def _longest_path_text(plan: ParsedPlan) -> str:
    """Return concatenated title+description of tasks on the longest path by
    estimate_hours. Falls back to task count when estimates are absent.
    """
    refs = {t.ref for t in plan.tasks}
    tasks_by_ref = {t.ref: t for t in plan.tasks}
    adj: dict[str, list[str]] = {ref: [] for ref in refs}
    indeg: dict[str, int] = {ref: 0 for ref in refs}
    for d in plan.dependencies:
        if d.from_ref in refs and d.to_ref in refs:
            adj[d.from_ref].append(d.to_ref)
            indeg[d.to_ref] += 1
    order: list[str] = []
    queue = [r for r, v in indeg.items() if v == 0]
    indeg_copy = dict(indeg)
    while queue:
        x = queue.pop()
        order.append(x)
        for m in adj[x]:
            indeg_copy[m] -= 1
            if indeg_copy[m] == 0:
                queue.append(m)
    if len(order) != len(refs):
        return " ".join(f"{t.title} {t.description}" for t in plan.tasks)

    def weight(ref: str) -> int:
        h = tasks_by_ref[ref].estimate_hours
        return h if h is not None else 1

    dist: dict[str, int] = {r: weight(r) for r in refs}
    prev: dict[str, str | None] = {r: None for r in refs}
    for ref in order:
        for m in adj[ref]:
            if dist[ref] + weight(m) > dist[m]:
                dist[m] = dist[ref] + weight(m)
                prev[m] = ref
    end = max(dist, key=lambda r: dist[r])
    chain: list[str] = []
    cur: str | None = end
    while cur is not None:
        chain.append(cur)
        cur = prev[cur]
    chain.reverse()
    return " ".join(
        f"{tasks_by_ref[r].title} {tasks_by_ref[r].description}" for r in chain
    )


def score_clarification(batch: ClarificationBatch, expected: dict[str, Any]) -> list[str]:
    """Returns list of failure messages. Empty list == passed."""
    failures: list[str] = []

    # Hard cap is enforced at the Pydantic layer, but eval still asserts it.
    if len(batch.questions) > 3:
        failures.append(f"question cap breached: {len(batch.questions)} > 3")

    if "min_questions" in expected and len(batch.questions) < expected["min_questions"]:
        failures.append(
            f"questions {len(batch.questions)} < min {expected['min_questions']}"
        )
    if "max_questions" in expected and len(batch.questions) > expected["max_questions"]:
        failures.append(
            f"questions {len(batch.questions)} > max {expected['max_questions']}"
        )

    joined = " ".join(q.question for q in batch.questions)

    if "any_question_mentions" in expected:
        missing = _scope_covers(
            [q.question for q in batch.questions],
            expected["any_question_mentions"],
        )
        if missing:
            failures.append(f"no question covered: {missing}")

    if expected.get("has_high_blocking"):
        if not any(q.blocking_level == "high" for q in batch.questions):
            failures.append("expected at least one high-blocking question")

    for bad in expected.get("forbid_patterns", []):
        if bad.lower() in joined.lower():
            failures.append(f"forbidden pattern present: {bad!r}")

    return failures


def score_im_assist(suggestion: IMSuggestion, expected: dict[str, Any]) -> list[str]:
    """Returns list of failure messages. Empty list == passed.

    Supported constraints:
      - kind: exact match on suggestion.kind
      - kind_any_of: suggestion.kind ∈ list
      - proposal_is_null: True → proposal must be None
      - proposal_action: exact match on suggestion.proposal.action
      - proposal_action_any_of: suggestion.proposal.action ∈ list
      - proposal_target_any_of: suggestion.proposal.detail values ∩ list ≠ ∅
      - targets_any_of: suggestion.targets ∩ list ≠ ∅
      - min_confidence / max_confidence: numeric bounds
    """
    failures: list[str] = []

    if "kind" in expected and suggestion.kind != expected["kind"]:
        failures.append(
            f"kind {suggestion.kind!r} != expected {expected['kind']!r}"
        )
    if "kind_any_of" in expected and suggestion.kind not in expected["kind_any_of"]:
        failures.append(
            f"kind {suggestion.kind!r} not in {expected['kind_any_of']!r}"
        )

    if expected.get("proposal_is_null") and suggestion.proposal is not None:
        failures.append(
            f"proposal expected null, got action={suggestion.proposal.action!r}"
        )

    if "proposal_action" in expected:
        if suggestion.proposal is None:
            failures.append(
                f"proposal is null but expected action={expected['proposal_action']!r}"
            )
        elif suggestion.proposal.action != expected["proposal_action"]:
            failures.append(
                f"proposal.action {suggestion.proposal.action!r} != expected "
                f"{expected['proposal_action']!r}"
            )

    if "proposal_action_any_of" in expected:
        if suggestion.proposal is None:
            failures.append(
                f"proposal is null but expected action in "
                f"{expected['proposal_action_any_of']!r}"
            )
        elif suggestion.proposal.action not in expected["proposal_action_any_of"]:
            failures.append(
                f"proposal.action {suggestion.proposal.action!r} not in "
                f"{expected['proposal_action_any_of']!r}"
            )

    if "proposal_target_any_of" in expected:
        wanted = set(expected["proposal_target_any_of"])
        detail_values: set[str] = set()
        if suggestion.proposal is not None:
            for v in suggestion.proposal.detail.values():
                if isinstance(v, str):
                    detail_values.add(v)
                elif isinstance(v, list):
                    detail_values.update(
                        x for x in v if isinstance(x, str)
                    )
        # Also accept matches that appear in suggestion.targets as a fallback:
        # the agent may place the target id there rather than in proposal.detail.
        detail_values.update(suggestion.targets)
        if not (detail_values & wanted):
            failures.append(
                f"proposal target missing any of {sorted(wanted)!r} "
                f"(saw detail/targets={sorted(detail_values)!r})"
            )

    if "targets_any_of" in expected:
        wanted = set(expected["targets_any_of"])
        if not (set(suggestion.targets) & wanted):
            failures.append(
                f"targets {suggestion.targets!r} ∩ {sorted(wanted)!r} is empty"
            )

    if "min_confidence" in expected and suggestion.confidence < expected["min_confidence"]:
        failures.append(
            f"confidence {suggestion.confidence} < min {expected['min_confidence']}"
        )
    if "max_confidence" in expected and suggestion.confidence > expected["max_confidence"]:
        failures.append(
            f"confidence {suggestion.confidence} > max {expected['max_confidence']}"
        )

    return failures


def score_conflict_explanation(
    explanation: ConflictExplanation, expected: dict[str, Any]
) -> list[str]:
    """Returns list of failure messages. Empty list == passed.

    Supported constraints:
      - severity_review: exact string
      - severity_review_any_of: list of severities
      - min_options / max_options: integer bounds on options count
      - summary_mentions_any_of: list[list[str]] — per group, summary must
        contain any synonym
      - options_mention_any_of: list[list[str]] — per group, union of all
        option text (label+detail+impact) must contain any synonym
    """
    failures: list[str] = []

    if "severity_review" in expected and explanation.severity_review != expected["severity_review"]:
        failures.append(
            f"severity_review {explanation.severity_review!r} != "
            f"expected {expected['severity_review']!r}"
        )
    if (
        "severity_review_any_of" in expected
        and explanation.severity_review not in expected["severity_review_any_of"]
    ):
        failures.append(
            f"severity_review {explanation.severity_review!r} not in "
            f"{expected['severity_review_any_of']!r}"
        )

    if "min_options" in expected and len(explanation.options) < expected["min_options"]:
        failures.append(
            f"options count {len(explanation.options)} < min {expected['min_options']}"
        )
    if "max_options" in expected and len(explanation.options) > expected["max_options"]:
        failures.append(
            f"options count {len(explanation.options)} > max {expected['max_options']}"
        )

    if "summary_mentions_any_of" in expected:
        missing = _scope_covers(
            [explanation.summary], expected["summary_mentions_any_of"]
        )
        if missing:
            failures.append(f"summary missing coverage for: {missing}")

    if "options_mention_any_of" in expected:
        option_blobs: list[str] = []
        for opt in explanation.options:
            option_blobs.append(f"{opt.label} {opt.detail} {opt.impact}")
        # Treat the full set of options as a single haystack by joining.
        joined = [" ".join(option_blobs)]
        missing = _scope_covers(joined, expected["options_mention_any_of"])
        if missing:
            failures.append(f"options missing coverage for: {missing}")

    return failures


# ---------- Runner ---------------------------------------------------------


async def run_requirement(concurrency: int = 2) -> AgentSummary:
    agent = RequirementAgent()
    fixtures = load_fixtures("requirement")

    sem = asyncio.Semaphore(concurrency)

    async def run_one(f: Fixture) -> CaseResult:
        async with sem:
            try:
                outcome = await agent.parse(f.input)
            except Exception as e:
                _log.exception(
                    "eval case raised",
                    extra={"fixture_id": f.id, "agent": "requirement"},
                )
                return CaseResult(
                    fixture_id=f.id,
                    category=f.category,
                    passed=False,
                    failures=[f"agent raised: {type(e).__name__}: {e}"],
                )
            parsed = outcome.parsed
            result = outcome.result
            failures = score_requirement(parsed, f.expected)
            # A manual_review outcome is always a fail at the eval layer,
            # even if the placeholder happens to satisfy the constraints.
            if outcome.outcome == "manual_review":
                failures.insert(0, f"manual_review after {outcome.attempts} attempts")
            case = CaseResult(
                fixture_id=f.id,
                category=f.category,
                passed=len(failures) == 0,
                failures=failures,
                parsed=parsed.model_dump(),
                latency_ms=result.latency_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
            _log.info(
                "eval case",
                extra={
                    "agent": "requirement",
                    "prompt_version": agent.prompt_version,
                    "fixture_id": f.id,
                    "category": f.category,
                    "passed": case.passed,
                    "outcome": outcome.outcome,
                    "attempts": outcome.attempts,
                    "failure_count": len(failures),
                    "latency_ms": result.latency_ms,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "cache_read_tokens": result.cache_read_tokens,
                },
            )
            return case

    cases = await asyncio.gather(*(run_one(f) for f in fixtures))
    passed = sum(1 for c in cases if c.passed)
    total = len(cases)
    return AgentSummary(
        agent="requirement",
        prompt_version=agent.prompt_version,
        total=total,
        passed=passed,
        pass_rate=(passed / total) if total else 0.0,
        cases=list(cases),
    )


async def run_clarification(concurrency: int = 2) -> AgentSummary:
    agent = ClarificationAgent()
    fixtures = load_fixtures("clarification")

    sem = asyncio.Semaphore(concurrency)

    async def run_one(f: Fixture) -> CaseResult:
        async with sem:
            raw_text = f.input.get("raw_text", "")
            parsed_dict = f.input.get("parsed", {})
            parsed = ParsedRequirement.model_validate(parsed_dict)
            try:
                outcome = await agent.generate(raw_text=raw_text, parsed=parsed)
            except Exception as e:
                _log.exception(
                    "eval case raised",
                    extra={"fixture_id": f.id, "agent": "clarification"},
                )
                return CaseResult(
                    fixture_id=f.id,
                    category=f.category,
                    passed=False,
                    failures=[f"agent raised: {type(e).__name__}: {e}"],
                )
            batch = outcome.batch
            result = outcome.result
            failures = score_clarification(batch, f.expected)
            if outcome.outcome == "manual_review":
                failures.insert(0, f"manual_review after {outcome.attempts} attempts")
            case = CaseResult(
                fixture_id=f.id,
                category=f.category,
                passed=len(failures) == 0,
                failures=failures,
                parsed=batch.model_dump(),
                latency_ms=result.latency_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
            _log.info(
                "eval case",
                extra={
                    "agent": "clarification",
                    "prompt_version": agent.prompt_version,
                    "fixture_id": f.id,
                    "category": f.category,
                    "passed": case.passed,
                    "outcome": outcome.outcome,
                    "attempts": outcome.attempts,
                    "failure_count": len(failures),
                    "latency_ms": result.latency_ms,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "cache_read_tokens": result.cache_read_tokens,
                    "question_count": len(batch.questions),
                },
            )
            return case

    cases = await asyncio.gather(*(run_one(f) for f in fixtures))
    passed = sum(1 for c in cases if c.passed)
    total = len(cases)
    return AgentSummary(
        agent="clarification",
        prompt_version=agent.prompt_version,
        total=total,
        passed=passed,
        pass_rate=(passed / total) if total else 0.0,
        cases=list(cases),
    )


async def run_planning(concurrency: int = 2) -> AgentSummary:
    agent = PlanningAgent()
    fixtures = load_fixtures("planning")

    sem = asyncio.Semaphore(concurrency)

    async def run_one(f: Fixture) -> CaseResult:
        async with sem:
            goal = f.input.get("goal", "")
            deliverables = f.input.get("deliverables", [])
            constraints = f.input.get("constraints", [])
            existing_risks = f.input.get("existing_risks", [])
            try:
                outcome = await agent.plan(
                    goal=goal,
                    deliverables=deliverables,
                    constraints=constraints,
                    existing_risks=existing_risks,
                )
            except Exception as e:
                _log.exception(
                    "eval case raised",
                    extra={"fixture_id": f.id, "agent": "planning"},
                )
                return CaseResult(
                    fixture_id=f.id,
                    category=f.category,
                    passed=False,
                    failures=[f"agent raised: {type(e).__name__}: {e}"],
                )
            plan = outcome.plan
            result = outcome.result
            deliverable_ids = {d["id"] for d in deliverables}
            failures = score_planning(plan, f.expected, deliverable_ids)
            if outcome.outcome == "manual_review":
                failures.insert(0, f"manual_review after {outcome.attempts} attempts")
            case = CaseResult(
                fixture_id=f.id,
                category=f.category,
                passed=len(failures) == 0,
                failures=failures,
                parsed=plan.model_dump(),
                latency_ms=result.latency_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
            _log.info(
                "eval case",
                extra={
                    "agent": "planning",
                    "prompt_version": agent.prompt_version,
                    "fixture_id": f.id,
                    "category": f.category,
                    "passed": case.passed,
                    "outcome": outcome.outcome,
                    "attempts": outcome.attempts,
                    "failure_count": len(failures),
                    "latency_ms": result.latency_ms,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "cache_read_tokens": result.cache_read_tokens,
                    "task_count": len(plan.tasks),
                    "dependency_count": len(plan.dependencies),
                },
            )
            return case

    cases = await asyncio.gather(*(run_one(f) for f in fixtures))
    passed = sum(1 for c in cases if c.passed)
    total = len(cases)
    return AgentSummary(
        agent="planning",
        prompt_version=agent.prompt_version,
        total=total,
        passed=passed,
        pass_rate=(passed / total) if total else 0.0,
        cases=list(cases),
    )


async def run_im_assist(concurrency: int = 2) -> AgentSummary:
    agent = IMAssistAgent()
    fixtures = load_fixtures("im_assist")

    sem = asyncio.Semaphore(concurrency)

    async def run_one(f: Fixture) -> CaseResult:
        async with sem:
            message = f.input.get("message", "")
            author = f.input.get("author", {})
            project = f.input.get("project", {})
            recent_messages = f.input.get("recent_messages", [])
            try:
                outcome = await agent.classify(
                    message=message,
                    author=author,
                    project=project,
                    recent_messages=recent_messages,
                )
            except Exception as e:
                _log.exception(
                    "eval case raised",
                    extra={"fixture_id": f.id, "agent": "im_assist"},
                )
                return CaseResult(
                    fixture_id=f.id,
                    category=f.category,
                    passed=False,
                    failures=[f"agent raised: {type(e).__name__}: {e}"],
                )
            suggestion = outcome.suggestion
            result = outcome.result
            failures = score_im_assist(suggestion, f.expected)
            if outcome.outcome == "manual_review":
                failures.insert(0, f"manual_review after {outcome.attempts} attempts")
            case = CaseResult(
                fixture_id=f.id,
                category=f.category,
                passed=len(failures) == 0,
                failures=failures,
                parsed=suggestion.model_dump(),
                latency_ms=result.latency_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
            _log.info(
                "eval case",
                extra={
                    "agent": "im_assist",
                    "prompt_version": agent.prompt_version,
                    "fixture_id": f.id,
                    "category": f.category,
                    "passed": case.passed,
                    "outcome": outcome.outcome,
                    "attempts": outcome.attempts,
                    "failure_count": len(failures),
                    "latency_ms": result.latency_ms,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "cache_read_tokens": result.cache_read_tokens,
                    "kind": suggestion.kind,
                    "confidence": suggestion.confidence,
                },
            )
            return case

    cases = await asyncio.gather(*(run_one(f) for f in fixtures))
    passed = sum(1 for c in cases if c.passed)
    total = len(cases)
    return AgentSummary(
        agent="im_assist",
        prompt_version=agent.prompt_version,
        total=total,
        passed=passed,
        pass_rate=(passed / total) if total else 0.0,
        cases=list(cases),
    )


async def run_conflict_explanation(concurrency: int = 2) -> AgentSummary:
    agent = ConflictExplanationAgent()
    fixtures = load_fixtures("conflict_explanation")

    sem = asyncio.Semaphore(concurrency)

    async def run_one(f: Fixture) -> CaseResult:
        async with sem:
            rule = f.input.get("rule", "")
            severity = f.input.get("severity", "medium")
            detail = f.input.get("detail", {})
            project = f.input.get("project", {})
            targets = f.input.get("targets", [])
            try:
                outcome = await agent.explain(
                    rule=rule,
                    severity=severity,
                    detail=detail,
                    project=project,
                    targets=targets,
                )
            except Exception as e:
                _log.exception(
                    "eval case raised",
                    extra={"fixture_id": f.id, "agent": "conflict_explanation"},
                )
                return CaseResult(
                    fixture_id=f.id,
                    category=f.category,
                    passed=False,
                    failures=[f"agent raised: {type(e).__name__}: {e}"],
                )
            explanation = outcome.explanation
            result = outcome.result
            failures = score_conflict_explanation(explanation, f.expected)
            if outcome.outcome == "manual_review":
                failures.insert(0, f"manual_review after {outcome.attempts} attempts")
            case = CaseResult(
                fixture_id=f.id,
                category=f.category,
                passed=len(failures) == 0,
                failures=failures,
                parsed=explanation.model_dump(),
                latency_ms=result.latency_ms,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
            )
            _log.info(
                "eval case",
                extra={
                    "agent": "conflict_explanation",
                    "prompt_version": agent.prompt_version,
                    "fixture_id": f.id,
                    "category": f.category,
                    "passed": case.passed,
                    "outcome": outcome.outcome,
                    "attempts": outcome.attempts,
                    "failure_count": len(failures),
                    "latency_ms": result.latency_ms,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "cache_read_tokens": result.cache_read_tokens,
                    "severity_review": explanation.severity_review,
                    "options": len(explanation.options),
                },
            )
            return case

    cases = await asyncio.gather(*(run_one(f) for f in fixtures))
    passed = sum(1 for c in cases if c.passed)
    total = len(cases)
    return AgentSummary(
        agent="conflict_explanation",
        prompt_version=agent.prompt_version,
        total=total,
        passed=passed,
        pass_rate=(passed / total) if total else 0.0,
        cases=list(cases),
    )


# ---------- Drift + baselines ---------------------------------------------


def load_baselines() -> dict:
    if BASELINES_PATH.exists():
        return json.loads(BASELINES_PATH.read_text(encoding="utf-8"))
    return {}


def save_baseline(summary: AgentSummary) -> None:
    data = load_baselines()
    data[summary.agent] = {
        "prompt_version": summary.prompt_version,
        "pass_rate": summary.pass_rate,
        "total": summary.total,
    }
    BASELINES_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def drift_vs_baseline(summary: AgentSummary) -> float | None:
    data = load_baselines()
    prior = data.get(summary.agent)
    if not prior:
        return None
    return summary.pass_rate - prior["pass_rate"]


# ---------- CLI ------------------------------------------------------------


def _cli() -> int:
    parser = argparse.ArgumentParser(description="WorkGraph eval runner")
    parser.add_argument("--agent", default="requirement")
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument(
        "--fail-under",
        type=float,
        default=0.80,
        help="minimum absolute pass rate",
    )
    parser.add_argument(
        "--fail-drift",
        type=float,
        default=-0.05,
        help="fail if drift vs baseline <= this (e.g. -0.05 for 5pp drop)",
    )
    args = parser.parse_args()
    configure_logging(os.environ.get("WORKGRAPH_LOG_LEVEL", "INFO"))

    if args.agent == "requirement":
        summary = asyncio.run(run_requirement())
    elif args.agent == "clarification":
        summary = asyncio.run(run_clarification())
    elif args.agent == "planning":
        summary = asyncio.run(run_planning())
    elif args.agent == "im_assist":
        summary = asyncio.run(run_im_assist())
    elif args.agent == "conflict_explanation":
        summary = asyncio.run(run_conflict_explanation())
    else:
        print(f"agent {args.agent!r} not yet supported by runner")
        return 2

    drift = drift_vs_baseline(summary)

    result = {
        "agent": summary.agent,
        "prompt_version": summary.prompt_version,
        "total": summary.total,
        "passed": summary.passed,
        "pass_rate": round(summary.pass_rate, 4),
        "drift_vs_baseline": round(drift, 4) if drift is not None else None,
        "failures": [
            {"id": c.fixture_id, "failures": c.failures}
            for c in summary.cases
            if not c.passed
        ],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.save_baseline:
        save_baseline(summary)
        print(f"baseline saved to {BASELINES_PATH}")

    gate_failed = False
    if summary.pass_rate < args.fail_under:
        print(f"FAIL: pass_rate {summary.pass_rate:.2%} < {args.fail_under:.2%}")
        gate_failed = True
    if drift is not None and drift <= args.fail_drift:
        print(f"FAIL: drift {drift:+.2%} <= threshold {args.fail_drift:+.2%}")
        gate_failed = True

    return 1 if gate_failed else 0


if __name__ == "__main__":
    raise SystemExit(_cli())
