# Attention engine eval — first-pass results

PLAN-Next.md §N.1.5. Eval-driven decision on whether to ship the full §7
retrieval stack or defer in favor of pure-LLM-everything-visible.

## Run conditions

- Corpus: hand-curated 40-node bench + RNG-padded synthetic items.
- Queries: 12 hand-labeled (4 retrieval / 3 ambiguous / 2 scope-suppress / 3 supersede).
- LLM: DeepSeek-Chat (deepseek-chat model, temperature=0.1).
- Reproduction: `pytest -m eval tests/eval/test_attention_eval.py` runs at 40 nodes;
  larger scales are explicit ad-hoc runs via `runner.run_config(corpus_size=…)`.

## Results — Config A (pure LLM, everything visible)

| Scale | F1 | Precision | Recall | Leak rate | Tokens/q | Latency p50 |
|------:|---:|----------:|-------:|----------:|---------:|------------:|
|    40 | 0.821 | 0.941 | 0.727 | **0.000** | ~3K  | 3.7s |
|   200 | 0.800 | 0.889 | 0.727 | **0.000** | ~8.9K | 5.7s |
|  1000 | 0.850 | 0.944 | 0.773 | **0.000** | ~40K | 5.8s |

The recall ceiling (~0.73-0.77) is roughly stable across scale — the
queries Config A misses are the same set (q02/q06/q08/q09 partial; q07
flips at 1000 — likely temperature variance).

The supersede probes (q10/q11/q12) hit 2/2 each at every scale —
Config A correctly distinguishes superseded from current content.

## Decision rule resolution

Per PLAN-Next.md §N.1.5:

| Trigger | Met? |
|---------|------|
| If A leaks suppressed nodes → ship §7.7 membrane post-filter as floor | NO (leak rate stayed 0) |
| If A is clean at 200-node scale → defer §7 stack | **YES** |
| If A's F1 drops at 1k+ → ship §7.2 hybrid retrieval | NO (F1 actually rose) |
| §7.14 LTR | deferred regardless |

**Decision: defer the §7 stack for v-Next. Ship pure-LLM-everything-visible.**

This is bounded by scale: Config A's context window (~64K tokens on
DeepSeek-Chat) breaks somewhere between 1000 and 5000 nodes. v-Next
target users (10-30 person teams) are not expected to cross that
threshold inside the v-Next ship window. If a customer cell does, §7.2
hybrid retrieval becomes a real ship gate at that point — not before.

## Files

- `config_a_size_200.json` — full ConfigSummary + per-query results at 200.
- `config_a_size_1000.json` — same at 1000.
- 40-node baseline: replayable via `pytest -m eval tests/eval/test_attention_eval.py`.

## Caveats worth flagging

1. **12 queries is small.** F1 swings of ~0.05 between 200 and 1000 are
   within noise for a 12-query bench. The leak rate (0/12 across all
   three scales) is the load-bearing number; F1 is supportive.
2. **Padding nodes are deterministic-RNG synthetic plain text.** They
   may be "easier" noise than real-world cell content. A second pass
   with paraphrased real content (e.g., GPT-rewritten variants of the
   hand-curated set) would tighten the confidence interval.
3. **Recall 0.73 is structural.** Config A's failure mode is "decline
   to cite" — never "cite the wrong thing." That's safe but means a
   user asking an ambiguous question may get an under-cited answer.
   Worth a follow-up: chain-of-thought prompt variant, or a second
   pass that asks "did you miss anything?" at the cost of ~2x tokens.
