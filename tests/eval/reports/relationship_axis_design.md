# Relationship interpretation accuracy — eval axis design

Drafted 2026-04-30 as the design counterpart to the architectural framing
in `test_report.md` (5-layer model, "missing capability is relation-evidence
in the payload"). Implementation lands in a separate slice; this doc is
spec only.

## 1. Axis definition

**What we measure:** given a query, a curated set of cells **plus the
relationship edges between those cells**, does the LLM produce an answer
that *correctly uses* the relationships?

The five-layer model puts the graph at layer 3 (structural memory +
relation routing). Today's prompt payload only exposes layer 1 (cell
content). Recall, F1, and leak rate test layer 1 + layer 4 — they ask
"did the right cells reach the model and did it write a coherent reply?"
This axis isolates the **layer 3 → layer 4 hand-off**: when we put the
graph evidence in front of the model, does the model use it the way a
human reading a graph would?

Concretely, "use the relationships" means three behaviors:

1. **Edge-respecting verdict** — when an `overrides` edge points from
   A to B, the answer treats B as the live view, not A. When `blocks`
   points from X to Y, the answer reports X as the blocker for Y.
2. **Edge-cited explanation** — the answer references the relationship
   in natural language ("decision_X supersedes decision_Y" / "task_T is
   blocked by risk_R"), not just dumps both cells side-by-side.
3. **No invented edges** — the answer does not assert relationships the
   payload did not contain. (Failure mode: "X depends on Y" when no
   `depends-on` edge exists between them.)

**Distinction from existing axes:**

| Axis | Question | Layer pair tested |
|------|----------|-------------------|
| Recall | Right cells surfaced? | retrieval → context |
| Precision / F1 | Right cells, no wrong ones? | retrieval → context |
| Leak rate | Forbidden cells exposed? | membrane → context |
| **Relationship interpretation** | Does the answer USE the edges? | graph evidence → LLM verdict |

A run can score perfect F1 (all the right cells in the prompt) and still
score zero on relationship interpretation if the LLM ignores or invents
edges. That is the gap this axis exposes.

## 2. Corpus design

**Size:** 30 query/fixture pairs, hand-curated. Three pairs per
relationship type × 9 edge types + 3 multi-edge stress fixtures.

**Why 30 is sufficient:** the existing N.1.5 corpus is 12 queries and
gives stable signal at stdev=0 (Test 2). Relationship interpretation has
more axes to cover (one per edge type), so we need ~2.5× the queries,
but each fixture is *narrower* than an N.1.5 query (small cell set, single
relationship under test) so per-query authoring cost stays comparable.
30 fits one human afternoon and one DeepSeek eval run under $1.

**Edge types covered (one fixture per relationship-shape × 3 query
phrasings each):**

`overrides`, `depends-on`, `crystallized-from`, `blocks`,
`source-of`, `downstream-of`, `conflicts-with`, `mentioned-by`,
`belongs-to`.

**Sketch fixtures (JSON-shaped, abbreviated):**

```json
{
  "id": "rel_overrides_01",
  "query": "What's the current Postgres pool size?",
  "edge_type": "overrides",
  "cells": [
    {"id": "dec_pool_v1", "kind": "decision",
     "excerpt": "Postgres pool sized to 20 connections."},
    {"id": "dec_pool_v2", "kind": "decision",
     "excerpt": "Bump Postgres pool to 50 after staging incident."}
  ],
  "edges": [
    {"type": "overrides", "src": "dec_pool_v2", "tgt": "dec_pool_v1"}
  ],
  "expected_answer_id": "dec_pool_v2",
  "must_mention": ["dec_pool_v2"],
  "must_not_assert": ["dec_pool_v1 is current"]
}
```

```json
{"id": "rel_blocks_02", "query": "Why is the SLA work stuck?",
 "edge_type": "blocks",
 "cells": [{"id": "task_sla_dash", ...}, {"id": "risk_metrics_drift", ...}],
 "edges": [{"type": "blocks", "src": "risk_metrics_drift", "tgt": "task_sla_dash"}],
 "expected_answer_id": "risk_metrics_drift",
 "must_mention": ["risk_metrics_drift", "blocks"]}
```

```json
{"id": "rel_crystallized_03", "query": "Where did the auth-fallback decision come from?",
 "edge_type": "crystallized-from",
 "cells": [{"id": "dec_auth_fallback", ...}, {"id": "msg_alice_42", ...}],
 "edges": [{"type": "crystallized-from", "src": "dec_auth_fallback", "tgt": "msg_alice_42"}],
 "must_mention": ["msg_alice_42"]}
```

```json
{"id": "rel_conflicts_04", "query": "Are the rate-limit proposals consistent?",
 "edge_type": "conflicts-with",
 "cells": [{"id": "kb_ratelimit_global", ...}, {"id": "kb_ratelimit_per_ip", ...}],
 "edges": [{"type": "conflicts-with", "src": "kb_ratelimit_global", "tgt": "kb_ratelimit_per_ip"}],
 "must_assert_conflict": true}
```

```json
{"id": "rel_depends_05", "query": "Can we ship the migration this week?",
 "edge_type": "depends-on",
 "cells": [{"id": "task_migration", ...}, {"id": "task_schema_review", ...}],
 "edges": [{"type": "depends-on", "src": "task_migration", "tgt": "task_schema_review"}],
 "must_mention": ["task_schema_review"]}
```

```json
{"id": "rel_source_of_06", "query": "What proves the API rate-limit number?",
 "edge_type": "source-of",
 "cells": [{"id": "kb_ratelimit_spec", ...}, {"id": "msg_bob_decision", ...}],
 "edges": [{"type": "source-of", "src": "msg_bob_decision", "tgt": "kb_ratelimit_spec"}],
 "must_mention": ["msg_bob_decision"]}
```

```json
{"id": "rel_multi_07", "query": "Summarize the auth thread",
 "edge_types": ["crystallized-from", "overrides", "mentioned-by"],
 "cells": [/* 5 cells */],
 "edges": [/* 4 edges across 3 types */],
 "must_mention": ["dec_auth_v2", "msg_alice_42"],
 "must_not_assert": ["dec_auth_v1 is current"]}
```

3 multi-edge fixtures cover the realistic case where 3-4 edges of
different types must be reasoned about jointly.

## 3. Scoring rubric

**Per-fixture score:** {fully correct, partially correct, wrong}.

- **Fully correct** — answer's headline verdict matches `expected_answer_id`,
  AND every entry in `must_mention` appears (by id or unambiguous title),
  AND no entry in `must_not_assert` is asserted, AND no edge is invented
  that is not in the fixture.
- **Partially correct** — verdict matches but explanation omits one
  required mention; OR explanation is right but cites the wrong id at
  the verdict line.
- **Wrong** — verdict contradicts the edge (e.g., names the overridden
  cell as current), OR invents an edge, OR refuses to answer when the
  edges are unambiguous.

**Two graders, both required:**

1. **Rule-based grader (cheap, deterministic).** Regex-extracts cell
   ids from the answer. Checks `must_mention` ⊆ extracted_ids. Checks
   `expected_answer_id` is the first or only id in the verdict
   sentence. Checks `must_not_assert` patterns absent. Detects
   invented edges by looking for relationship verbs ("supersedes",
   "blocks", "depends on", "overrides") between id pairs not in
   `edges`. Fails closed: ambiguous → "partial."
2. **LLM-as-judge (DeepSeek, separate prompt).** Given `{query,
   edges, model_answer}`, judge produces `{verdict: full | partial |
   wrong, reason: str}`. Used as tiebreaker on rule-based "partial"
   and as cross-check on rule-based "full" (sample 10%).

**Aggregate metric:** `relationship_score = (#full + 0.5 × #partial) /
total`. Target: ≥0.85 for shipping. Below 0.70 → ship-blocking.

## 4. Required schema additions

The eval expects `kb_slice` payload entries to grow from
`{id, source, excerpt}` to `{id, source, excerpt, edges}` where:

```json
{
  "id": "dec_pool_v2",
  "source": "decision",
  "excerpt": "Bump Postgres pool to 50...",
  "edges": [
    {
      "type": "overrides",
      "target_id": "dec_pool_v1",
      "target_kind": "decision",
      "direction": "out"
    },
    {
      "type": "crystallized-from",
      "target_id": "msg_alice_42",
      "target_kind": "message",
      "direction": "out"
    }
  ]
}
```

`direction: "out" | "in"` so the LLM can read "I override X" vs "I am
overridden by X" without mutating the edge type. `target_kind` keeps
the LLM from having to look up the cell type from `cells[]`. Edge
list is bounded (cap at ~8 per cell) — the membrane-eligible neighbors
of any one cell are typically well under that. Shape is intentionally
flat to stay friendly to JSON-mode.

Schema implementation lives in retrieval slice 5 (the production wiring
slice). This eval can synthesize the payload directly from fixtures
without waiting for that.

## 5. Experimental matrix

Three configs at the same 30-fixture corpus:

- **Config R-A (cells only).** Strip `edges` from payload. Baseline:
  what does the LLM infer from co-occurrence alone?
- **Config R-B (cells + edges as structured metadata).** Full payload
  per §4. Edges as JSON list per cell.
- **Config R-C (cells + edges as natural-language hints).** Edges
  rendered as prose appended to each cell's excerpt:
  *"This decision overrides decision dec_pool_v1."* No structured field.

Optional fourth: **Config R-D (both).** Structured edges + a one-line
prose hint per edge. Tests whether the LLM benefits from redundancy.

**Prediction:**

- R-A scores 0.40-0.55 (LLM correctly orders some pairs by ts/wording
  but invents edges or misses overrides on conflicts).
- R-B beats R-A by +0.20 to +0.30. Structured fields are easier to
  parse than long prose for relationship reasoning.
- R-C is close to R-B but slightly behind (0.05-0.10) because prose
  edges compete with cell content for attention; LLM occasionally
  reads the hint as part of the cell's claim rather than meta.
- R-D ≈ R-B; redundancy doesn't add signal once structured edges are
  present.

If R-A ≥ R-B by more than 0.05, the axis itself is suspect (we'd be
measuring LLM coherence, not edge use) and the fixtures need
sharpening — likely by introducing more cells where co-occurrence
order is ambiguous.

## 6. Failure modes to watch

**False positives (LLM hallucinates edges not in payload).**
Detection: rule-based grader scans answer for relationship verbs
between id pairs and rejects any pair not in `edges`. LLM-judge
spot-checks. Mitigation in prompt: explicit *"Only assert
relationships that are listed in the `edges` field."*

**False negatives (LLM ignores given edges).** Detection:
`must_mention` list flags answers that omit edge-target ids when an
edge points to them. Pattern to watch: LLM gives the right verdict
but doesn't *explain* it via the edge — that's a partial.

**Edge-direction confusion.** LLM treats `overrides(A, B)` as
"B overrides A." Detection: paired fixtures with reversed edge
direction (same cells, edge flipped). If both fixtures get the same
verdict, the LLM is direction-blind. Add 5 such paired fixtures to
the 30.

**Multi-edge collapse.** With 4+ edges of different types in one
fixture, LLM picks the first / strongest and ignores the others.
Detection: the 3 multi-edge fixtures explicitly require 2+ edges in
`must_mention`.

## 7. Cost / time estimate

**LLM calls per axis run:**

- 30 fixtures × 3 configs (R-A/B/C) = 90 model calls.
- 30 × 3 × 0.1 (LLM-judge sample on rule-based "full") + 30 × 3 ×
  est. 0.3 (LLM-judge tiebreak on rule-based "partial") ≈ 36 judge
  calls.
- Total: ~126 DeepSeek calls per axis run.

**Token cost:**

- Each fixture is small (3-6 cells × ~150 tokens + edges + system
  prompt ≈ 2K tokens in, 500 tokens out). 90 model calls × 2.5K avg
  = ~225K tokens. Judge calls average 1K each → ~36K tokens. Total
  ~260K tokens.
- DeepSeek-Chat at ~$0.27/M input → ~$0.07 per axis run.
- Add R-D (optional fourth config) → ~$0.10.

**Comparison to existing eval per-run cost:** N.1.5 retrieval eval
costs ~$0.05/run at 2505 nodes (per Test 6 final summary). Relationship
axis costs ~$0.07-$0.10/run — comparable. Cheap enough to run on every
prompt-template change in the agent code.

**Time:** 90 × ~5s = 8 min for model calls + 36 × ~5s = 3 min for
judge ≈ 11 min wall time. Single afternoon for fixture authoring +
first run.

## 8. Open design questions

1. **Should fixtures use realistic-corpus excerpts or synthetic
   templates?** Realistic content tests prose comprehension alongside
   edge reading. Synthetic isolates the edge-reading variable. Lean
   toward synthetic for v1 — we already know realistic ≠ synthetic
   per Test 5; mixing both is a confound.
2. **Should leak rate be cross-checked here?** A fixture could include
   a membrane-suppressed cell + an `overrides` edge from a visible cell
   to it. Does the LLM mention the suppressed id even though its
   content is absent? Worth one or two cross-axis fixtures.
3. **Edge-cap value.** §4 caps `edges` at 8 per cell. Is this right?
   Real graphs may have hub cells with 30+ neighbors. Need a per-cell
   ranking (most-relevant 8) — not in scope for this axis but a
   prerequisite for slice-5 wiring.
4. **LLM-judge bias.** DeepSeek-grading-DeepSeek inherits the same
   circularity caveat as Test 5. Cross-provider judge (a Qwen or
   Anthropic-grade pass) would tighten the signal, but adds setup
   cost. Defer until R-A/R-B gap is established.
5. **Is "partial" too forgiving?** 0.5-weighting partials in the
   aggregate metric may flatter Config R-A. Consider a stricter
   variant: `relationship_score_strict = #full / total`, reported
   alongside the lenient score.
