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
    """Smoke: harness produces summaries for A/B/C without exceptions.

    Asserts shape, not specific values. The corpus and configs evolve
    independently of the harness contract; this test guards the
    contract (corpus → query → config → summary) is intact.
    """
    queries, truths = load_seed_queries()
    # N.1.5 expanded the seed set from 3 to ~12; keep the floor at 10
    # so the test catches accidental fixture deletion but doesn't
    # churn every time we add a query.
    assert len(queries) >= 10, "seed query set should ship with ≥10 fixtures"

    # First-pass eval uses the hand-curated 40-node corpus. The
    # harness handles size > 40 via deterministic padding for the
    # scaling pass (PLAN-Next.md §N.1.5).
    corpus_size = 40
    summaries = run_all_configs(
        corpus_size=corpus_size,
        queries=queries,
        truth_by_query=truths,
    )

    assert len(summaries) == 3
    assert {s.config for s in summaries} == {"A", "B", "C"}
    for s in summaries:
        assert s.n_queries == len(queries)
        assert s.corpus_size == corpus_size
        # Stubs report zero latency; ensures the field is at least set.
        assert s.latency_p50_ms >= 0
        # Each summary is a fully-populated ConfigSummary — the harness
        # contract guarantees the fields exist and the per-query list
        # mirrors the input queries.
        assert len(s.per_query) == len(queries)
        # Audit score is in [0, 1] for any config. Configs A and B are
        # both LIVE (DeepSeek) with no per-cite explanations yet, so
        # each query scores 0.0 if cites exist and 1.0 if no cites —
        # the mean depends on the LLM's cite distribution this run.
        # Config C is still a stub with mocked explanations on every
        # cite so it scores exactly 1.0. Real Config C (slice 4) will
        # ship per-candidate "kept by §7 stack because X" reasons.
        assert 0.0 <= s.audit_score <= 1.0
        if s.config == "C":
            assert s.audit_score == 1.0, (
                f"Config C should audit-score 1.0; got {s.audit_score}"
            )
