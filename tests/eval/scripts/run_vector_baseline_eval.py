"""Run vector-only retrieval (Qwen3-Embedding-8B → DeepSeek) on 538 corpus.

Slice-2 baseline of the §7.2 hybrid stack. Compares against Config A
(full-context LLM) and Config B/BM25 baselines so the slice-2 commit
can quote the lexical-vs-semantic delta.

The first run embeds 538 corpus items + 12 queries via SiliconFlow
(~550 API calls one-time). Subsequent runs hit the disk cache at
`tests/eval/dataset/attention/qwen3_embeddings.json` and are zero-API.

Usage:
    python tests/eval/scripts/run_vector_baseline_eval.py
    python tests/eval/scripts/run_vector_baseline_eval.py --k 30
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "agents" / "src"))

from tests.eval.attention.configs import make_config_b_vector_only  # noqa: E402
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
    parser = argparse.ArgumentParser(
        description="Vector-only (Qwen3-Embedding-8B → LLM) on 538-node corpus."
    )
    parser.add_argument(
        "--k",
        type=int,
        default=50,
        help="Vector top-k feeding the LLM (default 50, per §7.2 spec).",
    )
    args = parser.parse_args()

    queries, truths = load_seed_queries()

    hand_curated = build_corpus(size=40, seed=42)
    realistic = _load_realistic_padding()
    corpus = hand_curated + realistic
    print(
        f"corpus: {len(corpus)} items "
        f"(hand-curated={len(hand_curated)} + realistic={len(realistic)}); "
        f"vector top-k={args.k}",
        flush=True,
    )

    print("building vector index (embeds via SiliconFlow on cache miss)...", flush=True)
    t_index = time.monotonic()
    vector_config = make_config_b_vector_only(corpus)
    print(f"  index ready in {time.monotonic() - t_index:.1f}s", flush=True)

    t0 = time.monotonic()
    results = []
    for q in queries:
        r = vector_config(corpus, q, k=args.k)
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

    s = summarize("B", len(corpus), results, truths)

    print()
    print("=" * 60)
    print(
        f"Vector-only (Qwen3-Embed top-{args.k} → LLM) on REALISTIC corpus  "
        f"size={s.corpus_size}  wall={elapsed:.1f}s"
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
    print("=" * 60)

    out_path = (
        REPO_ROOT
        / "tests"
        / "eval"
        / "reports"
        / f"config_b_vector_realistic_size_{s.corpus_size}_k{args.k}.json"
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
