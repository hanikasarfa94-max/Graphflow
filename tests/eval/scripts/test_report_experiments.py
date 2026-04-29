"""Test report experiments — N.1.5 follow-up.

Two experiments to characterize Config A's behavior before committing
~3 weeks to Path B (§7.2 + §7.4 frecency):

  Test 1 — timestamp-aware prompt: same Config A, but the JSON nodes
           sent to DeepSeek now include a `ts` field. Hypothesis: the
           recall gap on time-sensitive queries (q02 "currently…", q06
           "still…") closes when the LLM can see when content was made.

  Test 2 — variance check: three back-to-back runs of bare Config A at
           200 nodes. Establishes the noise floor for temp=0.1 so we
           can interpret Test 1's signal honestly.

Output: tests/eval/reports/test_report_experiments.json + a printed
summary. Sequential, single LLMClient instance to keep API state warm.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import statistics
import sys
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make sure repo root + agents package are importable when this script
# is invoked directly (e.g. `python tests/eval/scripts/test_...py`).
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "packages" / "agents" / "src"))

from tests.eval.attention.configs import (  # noqa: E402
    _viewer_can_see,
    _parse_cited_ids,
)
from tests.eval.attention.corpus import build_corpus  # noqa: E402
from tests.eval.attention.metrics import summarize  # noqa: E402
from tests.eval.attention.runner import load_seed_queries  # noqa: E402
from tests.eval.attention.types import ConfigRunResult, CorpusItem, Query  # noqa: E402
from workgraph_agents.llm import LLMClient  # noqa: E402


_NOW = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
_NINETY_DAYS = timedelta(days=90)


def _synthetic_ts(item: CorpusItem) -> str:
    """Deterministic ISO timestamp for an item that has no metadata.ts.

    Hash the id to get a stable offset within the past 90 days. Ages
    KB items > 30 days, decisions ~14-60 days, tasks ~7-30 days, risks
    ~14-45 days, stream_turns use existing metadata.ts if present.
    """
    if "ts" in item.metadata:
        return str(item.metadata["ts"])
    h = int(hashlib.sha1(item.id.encode("utf-8")).hexdigest(), 16)
    # Seed offset by kind so different kinds settle into reasonable bands.
    band = {
        "kb_item": (15, 90),
        "decision": (3, 60),
        "task": (1, 30),
        "risk": (7, 45),
        "stream_turn": (1, 14),
        "person": (1, 365),
    }.get(item.kind, (1, 90))
    span_days = band[1] - band[0]
    offset = band[0] + (h % (span_days * 24 * 60))
    age = timedelta(minutes=offset * 60)  # offset is roughly hours
    ts = _NOW - age
    return ts.isoformat()


def _pack_prompt(
    visible: Sequence[CorpusItem],
    query: Query,
    *,
    with_time: bool,
) -> list[dict[str, str]]:
    """Bare or time-aware variant of Config A's prompt."""
    nodes_payload = []
    for item in visible:
        node = {
            "id": item.id,
            "kind": item.kind,
            "scope": item.scope,
            "title": item.title,
            "content": item.content,
        }
        if with_time:
            node["created_at"] = _synthetic_ts(item)
        nodes_payload.append(node)

    if with_time:
        time_clause = (
            " Each node carries a `created_at` ISO timestamp; weight "
            "recent content higher when the query asks about current / "
            "latest / still / now state. Older content for the same "
            "fact has likely been superseded."
        )
    else:
        time_clause = ""
    system = (
        "You are a retrieval assistant for a collaboration platform. "
        "Given a corpus of nodes (KB items, decisions, tasks, risks, "
        "stream turns) and a user query, return ONLY the node ids "
        "whose content directly grounds an answer to the query. Prefer "
        "recent / active content over older / superseded content when "
        "both touch the same fact." + time_clause + " Return strict "
        'JSON of shape {"cited_ids": ["..."], "reasoning": "..."}. '
        "Cite zero ids if nothing grounds the query."
    )
    user = json.dumps(
        {
            "viewer_id": query.viewer_id,
            "query": query.text,
            "scope_anchor": query.scope_anchor,
            "corpus": nodes_payload,
        },
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _run_query(
    client: LLMClient,
    corpus: Sequence[CorpusItem],
    query: Query,
    *,
    with_time: bool,
) -> ConfigRunResult:
    visible = [
        item for item in corpus if _viewer_can_see(item, query.viewer_id)
    ]
    valid_ids = {item.id for item in visible}
    suppressed_ids = {item.id for item in corpus if item.suppressed}
    messages = _pack_prompt(visible, query, with_time=with_time)
    started = time.monotonic()
    result = asyncio.run(
        client.complete(
            messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    cited = _parse_cited_ids(result.content, valid_ids)
    leaks = tuple(sorted(set(cited) & suppressed_ids))
    return ConfigRunResult(
        config="A",
        query_id=query.id,
        cited_node_ids=cited,
        suppressed_cited=leaks,
        tokens_in=result.prompt_tokens,
        tokens_out=result.completion_tokens,
        latency_ms=elapsed_ms,
    )


def _run_all(
    client: LLMClient,
    corpus: Sequence[CorpusItem],
    queries: Sequence[Query],
    truths,
    *,
    with_time: bool,
):
    results = []
    for q in queries:
        results.append(_run_query(client, corpus, q, with_time=with_time))
    return summarize("A", len(corpus), results, truths)


def main():
    queries, truths = load_seed_queries()
    corpus = build_corpus(size=200, seed=42)
    client = LLMClient()
    output = {"experiments": {}, "ts": _NOW.isoformat()}

    # Test 2 first — variance baseline. Three bare runs.
    print("=" * 60)
    print("Test 2 — variance: 3 bare runs at 200 nodes")
    print("=" * 60)
    bare_runs = []
    for i in range(3):
        t0 = time.monotonic()
        s = _run_all(client, corpus, queries, truths, with_time=False)
        elapsed = time.monotonic() - t0
        print(
            f"  run {i + 1}: F1={s.f1:.3f} P={s.precision:.3f} R={s.recall:.3f} "
            f"leaks={s.n_leaks} tok={s.tokens_total} wall={elapsed:.1f}s"
        )
        bare_runs.append({
            "run": i + 1,
            "f1": s.f1,
            "precision": s.precision,
            "recall": s.recall,
            "leak_rate": s.leak_rate,
            "n_leaks": s.n_leaks,
            "tokens_total": s.tokens_total,
            "latency_p50_ms": s.latency_p50_ms,
            "wall_s": round(elapsed, 1),
            "per_query_hits": {
                r.query_id: len(set(r.cited_node_ids) & set(truths[r.query_id].must_appear))
                for r in s.per_query
            },
        })

    f1s = [r["f1"] for r in bare_runs]
    recalls = [r["recall"] for r in bare_runs]
    print()
    print(f"  F1 mean={statistics.mean(f1s):.3f}  stdev={statistics.stdev(f1s):.3f}")
    print(
        f"  Recall mean={statistics.mean(recalls):.3f}  "
        f"stdev={statistics.stdev(recalls):.3f}"
    )
    output["experiments"]["test2_variance"] = {
        "runs": bare_runs,
        "f1_mean": statistics.mean(f1s),
        "f1_stdev": statistics.stdev(f1s),
        "recall_mean": statistics.mean(recalls),
        "recall_stdev": statistics.stdev(recalls),
    }

    # Test 1 — timestamp-aware prompt.
    print()
    print("=" * 60)
    print("Test 1 — timestamp-aware prompt at 200 nodes")
    print("=" * 60)
    t0 = time.monotonic()
    s = _run_all(client, corpus, queries, truths, with_time=True)
    elapsed = time.monotonic() - t0
    print(
        f"  F1={s.f1:.3f} P={s.precision:.3f} R={s.recall:.3f} "
        f"leaks={s.n_leaks} tok={s.tokens_total} wall={elapsed:.1f}s"
    )
    print()
    print("  Per-query hits (compare to bare baseline):")
    for r in s.per_query:
        truth = truths[r.query_id]
        cited = set(r.cited_node_ids)
        expected = set(truth.must_appear)
        hits = len(cited & expected)
        bare_avg = statistics.mean(
            run["per_query_hits"].get(r.query_id, 0) for run in bare_runs
        )
        delta = hits - bare_avg
        flag = "+" if delta > 0.5 else ("-" if delta < -0.5 else " ")
        print(
            f"  {flag} {r.query_id}  with_time={hits}/{len(expected)}  "
            f"bare_avg={bare_avg:.1f}/{len(expected)}  delta={delta:+.1f}"
        )
    output["experiments"]["test1_with_time"] = {
        "f1": s.f1,
        "precision": s.precision,
        "recall": s.recall,
        "leak_rate": s.leak_rate,
        "n_leaks": s.n_leaks,
        "tokens_total": s.tokens_total,
        "latency_p50_ms": s.latency_p50_ms,
        "wall_s": round(elapsed, 1),
        "per_query_hits": {
            r.query_id: len(
                set(r.cited_node_ids) & set(truths[r.query_id].must_appear)
            )
            for r in s.per_query
        },
    }

    out_path = Path("tests/eval/reports/test_report_experiments.json")
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"saved {out_path}")


if __name__ == "__main__":
    main()
