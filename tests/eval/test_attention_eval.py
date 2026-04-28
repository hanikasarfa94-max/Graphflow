"""Pytest entry for the attention engine eval — Phase N.1.5.

This is NOT a pass/fail eval at this stage; it's a smoke test that
the eval harness wires end-to-end (corpus → query → config → summary)
without raising. Real F1 / leak-rate gates land once configs A/B/C
have real implementations and the seed query set grows past 10.

Marked `@pytest.mark.eval` so it's skipped from default unit-test runs
and only fires under `pytest -m eval` (matches existing eval pattern
at tests/eval/runner.py).
"""
from __future__ import annotations

import pytest

from tests.eval.attention.runner import (
    load_seed_queries,
    run_all_configs,
)


@pytest.mark.eval
def test_attention_harness_smoke():
    """Smoke: harness produces summaries for A/B/C without exceptions."""
    queries, truths = load_seed_queries()
    assert len(queries) >= 3, "seed query set should ship with ≥3 fixtures"

    summaries = run_all_configs(
        corpus_size=200,
        queries=queries,
        truth_by_query=truths,
    )

    assert len(summaries) == 3
    assert {s.config for s in summaries} == {"A", "B", "C"}
    for s in summaries:
        assert s.n_queries == len(queries)
        assert s.corpus_size == 200
        # Stubs report zero latency; ensures the field is at least set.
        assert s.latency_p50_ms >= 0
        # Audit score: A and B don't populate explanations (stub
        # returns empty for the cited node ids that have no
        # explanation match), C populates explanations for every
        # cited id. Stub harness expectation:
        if s.config == "C":
            assert s.audit_score == 1.0, (
                f"Config C should audit-score 1.0; got {s.audit_score}"
            )
        else:
            # A and B leave explanations empty; their cited nodes have
            # zero explanations. audit_score = 0 / n_cited = 0.0.
            # Edge case: if a config cites nothing, audit_score = 1.0
            # vacuously. Stub configs always cite ≥1 node so we expect
            # 0.0 here.
            assert s.audit_score == 0.0, (
                f"Config {s.config} stub should audit-score 0.0;"
                f" got {s.audit_score}"
            )
