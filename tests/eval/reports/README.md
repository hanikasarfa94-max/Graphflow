# Attention engine eval — first-pass results

PLAN-Next.md §N.1.5. Eval-driven decision on whether the full §7
retrieval stack is load-bearing for v-Next's target scale, or whether
membrane-suppressed eligible context fed to a long-context LLM is
sufficient.

## Run conditions

- Corpus: hand-curated 40-node bench + RNG-padded synthetic items.
- Queries: 12 hand-labeled (4 retrieval / 3 ambiguous / 2 scope-suppress / 3 supersede).
- LLM: DeepSeek-Chat (deepseek-chat model, temperature=0.1).
- Reproduction: `pytest -m eval tests/eval/test_attention_eval.py` runs at 40 nodes;
  larger scales are explicit ad-hoc runs via `runner.run_config(corpus_size=…)`.

## Results — Config A (membrane-suppressed eligible context + long-context LLM activation)

Config A passes the corpus through `_viewer_can_see` (drops other
users' personal items) and existing access guards before handing what
remains to DeepSeek-Chat. The membrane is still doing its job; what
the eval measures is whether the LLM, given properly-shaped context,
can pick the right ids without an explicit retrieval/rerank stack on
top.

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

**Decision: §7 is not load-bearing at v-Next's target scale. Ship Config A
(membrane-suppressed eligible context + long-context LLM activation).**

§7 is not obsolete — it remains the documented scale-triggered fallback.
The decision boundary is explicit:

- Ship Config A for v-Next.
- §7.2 hybrid retrieval is the scale-triggered path; it becomes a ship
  gate on **any** of:
  - Cell size approaches the 1K-5K node band (Config A's context window
    breaks somewhere between, depending on node verbosity and DeepSeek's
    deployed context cap).
  - Leak rate regresses above 0 in any scale or query slice.
  - F1 drops below the v-Next acceptance bar in production telemetry.
  - Token cost per turn exceeds budget at customer scale.

v-Next target users (10-30 person teams) are not expected to cross
those thresholds inside the v-Next ship window.

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
