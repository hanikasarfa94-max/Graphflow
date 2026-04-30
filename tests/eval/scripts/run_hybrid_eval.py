"""Run Config C (full §7.2 hybrid stack) on the realistic 538 corpus.

Slice-4 payoff measurement of pickup #4. The slice composes all five
retrievers (BM25 + vector + graph-neighbor + recency + pinned) via
RRF fusion + §7.7 membrane filter, then hands the survivors to
DeepSeek with the same prompt frame as A / B.

Compares against:
  * Config A (full-context LLM) — the no-retrieval baseline.
  * Config B / BM25 (slice 1)   — pure lexical.
  * Vector-only (slice 2)       — pure semantic.

Hypothesis (from slice 1+2 results): vector and BM25 win different
queries (semantic vs lexical), so RRF fusion should produce a strict
superset. Target: F1 ≥ 0.85, recall ≥ 0.85, leak rate 0, tokens
≤ 8K avg/query.

Embedding cache reuses `qwen3_embeddings.json` from slices 2 and is
zero-API on re-runs over the same corpus.

Usage:
    python tests/eval/scripts/run_hybrid_eval.py
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "agents" / "src"))

from tests.eval.attention.configs import make_config_c_hybrid  # noqa: E402
from tests.eval.attention.corpus import build_corpus  # noqa: E402
from tests.eval.attention.metrics import summarize  # noqa: E402
from tests.eval.attention.runner import load_seed_queries  # noqa: E402
from tests.eval.attention.types import CorpusItem  # noqa: E402


REALISTIC_JSON = (
    REPO_ROOT / "tests" / "eval" / "dataset" / "attention" / "realistic_padding.json"
)


def _load_realistic_padding() -> list[CorpusItem]:
    raw = json.loads(REALISTIC_JSON.read_text(encoding="utf-8"))
    return [
        CorpusItem(
            id=item["id"],
            kind=item["kind"],
            scope=item["scope"],
            title=item["title"],
            content=item["content"],
            metadata=dict(item.get("metadata") or {}),
            suppressed=bool(item.get("suppressed", False)),
        )
        for item in raw
    ]


def main() -> None:
    queries, truths = load_seed_queries()

    hand_curated = build_corpus(size=40, seed=42)
    realistic = _load_realistic_padding()
    corpus = hand_curated + realistic
    print(
        f"corpus: {len(corpus)} items "
        f"(hand-curated={len(hand_curated)} + realistic={len(realistic)})",
        flush=True,
    )

    print(
        "building hybrid index (BM25 + vector + graph + recency + pinned)...",
        flush=True,
    )
    t_index = time.monotonic()
    hybrid_config = make_config_c_hybrid(corpus)
    print(f"  index ready in {time.monotonic() - t_index:.1f}s", flush=True)

    t0 = time.monotonic()
    results = []
    for q in queries:
        r = hybrid_config(corpus, q)
        results.append(r)
        truth = truths[q.id]
        cited = set(r.cited_node_ids)
        expected = set(truth.must_appear)
        forbidden = set(truth.must_not_appear)
        hits = cited & expected
        leaks = cited & forbidden
        miss = expected - cited
        flag = "!" if leaks else (" " if hits == expected else "~")
        print(
            f"  {flag} {q.id}  hits={len(hits)}/{len(expected)}  "
            f"leaks={len(leaks)}  miss={len(miss)}  "
            f"tok={r.tokens_in}+{r.tokens_out}  ({r.latency_ms}ms)",
            flush=True,
        )
    elapsed = time.monotonic() - t0

    s = summarize("C", len(corpus), results, truths)

    print()
    print("=" * 60)
    print(
        f"Config C (HYBRID — RRF over BM25 + vector + graph + recency + pinned)\n"
        f"  size={s.corpus_size}  wall={elapsed:.1f}s"
    )
    print(f"  F1:        {s.f1:.3f}")
    print(f"  Precision: {s.precision:.3f}")
    print(f"  Recall:    {s.recall:.3f}")
    print(f"  Leak rate: {s.leak_rate:.3f}  ({s.n_leaks} total leaks)")
    print(
        f"  Tokens:    {s.tokens_total} total "
        f"({s.tokens_total // s.n_queries} avg/q)"
    )
    print(f"  Latency:   p50={s.latency_p50_ms}ms  p95={s.latency_p95_ms}ms")
    print(f"  Audit:     {s.audit_score:.3f}  (1.0 = every cite explained)")
    print("=" * 60)

    out_path = (
        REPO_ROOT
        / "tests"
        / "eval"
        / "reports"
        / f"config_c_hybrid_realistic_size_{s.corpus_size}.json"
    )
    out_path.write_text(
        json.dumps(
            {**asdict(s), "per_query": [asdict(r) for r in s.per_query]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
