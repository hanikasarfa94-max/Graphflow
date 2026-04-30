"""Run Config A on hand-curated 40 + 458 realistic-padding nodes (~498 total).

Compares F1 / leak rate / tokens / latency against the existing
synthetic-padded baselines (200 and 1000) to test whether the
RNG-synthetic noise was unrealistically easy.

Circularity caveat (logged in test report): DeepSeek-Chat both
generated the padding and runs Config A. Multi-type retrieval
(decision vs KB vs stream-turn vs task vs risk) keeps the eval
honest in spirit — the LLM has to pick which kind grounds the
query, which is somewhat orthogonal to who authored the content.
Cross-provider generation would tighten the signal further but no
non-DeepSeek key is configured today.
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

from tests.eval.attention.configs import config_a_llm_only  # noqa: E402
from tests.eval.attention.corpus import build_corpus  # noqa: E402
from tests.eval.attention.metrics import summarize  # noqa: E402
from tests.eval.attention.runner import load_seed_queries  # noqa: E402
from tests.eval.attention.types import CorpusItem  # noqa: E402


REALISTIC_JSON = (
    REPO_ROOT / "tests" / "eval" / "dataset" / "attention" / "realistic_padding.json"
)


def _load_realistic_padding() -> list[CorpusItem]:
    """Load DeepSeek-generated padding from disk."""
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


def main():
    queries, truths = load_seed_queries()

    hand_curated = build_corpus(size=40, seed=42)
    realistic = _load_realistic_padding()
    corpus = hand_curated + realistic
    print(
        f"corpus: {len(corpus)} items "
        f"(hand-curated={len(hand_curated)} + realistic={len(realistic)})",
        flush=True,
    )

    t0 = time.monotonic()
    results = []
    for q in queries:
        r = config_a_llm_only(corpus, q)
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

    s = summarize("A", len(corpus), results, truths)

    print()
    print("=" * 60)
    print(
        f"Config A on REALISTIC corpus  size={s.corpus_size}  "
        f"wall={elapsed:.1f}s"
    )
    print(f"  F1:        {s.f1:.3f}")
    print(f"  Precision: {s.precision:.3f}")
    print(f"  Recall:    {s.recall:.3f}")
    print(f"  Leak rate: {s.leak_rate:.3f}  ({s.n_leaks} total leaks)")
    print(f"  Tokens:    {s.tokens_total} total ({s.tokens_total // s.n_queries} avg/q)")
    print(f"  Latency:   p50={s.latency_p50_ms}ms  p95={s.latency_p95_ms}ms")
    print("=" * 60)

    out_path = (
        REPO_ROOT
        / "tests"
        / "eval"
        / "reports"
        / f"config_a_realistic_size_{s.corpus_size}.json"
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
