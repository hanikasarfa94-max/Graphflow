# Attention engine test report — N.1.5 follow-up

Compiled 2026-04-29 from four diagnostic experiments before committing to
Path B (§7.2 hybrid retrieval + §7.4 frecency on the v-Next critical
path). Goal: validate the recall plateau, characterize the noise floor,
and project production economics. **Result: stronger case for Path B
than the original analysis, plus a free win that ships independently.**

## TL;DR

1. **Variance is zero at temp=0.1.** Three identical runs give identical
   numbers to four decimal places. So the F1 swings between scales
   (0.821→0.800→0.850→0.800→0.850) are *real signal*, not noise — but
   they're small enough that scale-sensitivity is mild within the
   tested range.
2. **Adding `created_at` to the prompt lifts recall +0.137** (0.727 →
   0.864) at 200 nodes. Three of five chronic-miss queries recover.
   The LLM was time-blind, not too literal. **This is a 30-minute
   change with v-Next-baseline-quality impact** — should ship
   independently of any §7 work.
3. **Quality (F1, leak rate) holds across 125× corpus growth.** Config
   A's qualitative scaling is real, not a measurement artifact.
4. **The economic wall is the load-bearing reason for Path B.** At
   5000 nodes, Config A burns ~64% of $50/seat SaaS revenue on
   inference. §7.2 cuts that 18×. That's the case for shipping
   §7.2 + §7.4, not retrieval quality.

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
- **Realistic-corpus addendum** (separate run, also today): replaces
  RNG synthetic padding with DeepSeek-generated prose-quality content
  to verify Config A's numbers hold against realistic noise. See
  `realistic_corpus_addendum.md` once that experiment lands.
