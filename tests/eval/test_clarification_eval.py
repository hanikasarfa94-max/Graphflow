"""Pytest wrapper around the clarification eval runner — opt-in via `-m eval`.

Same drift-vs-baseline contract as test_requirement_eval.py: fail if the
new run drops > 5pp compared to the committed clarification baseline.
Phase 4 writes the initial baseline after the first live run.
"""

from __future__ import annotations

import os

import pytest

from tests.eval import runner

MAX_DRIFT = -0.05

skip_if_no_key = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set — eval suite requires live LLM",
)


@pytest.mark.eval
@skip_if_no_key
async def test_clarification_eval_no_regression():
    summary = await runner.run_clarification()
    assert summary.total > 0, "no fixtures loaded"

    failed = [c for c in summary.cases if not c.passed]
    failure_report = "\n".join(
        f"  - {c.fixture_id}: {'; '.join(c.failures)}" for c in failed
    ) or "  (all cases passed)"

    drift = runner.drift_vs_baseline(summary)
    if drift is None:
        pytest.fail(
            "no clarification baseline found. "
            "Run `uv run python -m tests.eval.runner --agent clarification --save-baseline` "
            "and commit the baseline."
        )

    assert drift > MAX_DRIFT, (
        f"regression: pass_rate {summary.pass_rate:.2%} drifted "
        f"{drift:+.2%} vs baseline (threshold {MAX_DRIFT:+.2%})\n"
        f"{summary.passed}/{summary.total} passed\n"
        f"failures:\n{failure_report}"
    )
