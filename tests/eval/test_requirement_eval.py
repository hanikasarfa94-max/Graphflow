"""Pytest wrapper around the eval runner — opt-in via `-m eval`.

Regular `uv run pytest` excludes this (see pyproject addopts). CI runs
`uv run pytest -m eval` with DEEPSEEK_API_KEY set.

Gate: no more than MAX_DRIFT regression vs the committed baseline.
Phase 2.5 sets the baseline from the minimal prompt; Phase 3 raises it.
The baseline file lives at tests/eval/baselines.json.
"""

from __future__ import annotations

import os

import pytest

from tests.eval import runner

MAX_DRIFT = -0.05  # fail if pass_rate - baseline <= this (5pp drop)

skip_if_no_key = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set — eval suite requires live LLM",
)


@pytest.mark.eval
@skip_if_no_key
async def test_requirement_eval_no_regression():
    summary = await runner.run_requirement()
    assert summary.total > 0, "no fixtures loaded"

    failed = [c for c in summary.cases if not c.passed]
    failure_report = "\n".join(
        f"  - {c.fixture_id}: {'; '.join(c.failures)}" for c in failed
    ) or "  (all cases passed)"

    drift = runner.drift_vs_baseline(summary)
    if drift is None:
        pytest.fail(
            "no baseline found at tests/eval/baselines.json. "
            "Run `uv run python -m tests.eval.runner --save-baseline` "
            "and commit the baseline."
        )

    assert drift > MAX_DRIFT, (
        f"regression: pass_rate {summary.pass_rate:.2%} drifted "
        f"{drift:+.2%} vs baseline (threshold {MAX_DRIFT:+.2%})\n"
        f"{summary.passed}/{summary.total} passed\n"
        f"failures:\n{failure_report}"
    )
