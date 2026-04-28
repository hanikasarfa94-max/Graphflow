"""Metric calculators for the attention engine eval.

All metrics are per-query with explicit aggregation rules in `summarize`.
Pure functions; no I/O, no LLM calls.
"""
from __future__ import annotations

import statistics
from collections.abc import Iterable

from .types import ConfigRunResult, ConfigSummary, GroundTruth


def precision_recall_f1(
    cited: Iterable[str],
    must_appear: Iterable[str],
) -> tuple[float, float, float]:
    """Standard set-based P/R/F1.

    `cited` = node ids the config used. `must_appear` = ground-truth
    relevant set. F1 here is structural retrieval F1, not prose quality.
    Empty must_appear → vacuously perfect (skipped in aggregation).
    """
    cited_set = set(cited)
    expected_set = set(must_appear)
    if not expected_set:
        return 1.0, 1.0, 1.0
    tp = len(cited_set & expected_set)
    precision = tp / len(cited_set) if cited_set else 0.0
    recall = tp / len(expected_set)
    if precision + recall == 0:
        return precision, recall, 0.0
    f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def count_leaks(
    cited: Iterable[str],
    must_not_appear: Iterable[str],
) -> tuple[int, tuple[str, ...]]:
    """Returns (count, ids). A "leak" = cited a node the membrane
    should have suppressed (private, superseded, redacted, sensitive)
    AND that the ground-truth labeled as must-not-appear.
    """
    leaks = tuple(sorted(set(cited) & set(must_not_appear)))
    return len(leaks), leaks


def audit_score(result: ConfigRunResult) -> float:
    """Fraction of cited nodes that have a `why-was-this-kept` trace.

    Config C (full §7 stack) populates `explanations` for every cited
    node; A/B leave it empty so they score 0.0. The decision rule cares
    about audit explainability — a 0.0 here is not a failure but a
    feature gap that matters for production debugging.
    """
    if not result.cited_node_ids:
        return 1.0
    n_with_explanation = sum(
        1 for nid in result.cited_node_ids if nid in result.explanations
    )
    return n_with_explanation / len(result.cited_node_ids)


def summarize(
    config: str,
    corpus_size: int,
    results: list[ConfigRunResult],
    truth_by_query: dict[str, GroundTruth],
) -> ConfigSummary:
    """Aggregate per-query results into one ConfigSummary row.

    Aggregation rules:
      * F1/precision/recall = micro-average across queries (sum tp/fp/fn,
        compute once). Macro-average tends to over-weight tiny queries.
      * leak_rate = fraction of queries with ≥ 1 leak. Different from
        n_leaks (total leaked nodes) — both reported.
      * latency p50/p95 from per-query latency_ms.
      * audit_score = mean over per-query audit fractions.
    """
    if not results:
        return ConfigSummary(
            config=config,  # type: ignore[arg-type]
            corpus_size=corpus_size,
            n_queries=0,
            f1=0.0,
            precision=0.0,
            recall=0.0,
            leak_rate=0.0,
            n_leaks=0,
            tokens_total=0,
            latency_p50_ms=0,
            latency_p95_ms=0,
            audit_score=0.0,
            per_query=[],
        )

    # Micro-average tp/fp/fn for P/R/F1.
    total_tp = total_fp = total_fn = 0
    n_leaks = 0
    n_queries_with_leak = 0
    audit_scores: list[float] = []
    latencies: list[int] = []
    tokens = 0

    for r in results:
        truth = truth_by_query.get(r.query_id)
        if truth is None:
            continue
        cited_set = set(r.cited_node_ids)
        expected_set = set(truth.must_appear)
        forbidden_set = set(truth.must_not_appear)
        tp = len(cited_set & expected_set)
        total_tp += tp
        total_fp += len(cited_set - expected_set)
        total_fn += len(expected_set - cited_set)
        leaks = cited_set & forbidden_set
        if leaks:
            n_queries_with_leak += 1
            n_leaks += len(leaks)
        audit_scores.append(audit_score(r))
        latencies.append(r.latency_ms)
        tokens += r.tokens_in + r.tokens_out

    precision = (
        total_tp / (total_tp + total_fp) if (total_tp + total_fp) else 0.0
    )
    recall = (
        total_tp / (total_tp + total_fn) if (total_tp + total_fn) else 0.0
    )
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )
    leak_rate = n_queries_with_leak / len(results)

    p50 = int(statistics.median(latencies)) if latencies else 0
    if latencies:
        sorted_l = sorted(latencies)
        p95_idx = max(0, int(len(sorted_l) * 0.95) - 1)
        p95 = sorted_l[p95_idx]
    else:
        p95 = 0

    return ConfigSummary(
        config=config,  # type: ignore[arg-type]
        corpus_size=corpus_size,
        n_queries=len(results),
        f1=f1,
        precision=precision,
        recall=recall,
        leak_rate=leak_rate,
        n_leaks=n_leaks,
        tokens_total=tokens,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        audit_score=(
            sum(audit_scores) / len(audit_scores) if audit_scores else 0.0
        ),
        per_query=results,
    )
