# Attention Engine Eval

Phase **N.1.5** of `PLAN-Next.md`. Settles the open question from
`new_concepts.md` §7 (Core Algorithmic Doctrine) with data instead of
opinion: how much of the explicit hybrid-retrieval / RRF / membrane /
ranking stack actually needs to ship in v-Next, vs. what a
sufficiently-capable LLM with a large context window already handles?

## The three configurations

For the same corpus and same labeled queries, run all three and
compare:

- **Config A — LLM-only.** Dump every accessible corpus node into the
  LLM context window. No retrieval, no ranking, no membrane filter.
  Tests the upper-bound assumption "model is smart, just give it
  everything."
- **Config B — vector-only → LLM.** Top-K vector retrieval only, then
  LLM. The cheapest retrieval baseline.
- **Config C — full §7 stack → LLM.** Hybrid retrieval (BM25 + vector
  + graph-neighbor + recency + pinned) → RRF fusion → rule-based
  membrane filter → explainable rank → context-bundle assembly →
  LLM. The full doctrine.

## What we measure

Per config × corpus-size:

| Metric | Why it matters |
|---|---|
| Tokens per query | Cost-of-ownership signal. A is expensive; C is cheap if the membrane filter throws out 80%+ of candidates. |
| p50 / p95 latency | A is LLM-bound; C adds retrieval but reduces the LLM's context size. |
| F1 vs ground-truth | Are the right nodes used? Precision + recall against hand-labeled relevance. |
| **Suppressed-node leak rate** | The single non-negotiable. A node tagged `must_not_appear` showing up in cited evidence = leak. Membrane post-filter (§7.7) should drive C to ~0. |
| Audit explainability | Can we answer "why did this node end up in context, why was that one suppressed?" Strong for C, weak for A/B. |

## Decision rule (locked in PLAN-Next.md)

After running all three at corpus = 200 / 1,000 / 5,000:

1. **If A has acceptable F1 AND 0% leak rate at 200 nodes** → ship A
   for v-Next; defer the §7 stack.
2. **If A leaks suppressed nodes** (very likely, since LLMs cite "for
   completeness" things they shouldn't) → ship at minimum §7.7
   (rule-based membrane post-filter) regardless of other layers.
3. **If A's F1 drops sharply at 1k+ nodes** → ship §7.2 hybrid
   retrieval; skip RRF and learning-to-rank.
4. **§7.14 Stage 7 (learning-to-rank) is deferred past v-Next
   regardless** — needs feedback data we won't have for months.

## Layout

```
tests/eval/attention/
├── README.md      # this file
├── __init__.py
├── types.py       # CorpusItem / Query / GroundTruth / ConfigResult
├── corpus.py      # build_corpus(size) — synthetic cell + KB + decisions
├── configs.py     # Config A / B / C implementations
├── metrics.py     # f1, leak_rate, latency, tokens, audit_score
└── runner.py      # run_config(corpus, queries, config) → ConfigResult

tests/eval/dataset/attention/
└── seed_queries.yaml   # initial labeled queries; expand to 30–50
```

## Status (2026-04-29)

Scaffold + types + one seed fixture. Configs and metrics are stubs;
they return placeholder values so the runner exercises end-to-end.
Real LLM calls (DeepSeek per `project_deepseek_dev_llm` memory) wire
in once the corpus generator is real and at least 10 labeled queries
exist.

Track progress per **PLAN-Next.md §"Phase N.1.5 — Attention-engine
eval"**.
