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

from workgraph_agents import ParsedRequirement, RequirementAgent
from workgraph_observability import configure_logging

_log = logging.getLogger("workgraph.eval")

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "tests" / "eval" / "dataset"
BASELINES_PATH = REPO_ROOT / "tests" / "eval" / "baselines.json"


@dataclass
class Fixture:
    id: str
    category: str
    input: str
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


# ---------- Runner ---------------------------------------------------------


async def run_requirement(concurrency: int = 2) -> AgentSummary:
    agent = RequirementAgent()
    fixtures = load_fixtures("requirement")

    sem = asyncio.Semaphore(concurrency)

    async def run_one(f: Fixture) -> CaseResult:
        async with sem:
            try:
                parsed, result = await agent.parse(f.input)
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
            failures = score_requirement(parsed, f.expected)
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
                    "failure_count": len(failures),
                    "latency_ms": result.latency_ms,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
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

    if args.agent != "requirement":
        print(f"agent {args.agent!r} not yet supported by runner")
        return 2

    summary = asyncio.run(run_requirement())
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
