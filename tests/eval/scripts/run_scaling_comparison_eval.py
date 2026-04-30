"""§7.2 scaling comparison eval — slice-4 addendum (pickup #4).

Runs three retrieval variants on a single corpus so the comparison is
apples-to-apples (same queries, same ground truth, same LLM):

  * **Vector alone** (Qwen3-Embedding-8B → DeepSeek)
  * **BM25 + Vector RRF** (classical IR hybrid)
  * **Full 5-layer hybrid** (BM25 + Vector + Graph + Recency + Pinned)

Slice 4's 538-node finding was that vector alone beats both fusion
variants. This script lets us re-test at larger scale (2500-ish) to
check whether RRF starts winning when individual top-50 lists
truncate too aggressively.

Loads:
  * 40 hand-curated spine items (build_corpus(size=40, seed=42))
  * Whatever JSON files are passed via --realistic-files (default:
    realistic_padding.json + realistic_padding_xl.json).

Saves a single JSON report containing all three summaries side-by-side
for direct diff against the slice-1/2/4 reports.

Usage:
    python tests/eval/scripts/run_scaling_comparison_eval.py
    python tests/eval/scripts/run_scaling_comparison_eval.py \
        --realistic-files tests/eval/dataset/attention/realistic_padding.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "agents" / "src"))

from tests.eval.attention.configs import (  # noqa: E402
    _embedding_text,
    _get_llm_client,
    _pack_prompt,
    _parse_cited_ids,
    _viewer_can_see,
    make_config_b_vector_only,
    make_config_c_hybrid,
)
from tests.eval.attention.corpus import build_corpus  # noqa: E402
from tests.eval.attention.embeddings import (  # noqa: E402
    EmbeddingsCache,
    SiliconFlowEmbeddingClient,
    embed_with_cache,
)
from tests.eval.attention.metrics import summarize  # noqa: E402
from tests.eval.attention.retrievers import (  # noqa: E402
    BM25Retriever,
    VectorRetriever,
    reciprocal_rank_fusion,
)
from tests.eval.attention.runner import load_seed_queries  # noqa: E402
from tests.eval.attention.types import ConfigRunResult, CorpusItem  # noqa: E402


def _load_json_corpus(path: Path) -> list[CorpusItem]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        CorpusItem(
            id=it["id"],
            kind=it["kind"],
            scope=it["scope"],
            title=it["title"],
            content=it["content"],
            metadata=dict(it.get("metadata") or {}),
            suppressed=bool(it.get("suppressed", False)),
        )
        for it in raw
    ]


def _make_bm25_vector_rrf(
    corpus: list[CorpusItem],
    cache: EmbeddingsCache,
    embed_client: SiliconFlowEmbeddingClient,
):
    """Closure: classical lexical+semantic RRF (no graph/recency/pinned).

    Tests the hypothesis that the 5-layer hybrid loses because of
    extra layers, not because RRF itself is the wrong tool.
    """
    item_texts = [_embedding_text(item) for item in corpus]
    item_vectors = asyncio.run(embed_with_cache(item_texts, cache, embed_client))
    bm25 = BM25Retriever(corpus)
    vec = VectorRetriever(corpus, item_vectors)

    def _run(_corpus, query) -> ConfigRunResult:
        started = time.monotonic()
        visible_mask = [_viewer_can_see(it, query.viewer_id) for it in corpus]
        visible_ids = {
            it.id for it, ok in zip(corpus, visible_mask) if ok
        }
        suppressed_ids = {it.id for it in corpus if it.suppressed}
        q_vec = asyncio.run(
            embed_with_cache([query.text], cache, embed_client)
        )[0]
        bm25_h = bm25.top_k(
            query.text, k=50, candidate_filter=visible_mask
        )
        vec_h = vec.top_k(q_vec, k=50, candidate_filter=visible_mask)
        fused = reciprocal_rank_fusion(
            [bm25_h, vec_h], k=50, weights=[1.0, 1.0]
        )
        candidates = [it for it, _s in fused if not it.suppressed]
        if not candidates:
            return ConfigRunResult(
                config="C",
                query_id=query.id,
                cited_node_ids=(),
                suppressed_cited=(),
                tokens_in=0,
                tokens_out=0,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        llm = _get_llm_client()
        msgs = _pack_prompt(candidates, query)
        res = asyncio.run(
            llm.complete(
                msgs,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
        )
        cited = _parse_cited_ids(res.content, visible_ids)
        return ConfigRunResult(
            config="C",
            query_id=query.id,
            cited_node_ids=cited,
            suppressed_cited=tuple(sorted(set(cited) & suppressed_ids)),
            tokens_in=res.prompt_tokens,
            tokens_out=res.completion_tokens,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    return _run


def _print_per_query(name: str, results, truths) -> None:
    print(f"\n--- {name} ---")
    for r in results:
        truth = truths[r.query_id]
        cited = set(r.cited_node_ids)
        expected = set(truth.must_appear)
        forbidden = set(truth.must_not_appear)
        hits = cited & expected
        leaks = cited & forbidden
        miss = expected - cited
        flag = "!" if leaks else (" " if hits == expected else "~")
        print(
            f"  {flag} {r.query_id}  hits={len(hits)}/{len(expected)}  "
            f"leaks={len(leaks)}  miss={len(miss)}  "
            f"tok={r.tokens_in}+{r.tokens_out}  ({r.latency_ms}ms)"
        )


def _print_summary(name: str, s) -> None:
    print(f"\n{name}")
    print(f"  size={s.corpus_size}  n_queries={s.n_queries}")
    print(
        f"  F1={s.f1:.3f}  P={s.precision:.3f}  R={s.recall:.3f}  "
        f"Leak={s.leak_rate:.3f}  Tok/q={s.tokens_total // s.n_queries}  "
        f"p50={s.latency_p50_ms}ms"
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--realistic-files",
        nargs="*",
        type=Path,
        default=[
            REPO_ROOT
            / "tests"
            / "eval"
            / "dataset"
            / "attention"
            / "realistic_padding.json",
            REPO_ROOT
            / "tests"
            / "eval"
            / "dataset"
            / "attention"
            / "realistic_padding_xl.json",
        ],
    )
    args = p.parse_args()

    queries, truths = load_seed_queries()

    corpus = build_corpus(size=40, seed=42)
    sources = [("hand-curated", 40)]
    for path in args.realistic_files:
        if not path.exists():
            print(f"  (skipping missing file: {path})", flush=True)
            continue
        loaded = _load_json_corpus(path)
        corpus.extend(loaded)
        sources.append((path.name, len(loaded)))
    print(
        f"corpus: {len(corpus)} items  ({', '.join(f'{n}={c}' for n, c in sources)})",
        flush=True,
    )

    cache_path = (
        REPO_ROOT
        / "tests"
        / "eval"
        / "dataset"
        / "attention"
        / "qwen3_embeddings.json"
    )
    cache = EmbeddingsCache(cache_path)
    embed_client = SiliconFlowEmbeddingClient()

    print("\nbuilding shared embedding index (cache miss = SF API call)...", flush=True)
    t_idx = time.monotonic()
    item_texts = [_embedding_text(item) for item in corpus]
    asyncio.run(embed_with_cache(item_texts, cache, embed_client))
    print(f"  index ready in {time.monotonic() - t_idx:.1f}s", flush=True)

    # Build the three runners. They share the cache so they only embed
    # the corpus + queries once across the whole comparison.
    print("\nbuilding three Config-C-shaped runners...", flush=True)
    vector_only = make_config_b_vector_only(corpus, cache_path=cache_path)
    bm25_vector = _make_bm25_vector_rrf(corpus, cache, embed_client)
    full_hybrid = make_config_c_hybrid(corpus, cache_path=cache_path)

    summaries: dict[str, object] = {}
    per_query: dict[str, list] = {}
    for name, runner in (
        ("vector_only", vector_only),
        ("bm25_vector_rrf", bm25_vector),
        ("full_hybrid", full_hybrid),
    ):
        print(f"\n=== running {name} ===", flush=True)
        t0 = time.monotonic()
        results = []
        for q in queries:
            r = runner(corpus, q)
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
        config_letter = "B" if name == "vector_only" else "C"
        s = summarize(config_letter, len(corpus), results, truths)
        per_query[name] = [asdict(r) for r in s.per_query]
        summaries[name] = {
            "wall_seconds": round(elapsed, 1),
            "f1": s.f1,
            "precision": s.precision,
            "recall": s.recall,
            "leak_rate": s.leak_rate,
            "n_leaks": s.n_leaks,
            "tokens_total": s.tokens_total,
            "tokens_per_query": s.tokens_total // s.n_queries,
            "latency_p50_ms": s.latency_p50_ms,
            "latency_p95_ms": s.latency_p95_ms,
            "audit_score": s.audit_score,
        }

    print("\n" + "=" * 70)
    print(f"§7.2 SCALING COMPARISON  size={len(corpus)}  n_queries={len(queries)}")
    print("=" * 70)
    header = (
        f"{'variant':<22} {'F1':>6} {'P':>6} {'R':>6} {'Leak':>6} "
        f"{'Tok/q':>8} {'p50':>7}"
    )
    print(header)
    print("-" * 70)
    for name, s in summaries.items():
        s_dict = s if isinstance(s, dict) else {}
        print(
            f"{name:<22} "
            f"{s_dict['f1']:>6.3f} "
            f"{s_dict['precision']:>6.3f} "
            f"{s_dict['recall']:>6.3f} "
            f"{s_dict['leak_rate']:>6.3f} "
            f"{s_dict['tokens_per_query']:>8} "
            f"{s_dict['latency_p50_ms']:>5}ms"
        )
    print("=" * 70)

    out_path = (
        REPO_ROOT
        / "tests"
        / "eval"
        / "reports"
        / f"scaling_comparison_size_{len(corpus)}.json"
    )
    out_path.write_text(
        json.dumps(
            {
                "corpus_size": len(corpus),
                "n_queries": len(queries),
                "sources": sources,
                "summaries": summaries,
                "per_query": per_query,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
