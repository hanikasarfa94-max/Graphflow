"""Pytest wrapper around the im_assist eval runner — opt-in via `-m eval`.

Mirror of test_planning_eval: pass-rate must be ≥ AC gate and must not regress
more than 5pp vs the committed baseline.
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
async def test_im_assist_eval_no_regression():
    summary = await runner.run_im_assist()
    assert summary.total > 0, "no fixtures loaded"

    failed = [c for c in summary.cases if not c.passed]
    failure_report = "\n".join(
        f"  - {c.fixture_id}: {'; '.join(c.failures)}" for c in failed
    ) or "  (all cases passed)"

    drift = runner.drift_vs_baseline(summary)
    if drift is None:
        pytest.fail(
            "no im_assist baseline found. "
            "Run `uv run python -m tests.eval.runner --agent im_assist --save-baseline` "
            "and commit the baseline."
        )

    assert drift > MAX_DRIFT, (
        f"regression: pass_rate {summary.pass_rate:.2%} drifted "
        f"{drift:+.2%} vs baseline (threshold {MAX_DRIFT:+.2%})\n"
        f"{summary.passed}/{summary.total} passed\n"
        f"failures:\n{failure_report}"
    )
