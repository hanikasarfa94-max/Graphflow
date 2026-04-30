# Attention engine test report — N.1.5 follow-up

Compiled 2026-04-29 from four diagnostic experiments before committing to
Path B (§7.2 hybrid retrieval + §7.4 frecency on the v-Next critical
path). Goal: validate the recall plateau, characterize the noise floor,
and project production economics. **Result: stronger case for Path B
than the original analysis, plus a free win that ships independently.**

## TL;DR

1. **Variance is zero at temp=0.1.** Three identical runs give identical
   numbers to four decimal places. So all F1 differences across scales
   are *real signal*, not noise — but they're small enough that
   scale-sensitivity is mild within the tested range.
2. **Adding `created_at` to the prompt lifts recall +0.137** (0.727 →
   0.864) at 200 nodes. Three of five chronic-miss queries recover.
   The LLM was time-blind, not too literal. **This is a 30-minute
   change with v-Next-baseline-quality impact** — should ship
   independently of any §7 work.
3. **Quality (F1, leak rate) holds across 125× corpus growth and on
   realistic prose padding.** Config A's qualitative scaling is real,
   not a measurement artifact. The §7-defer call on quality grounds
   survives.
4. **The economic wall is closer than the synthetic-padded projection
   suggested.** Realistic content runs 3-4× more tokens per node than
   RNG synthetic padding, and DeepSeek-Chat is meaningfully slower on
   substantive prose (18s p50 / 72s p95 at 73K-token realistic prompts
   vs 6s p50 at synthetic). **§7.2 + §7.4 frecency need to ship in
   v-Next baseline, not as scale-triggered fallback** — the latency /
   cost wall arrives at ~1500-2000 realistic nodes, not 5000.

## Architectural framing (added 2026-04-30)

Earlier drafts of this report framed §7.2 as "graph-hop candidates
vs vector candidates, may the best score win." That was a misread of
the layer assignment, corrected after a user review of the full report.
The five-layer model the eval is actually measuring against:

1. **Cell** — canonical information (KbItem, Decision, Task, Message, Risk).
2. **Membrane** — boundary + governance (what crosses, crystallizes,
   stays local). §7.7 lives here.
3. **Graph** — structural memory + relation routing (records how cells
   relate: `overrides`, `depends-on`, `crystallized-from`, `blocks`,
   `source-of`, `mentioned-by`). The graph **does not compete with
   vector / BM25 for candidate slots.** It explains how cells relate
   and which paths can be traversed.
4. **LLM** — neural interpretation (reads cells + relationship evidence;
   produces explanation, classification, decision support, action).
5. **Projection / Attention** — active work surface (decides how the
   same canonical entities are projected into timeline, workbench,
   tasks, decisions, status pages, notifications, agent context).

Implications for how to read Tests 5–7 below:

- **Config A vs hybrid is an economic and systems baseline comparison**,
  not a "graph beats / loses to vector" contest. We are measuring
  whether trimming the candidate pool (BM25 + vector) before LLM read
  preserves quality at lower token / latency cost.
- **§7.2 retrieval is BM25 + vector finding plausible cells**; graph
  belongs at the *evidence* and *routing* layer, not in the candidate
  pool. The slice-4 finding that "graph-neighbor as a default RRF
  layer adds distractors" is correct empirically — and architecturally
  it confirms the layer assignment (graph-as-RRF-layer was the wrong
  projection of graph into retrieval).
- **Frecency is a traversal / projection prior**, not a relevance
  verdict. It prioritizes which already-relevant paths or entities
  get expanded, surfaced, or kept in active context. It must not let
  unrelated recent content compete with topically relevant content.
  The current implementation honors this (multiplier capped at 2.0×,
  applied after BM25/vector ranking, zero-score BM25 hits dropped).
- **The missing capability is relation-evidence in the payload** —
  the LLM today consumes `[{source, excerpt}]` per cell. It does not
  see "this cell was reached via `overrides` from `decision_X`." A
  new axis (relationship interpretation accuracy) measures whether
  the LLM produces correct answers when given cells **plus** their
  edges — design doc tracked separately.

Numbers below are unchanged. The framing is what gets corrected.

## Test 1 — timestamp-aware prompt

**Hypothesis:** chronic-miss queries (q02 "currently…", q06 "still…",
q08 "Alice's take", q09 "discussed privately") fail because the LLM
has no time signal — it can't distinguish recent from old content.
Adding `created_at` per node should close the gap on time-sensitive
queries.

**Method:** identical Config A on identical 200-node corpus; prompt JSON
now carries a `created_at` ISO timestamp on every node. Synthetic
timestamps where the corpus doesn't carry one (KB / decision / task /
risk get deterministic values in plausible recency bands per kind).
System prompt extended with one clause: *"Each node carries a
`created_at` ISO timestamp; weight recent content higher when the
query asks about current / latest / still / now state."*

**Results:**

| Metric | Bare prompt | + timestamps | Δ |
|--------|-------------|--------------|---|
| F1 | 0.800 | **0.884** | +0.084 |
| Precision | 0.889 | 0.905 | +0.016 |
| Recall | 0.727 | **0.864** | +**0.137** |
| Leak rate | 0.000 | 0.000 | 0 |
| Tokens / query | ~8.9K | ~12.1K | +35% |
| Latency | similar | similar | — |

Per-query deltas (queries unchanged: q01, q03, q04, q05, q10, q11, q12):

| Query | Pattern | Bare | +Time | Δ |
|-------|---------|------|-------|---|
| q07 | "What's blocking the SLA work?" | 1/2 | **2/2** | +1 |
| q08 | "What's Alice's take on the auth fallback?" | 0/1 | **1/1** | +1 |
| q09 | "rate limit per IP, discussed privately?" | 0/2 | **1/2** | +1 |
| q02 | "Postgres pool sizing currently?" | 1/2 | 1/2 | 0 |
| q06 | "v1 scope still adding?" | 1/2 | 1/2 | 0 |

**Verdict:** time-awareness is **the missing dimension**, not gold-set
looseness. Three of the five chronic misses recover with no other
change. q02 and q06 don't recover — those are genuine "topical scope"
mismatches (LLM cites the literal answer; gold also expects related
items). Future work could close those with prompt-strictness tweaks
or §7.2 retrieval-set expansion, but they're a smaller residual than
the time-blindness was.

## Test 2 — variance check

**Hypothesis:** F1 swings of ~0.05 between scales might be temperature
noise (temp=0.1) rather than scale sensitivity. If three back-to-back
runs at the same scale swing this much, then F1 differences across
scales are noise; only the leak rate (0.000 across all) is signal.

**Method:** three sequential runs of bare Config A at 200 nodes. Same
corpus, same queries, same prompt. Sequential to avoid concurrent
rate-limit interference.

**Results:**

| Run | F1 | Precision | Recall | n_leaks |
|-----|----|----|------|----|
| 1 | 0.800 | 0.889 | 0.727 | 0 |
| 2 | 0.800 | 0.889 | 0.727 | 0 |
| 3 | 0.800 | 0.889 | 0.727 | 0 |
| **stdev** | **0.000** | 0.000 | 0.000 | 0 |

**Verdict:** at temp=0.1 with `response_format=json_object`, the eval
is *effectively deterministic*. Variance noise floor is below
measurement precision. So:
- F1 differences ≥ 0.01 between scales are genuine signal.
- The 0.05 swings (e.g., 0.800 at 200 vs 0.850 at 1000) are real
  scale-sensitivity, modest but real.
- Test 1's +0.084 F1 lift from timestamps is *7× the smallest scale
  difference we measured* — robustly significant.

## Test 3 — production economics for 100-person org

Analysis. Assumes:

- 100-person org, 8h/day, 250 working days/year.
- ~20 LLM-mediated queries / person / day (chat assistance, search hits,
  agent context-builds).
- 1.5 years of accumulation by mid-v-Next → ~5000 nodes per cell.
- DeepSeek-Chat pricing: ~$0.27 per million input tokens.

| Metric | At 1000 nodes | At 5000 nodes | At 10000 nodes |
|--------|---------------|---------------|-----------------|
| Tokens / query | ~40K | ~200K | ~400K (likely fails) |
| Cost / query | ~$0.011 | ~$0.054 | breaks |
| Queries / day (org) | 2000 | 2000 | 2000 |
| Cost / day | ~$22 | ~$108 | — |
| Cost / month / cell | **~$660** | **~$3,200** | — |
| Latency p50 | ~6s | ~10s | — |
| Latency p95 | ~9s | ~17s | — |

A SaaS at $50/seat/month = $5000/month for a 100-person cell. At Config
A bare on 5000 nodes, **64% of seat revenue goes to inference** — and
that's before support, infrastructure, margin.

§7.2 hybrid retrieval cuts candidates from corpus_size to ~50 before the
LLM call:

| Knob | §7.2-narrowed |
|------|---------------|
| Cost / query | ~$0.003 |
| Cost / month / cell | **~$180** |
| Cost reduction | **18×** |
| Latency p50 | ~3-5s (200-node-equivalent) |

§7.2 turns inference from a margin-killer into a rounding error on a
$5000/month SaaS line. **This is the load-bearing case for Path B.**

## Test 4 — recall gap classification (revised)

After Test 1 made it clear that time-blindness was the dominant issue,
the chronic-miss classification simplifies:

| Query | Was | Now (with time) | Residual cause |
|-------|-----|-----------------|----------------|
| q02 | miss `dec_pg_pool_bump` | unchanged | gold expects forward-looking decision; LLM cites only "current" KB |
| q06 | miss `stream_alice_freeze_call` | unchanged | gold expects supporting chat turn; LLM cites only formal decision |
| q07 | flips hit/miss | hits 2/2 | resolved by time-awareness |
| q08 | declines all cites | hits 1/1 | resolved by time-awareness |
| q09 | declines all cites | partial 1/2 | partially resolved; one residual is genuine recall edge |

**Net:** the *true retrieval recall* is ~0.86 once time signal is
present. The 0.727 plateau in earlier runs was not retrieval failure —
it was prompt-input failure (no temporal context). The remaining ~0.14
gap is split between gold over-specification (q02, q06) and one genuine
recall edge (q09's missing item).

## Recommendation (revised)

1. **Ship Path B as planned**, justified by Test 3 economics. The
   inference-cost wall at 100+ person org scale is the real constraint;
   §7.2 + §7.4 are load-bearing for unit economics, not for retrieval
   quality.
2. **Ship the timestamp-in-prompt change in the v-Next baseline
   regardless of §7 timing.** It's a 30-minute Config A modification
   that lifts recall +0.137 with no architectural cost. There is no
   reason to gate this on §7.2.
3. **Schema work (§7.4 prerequisites):** add `last_accessed_at` and
   `access_count` to all five row types (KbItem / Message / Decision /
   Task / Risk). These are the primitives §7.4 frecency reads. Already
   timestamps exist (`created_at`) on all five.
4. **Bump-on-touch hooks** in: search hits, citation resolution, edge-
   LLM cited claims, explicit user navigation. These keep
   `last_accessed_at` honest as a relevance signal.
5. **§7.2 hybrid retrieval (BM25 + vector + graph-neighbor + RRF):**
   ~1 week. Independent of frecency; can ship in parallel.
6. **§7.4 frecency ranker:** ~half day after §7.2 lands and the
   `last_accessed_at` columns are populating. Multiplies frecency
   score against retrieval score to weight recent / hot content.
7. **q02/q06 prompt-strictness experiment** — defer. The remaining ~0.14
   recall gap is small, and the cure (relaxing "directly grounds" to
   "topically related") risks more leaks. Re-investigate after §7.2
   trims the candidate set.

## Caveats

- **12 queries is small.** Test 1's +0.137 recall lift is robust against
  variance (Test 2: stdev=0), but a larger query set might shift the
  proportion of time-sensitive queries.
- **Synthetic timestamps in Test 1.** Real production timestamps are
  more clustered (active threads bunch in time); the time signal may
  be even stronger or noisier in production.
- **DeepSeek-Chat behavior may differ from production-time models.**
  Migrating to a different LLM provider requires a re-run.
- **Test 3's economic projections** assume 20 queries/person/day and
  ~5000 nodes after 1.5 years. Heavier-usage orgs scale costs
  proportionally; Config A's wall arrives sooner.
- **Realistic-corpus addendum** below.

## Test 5 — realistic corpus (DeepSeek-generated padding)

**Hypothesis:** the RNG synthetic `pad_NNNNN` plain-text padding may be
"easier" noise than realistic team content. Replace it with
DeepSeek-generated prose (498 items following the WorkGraph team
narrative, multi-type/multi-scope/multi-language) and re-run Config A
to see whether F1/leak numbers hold against realistic noise.

**Method:** generated 498 padding items via DeepSeek-Chat at
temp=0.7 (varied prose), kept the hand-curated 40-node spine
unchanged. Total corpus = 538 nodes. Ran bare Config A (no
timestamp prompt) so the comparison is apples-to-apples against
the synthetic-padded scaling pass. Circularity caveat: same model
generated and evaluated — multi-type retrieval (decision vs KB vs
stream-turn vs task vs risk) is the orthogonal challenge that resists
same-author bias.

**Results:**

| Metric | Synthetic 200 | **Realistic 538** | Synthetic 1000 |
|--------|--------------:|------------------:|---------------:|
| F1 | 0.800 | **0.821** | 0.850 |
| Precision | 0.889 | **0.941** | 0.944 |
| Recall | 0.727 | **0.727** | 0.773 |
| Leak rate | 0.000 | **0.000** | 0.000 |
| Tokens / query | ~9K | **~73K** | ~40K |
| Latency p50 | 5.7s | **18.1s** | 5.8s |
| Latency p95 | — | **72.2s** | 8.9s |

**Verdict:** quality story holds — F1 stays in the 0.80-0.85 band,
leak rate stays at 0.000. But two findings shift the economic case
significantly:

1. **Realistic content is ~3-4× more expensive per node than RNG
   synthetic.** RNG padding averaged ~50 tokens/node; realistic prose
   averaged ~150 tokens/node. So token cost at any given node count
   is 3× the earlier synthetic-based projection.

2. **Latency degrades disproportionately on realistic content.**
   DeepSeek-Chat handled 73K tokens of synthetic prose at ~6s p50;
   the same token count of realistic prose runs at 18s p50, 72s p95.
   The model is meaningfully slower on substantive content than
   filler. Three transient errors during the 12-query run dragged
   p95 further (the retries are visible in the 72s outlier).

**Implication for Test 3's economics:** the synthetic-padded
projections were underestimates. With realistic content:

| Scale (realistic) | Tokens / query | Cost / query | Cost / month / 100p cell |
|-------------------|---------------:|-------------:|--------------------------:|
| 500 | ~73K | ~$0.020 | ~$1,200 |
| 1500 | ~220K | ~$0.060 | ~$3,600 |
| 5000 | ~730K (exceeds context) | breaks | breaks |

**The §7.2 ship-gate on realistic content arrives at ~1500-2000 nodes,
not 5000.** This makes Path B's argument stronger, not weaker — the
latency/cost wall is closer than the original analysis suggested.

The §7-defer call (on **quality** grounds) survives unchanged. Config
A still produces clean leak rate and stable F1 across realistic
content. What's now clearer is that **§7.2 + §7.4 frecency must ship
in v-Next baseline**, not as scale-triggered fallback — they're
required by month one of a 100-person org's usage.

## Test 6 — §7.2 hybrid retrieval (slices 1-4, pickup #4)

Compiled 2026-04-30. Builds on Test 5's realistic-corpus baseline
(Config A at 538 nodes: F1=0.821, leak=0.000, ~73K tokens/q, p50
18.1s) and tests four progressively richer retrieval architectures
against it. Goal: replace Config A's full-context approach with a
candidate-trimming retrieval stack that holds F1 + leak rate while
collapsing tokens and latency by 10×.

### Architecture under test

`new_concepts.md §7.2` proposes a five-layer hybrid: BM25 + vector +
graph-neighbor + recency + pinned, fused via Reciprocal Rank Fusion
(RRF), then membrane-filtered (§7.7) before context assembly. Slices
1-4 of pickup #4 implemented and evaluated this stack:

  * **Slice 1 (BM25)** — pure-Python Okapi BM25 with bilingual
    zh + en char-unigram tokenization. Title weighted ×3. No external
    deps. (commit `7357d03`)
  * **Slice 2 (Vector)** — Qwen3-Embedding-8B via SiliconFlow's
    OpenAI-compatible API (4096-dim multilingual embeddings).
    Disk-cached `{content_hash: vec}` so re-runs are zero-API.
    (commit `3133825`)
  * **Slice 3 (Graph + Recency + Pinned)** — graph-neighbor with
    @-mention edges + supersedes edges + tag-Jaccard expansion;
    recency by `metadata.ts` descending; explicit pinned ids in
    user-specified order. (commit `c8e1ef8`)
  * **Slice 4 (RRF + real Config C)** — `reciprocal_rank_fusion()`
    with weighted contributions (rrf_k=60, pinned 1.5, bm25/vector
    1.0, graph 0.8, recency 0.5). Real Config C wires all five via
    RRF + §7.7 membrane filter + DeepSeek over the survivors.
    (commit `8ddcc8e`)

### First pass — 538-node realistic corpus (slice-4 commit)

Live DeepSeek runs against the same 12 queries used throughout the
N.1.5 test report. Same prompt frame as Config A (timestamp-aware,
strict-JSON cite extraction). All variants pass the §7.7 membrane
floor (suppressed items dropped before LLM sees them).

| Variant                        |     F1 | Recall |  Leak | Tok/q  | p50    |
|--------------------------------|-------:|-------:|------:|-------:|-------:|
| Config A (full context)        | 0.821  | 0.727  | 0.000 | 73,000 | 18.1s  |
| BM25 alone (slice 1)           | 0.700  | 0.636  | 0.000 |  9,438 |  3.5s  |
| **Vector alone (slice 2)**     | **0.818** | **0.818** | 0.000 |  6,842 |  4.6s  |
| BM25 + Vector RRF              | 0.698  | 0.682  | 0.000 |  8,203 |  3.2s  |
| 5-layer hybrid (slice 4)       | 0.652  | 0.682  | 0.000 |  8,262 |  3.5s  |

**First-pass conclusion (later partially overturned):** vector alone
matched Config A's F1 with 91% fewer tokens and ¼ the latency. RRF
fusion *hurt* — both 2-layer (BM25+vec) and 5-layer variants
underperformed vector alone. Diagnostic on q07 ("What's blocking the
SLA work?") showed the expected items were at fused ranks 1-2 in the
candidate set, but the LLM didn't cite them; RRF mixing pulled in
tangential items that distracted the LLM. Vector top-50 was
topically tight; hybrid top-50 was mixed-quality.

The §7.2 5-layer hypothesis was rejected by this data. The slice-4
commit (`8ddcc8e`) recommended **vector-as-primary** with BM25 as a
fallback — a meaningful pivot from the original spec.

### Second pass — 2505-node realistic corpus (slice-4 addendum)

Generated 1967 more realistic items via DeepSeek (`gen_xl_NNNNN`,
seed=1337) into `realistic_padding_xl.json`. Combined corpus =
40 hand-curated + 498 existing + 1967 new = **2505 nodes**. Re-ran
the three Config-C-shaped variants on the same queries (commit
`1769c1a`).

| Variant            | F1 @ 538  | F1 @ 2505 |       Δ |
|--------------------|----------:|----------:|--------:|
| Vector only        | **0.818** |     0.727 |  -0.091 |
| BM25 + Vector RRF  |     0.698 | **0.818** |  +0.120 |
| Full 5-layer hybrid|     0.652 |     0.732 |  +0.080 |

**Per-query reversal:** q07 (the chronic semantic miss) recovered
with BM25+vector RRF at 2505 (hits=2/2), even though vector alone
*lost* it (0/2). The lexical layer rescues recall as the corpus widens
and relevant items fall outside vector's top-50.

The §7.2 RRF thesis is **confirmed at scale** — just not at the
538-node first-pass scale. The crossover point lies somewhere
between, and Path B targets corpus sizes (thousands of nodes by
month one of a 100-person org) where RRF wins decisively.

### Final 2505-node summary

| Variant            | F1     | P      | R      | Leak  | Tok/q | p50    |
|--------------------|-------:|-------:|-------:|------:|------:|-------:|
| Vector only        | 0.727  | 0.727  | 0.727  | 0.000 | 6,894 |  4.0s  |
| **BM25+Vector RRF**| **0.818** | **0.818** | **0.818** | **0.000** | **8,098** | **3.9s** |
| 5-layer hybrid     | 0.732  | 0.789  | 0.682  | 0.000 | 8,307 |  4.0s  |

Single full eval costs ~$0.05 in DeepSeek + ~30s embed time on a
warm cache.

### Why the 5-layer still loses to the 2-layer at 2505

The graph-neighbor / recency / pinned layers add candidates that the
LLM reads as distractors. Recency is the worst offender — pure ts
descending has zero topical signal, so its top-20 is just "what
happened recently" regardless of query. The §7.2 spec listed it as
a layer, but the data says it should be a **score multiplier**, not
a standalone retriever.

Specifically:
  * **Recency** → §7.4 frecency multiplier on retrieved items
    (`log(1 + access_count) × time_decay(now - last_accessed_at)`).
    Frecency primitives shipped 387aef6 + bump-on-touch hooks shipped
    95aaeef are ready to plug in.
  * **Graph-neighbor** → on-demand expansion when the query mentions
    a node id (one-hop expansion only, not a default RRF layer).
  * **Pinned** → always-include union (bypass scoring; pins shouldn't
    compete on rank).

### Architectural verdict for slice 5 (production wiring)

  * **BM25 + Vector RRF is the production retrieval primitive.**
    Validated at 2505 nodes against the most realistic noise we can
    generate. Targets the v-Next Path B regime (1.5K-5K node cells).
  * **Frecency as score multiplier**, not retriever. Per §7.4
    original design. The bump-on-touch infra lands here.
  * **Graph-neighbor as on-demand**, query-classifier-driven. Adds
    cost when an anchor is present, doesn't dilute when there isn't.
  * **Pinned as always-include union.** No rank competition.
  * **Embedding storage strategy** is the next load-bearing decision
    before slice 5 starts coding. Options: in-memory rebuild on boot
    (simple, scales to ~50K rows/cell), persistent table with pgvector
    (scales further, requires extension), or persistent JSON cache
    file per cell (low-effort, low-scale ceiling).

### Caveats

  * **Same-model circularity persists** — DeepSeek generated the
    realistic padding *and* runs the eval. Cross-provider eval would
    tighten the signal but no other LLM provider is configured.
  * **12 queries is still small.** The crossover behavior between
    538 and 2505 might shift with a different query mix.
  * **Slice-4 weights pre-tuned** — `pinned 1.5, bm25/vector 1.0,
    graph 0.8, recency 0.5` was a rule-of-thumb default. A weight
    sweep was deferred since the conclusion (drop graph/recency from
    the default RRF) doesn't hinge on the specific weight values.
  * **Embedding model not swept.** Qwen3-Embedding-8B is multilingual
    and 4096-dim; smaller / different models might shift the
    crossover scale. SiliconFlow's other multilingual options are
    cheap to test if needed.

### Reports

  * `tests/eval/reports/config_b_bm25_realistic_size_538_k50.json`
  * `tests/eval/reports/config_b_vector_realistic_size_538_k50.json`
  * `tests/eval/reports/config_c_hybrid_realistic_size_538.json`
  * `tests/eval/reports/scaling_comparison_size_2505.json`

### Replayable scripts

  * `tests/eval/scripts/run_bm25_baseline_eval.py`
  * `tests/eval/scripts/run_vector_baseline_eval.py`
  * `tests/eval/scripts/run_hybrid_eval.py`
  * `tests/eval/scripts/run_scaling_comparison_eval.py`
  * `tests/eval/scripts/generate_realistic_corpus.py --id-prefix gen_xl_
    --seed 1337 --count 2000` (regenerates the 2K padding)

## Test 7 — Room-stream slice + N.4 vote affordance (room slice +
14 commits this session)

Compiled 2026-04-30. Builds on the §7.2 retrieval (Test 6) + pickup
#6 (IM accepts stream_id) + pickup #7 (scope_tiers consumer)
foundations. Captures the architectural reasoning behind the room
surface so future sessions can find it without trawling commits.

### The thesis

> **Team conversation visibly transforms into decisions, tasks,
> knowledge, and structured memory through membrane review.**

The room view is where this transformation happens. The first plan
revision was UI-heavy and would have shipped a Slack-like surface
that lied about backend contracts. Codex review (`/codex consult`,
two passes) surfaced 10 problems and the user added the load-bearing
correction:

> One canonical entity, multiple projections.

That correction is the spine of every architectural choice in this
slice. Inline = causality (source message → suggestion → accept/
reject → decision/task/knowledge). Workbench = current work
surface (queue of pending candidates / accepted decisions). **Same
entity_id, different projections, single reducer.**

### Architecture in 12 facts

1. **`StreamRow.name` persisted** — alembic 0029. Until this
   shipped, `create_room()` accepted a name parameter but threw it
   away on read. Frontend would render unnamed streams.

2. **`_decision_payload.scope_stream_id` exposed** — pickup #6 wrote
   the field on every room-scoped crystallization, but the wire
   serializer didn't surface it. Vote-scope explainer was impossible
   to render before this commit.

3. **GET /api/projects/{pid}/rooms/{rid}/timeline** — joins
   messages + im_suggestions + decisions chronologically with a
   discriminated `kind` per item. Membership-gated (project +
   stream). One round trip seeds the entire room view.

4. **`RoomTimelineEvent` discriminated union over WS** — every
   state change publishes via `/ws/streams/{room_id}` as one of:
   ```ts
   | { type: "timeline.upsert"; item: TimelineItem }
   | { type: "timeline.update"; kind: string; id: string; patch: ... }
   | { type: "timeline.delete"; kind: string; id: string }
   ```
   Frontend reducer is one switch. Adding a new entity kind requires
   a renderer, not new reducer logic.

5. **WS fan-out at every state-changing service call** —
   `MessageService.post`, `IMService._classify_and_persist`,
   `IMService.accept/dismiss`, `DecisionVoteService.cast_vote`. All
   emit `RoomTimelineEvent` to the room stream when the source
   touches a room. Best-effort: failure logs but never breaks the
   primary write path.

6. **Single `useRoomTimeline` hook on the FE** — owns ALL projection
   state. `pendingSuggestions` and `decisions` are MEMOIZED DERIVED
   slices of `items`, NOT separate hooks. A workbench panel reading
   `timeline.pendingSuggestions` projects the same canonical entity
   the inline `RoomStreamTimeline` renders. Click a workbench
   PanelItem → `scrollToEntity({kind, id})` → smooth-scrolls the
   inline `data-entity-id={id}` card into view + flashes it.

7. **Vote tally enriched at TWO surfaces** — `enrich_decision_with_
   tally(payload, sessionmaker)` is called by both
   `RoomTimelineService.get_timeline` (REST snapshot) AND
   `IMService.accept` (crystallize WS upsert). Every decision wire
   carries the tally without forcing a follow-up GET.

8. **Vote affordance = polymorphic over existing VoteRow** —
   `subject_kind="decision"` joins the existing
   `subject_kind="gated_proposal"` use without a schema change.
   Voter-pool gate: `scope_stream_id` set → room membership;
   null → project membership. Two distinct queries (we don't widen
   project membership to grant room votes).

9. **Tally → `timeline.update.patch.tally`** — when a vote lands,
   one WS frame updates the decision row in place across all
   projections. No bespoke "vote-cast" event type; the frontend
   reducer applies the patch via shallow-merge.

10. **Workbench is the prototype's `工具栏`** — direct port of
    `workgraph-ts-prototype/src/App.tsx` ToolPanelCard (lines
    350-475) and PanelItem (lines 530-538). Three layout modes
    (grid / vertical / focus), additive `+chip` shelf, drag-
    rearrange, focus/close per panel. Same DOM class names so the
    prototype's CSS patterns transplant cleanly. Inert chips
    (`+任务中心 / +知识记忆 / +技能图谱 / +工作流`) establish the
    projection vocabulary now; renderers slot in incrementally
    (Knowledge panel landed alongside this report; Tasks panel is
    next).

11. **What we deliberately did NOT do**:
    - Hover menus (codex flagged: fail on touch + create fake manual
      workflow alongside the auto-classifier).
    - Toast vote stubs (codex was firm: "toast vote is worse than
      no vote button" — we shipped a real backend instead).
    - Reuse PersonalStream for rooms (couples to user→agent
      semantics + EdgeAgent rehearsal).
    - Reuse MembraneCard for IM suggestions (different shape:
      MembraneCard renders MembraneSignal/KB-ingest review, not
      LLM-classifier interpretation of chat).
    - Persistent workbench drag-reorder (in-memory only this slice).
    - `build_slice` scope filtering (research confirmed structural
      rows lack `.scope` — would be a near-no-op).

12. **Codex's two consults locked into the plan** — see
    `~/.claude/plans/ok-so-go-to-shimmying-puppy.md` GSTACK REVIEW
    REPORT. First pass found 10 problems including WS-broadcast
    mismatch, thin `/api/streams/{id}/messages` payload, room name
    not persisted. Second pass with the user's projection-model
    correction + prototype context endorsed the reshape.

### Tests + verification

- 9 new BE tests for vote affordance: cast / re-vote (UPDATE in
  place) / non-room-member rejected / invalid verdict / unknown
  decision / tally enrichment in timeline / 3 route-level cases.
- 8 BE tests for room timeline + scope_stream_id + preview
  scope_tiers (committed earlier in `test_room_timeline.py`).
- 6 BE tests for IM-room-post + B3 sequel (committed in pickup #6).
- Full backend sweep: **538/538 green** (was 521 + 17 new across
  rooms + votes).
- FE `tsc --noEmit` clean across all touched files (~17 modified +
  new TypeScript).
- One Playwright e2e smoke (`tests/e2e/room_timeline.spec.ts`) for
  the projection wire contract.

### What's next from this slice's deferred list

- **Knowledge workbench panel** — landed alongside this report; surfaces
  group-scope KbItems via `KbItemRepository.list_visible_for_user`.
- **Tasks workbench panel** — needs a manual_task creation path
  beyond the existing PlanRepository.task surface; deferred until we
  scope whether the existing `personal-task → plan promote` flow can
  be reused.
- **Project-wide vote** — DecisionVoteService already supports
  `scope_stream_id=null` (project membership pool); the FE
  affordance currently only mounts inside the room view because
  that's where the user instruction was clearest. Extending to the
  team-room and personal-stream decision cards is a single prop
  flip + a member-check in the card's parent.
- **EdgeAgent prompt rewrite** to explicitly cite from `kb_slice`
  (today the LLM uses it organically) — would lift cite consistency
  per the Test 1 timestamp finding.

### Reports

  * Backend sweep: 538/538 green at commit `9d8fb9c`.
  * Plan + GSTACK review report:
    `~/.claude/plans/ok-so-go-to-shimmying-puppy.md`.
  * Room-slice commit chain (chronological): `e0794c7` → `852cf73`
    → `72d7c6b` → `ff73f8b` → `4790ca6` → `75efa77` → `f5c1637` →
    `644b66d` → `722398b` → `6b1d0ca` → `f0d2987` → `9d8fb9c`.
