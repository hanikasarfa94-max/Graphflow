# Demo — Moonshot Studios, *Stellar Drift Season 1*

**For:** showing potential users the canonical signal chain (`docs/vision.md §6`) in a lived-in context.

**Company:** Moonshot Studios — a 30-person indie game studio, Montreal. Five-year-old. Shipped two previous roguelikes (*Ember Hollow*, *Cinderbloom*). Currently in the final 4-week stretch on their biggest title yet.

**Project:** *Stellar Drift Season 1* — a 4-player co-op space-roguelike with permadeath, procedurally-generated runs, and boss encounters. Targeting Steam + Switch + PS5, launch in 4 weeks.

## The team (demo characters)

| User | Role | Profile |
|---|---|---|
| **Maya Chen** | CEO / Game Director | Emits vision + strategic signals. Sparse, decisive. |
| **Raj Patel** | Design Lead | Emits gameplay-feel signals. Obsessed with "fun first, system second." |
| **Aiko Nakamura** | Engineering Lead | Emits feasibility + technical-debt signals. Protective of the codebase. |
| **Diego Torres** | Art Director | Emits visual direction. Unruffled, tracks on plan. |
| **Sofia Rossi** | QA / Community Lead | Emits external-world signals — playtest data, community feedback. |
| **James Okoro** | Junior Engineer | 6 weeks in. Responds to assignments, still finding his profile. |

All use password `moonshot2026` for demo.

## The seeded state (what a judge sees on first load)

After running `scripts/demo/seed_moonshot.py`:

1. Six registered users
2. One project: *Stellar Drift Season 1* — created by Maya via intake, parsed through the agent pipeline (Requirement → Graph → Planning)
3. All six users are project members
4. ~5 older IM messages between the team, establishing context for the live demo moment

## The live moment — the canonical signal chain

The seeded history has set up a tension: Sofia's playtest report flagged that 3/5 external testers found the first boss "unfair" — 40% rage-quit rate. Aiko has already signalled that a design call is needed before touching code.

**This is where the live demo starts.** You drive it in two browser profiles.

### Step 1 — Raj posts the opening signal

Log in as **Raj** in Browser A. Type this into the IM pane:

> *"I think we need to drop the permadeath-for-bosses feature — playtesting shows it's too punishing and causes 40% rage-quit. We should make boss deaths meaningful but not run-ending."*

Wait ~2s. IMAssist metabolizes the raw text and produces a `decision`-kind suggestion with `action: drop_deliverable`, summary visible in the card. Confidence ~0.8.

### Step 2 — Aiko counters instead of accepting

Switch to Browser B, logged in as **Aiko**. She sees the message and the suggestion. Instead of clicking Accept or Dismiss, she clicks **Counter**.

Type this counter-framing:

> *"Permadeath is already wired through 3 systems — dropping it is a 2-week un-build. What if we keep permadeath but add a one-time 'memento' revive item as a midgame unlock? Threads the needle — keeps the stakes, reduces rage-quit."*

Send. Her message arrives with `↳ counter to earlier suggestion` above the bubble. Raj's original suggestion card ghosts to `↳ countered`.

### Step 3 — Raj accepts the counter

Back in Browser A. Raj sees Aiko's counter. The new suggestion card below her message carries her reframe. Raj clicks **Accept**.

Suggestion resolves. Both browsers light up with the ⚡ **Decision recorded** chip below Aiko's message. A `DecisionRow` has crystallized on the graph with lineage tracing back through both signals.

### What just happened (the thesis compressed)

- A human emitted a raw signal (confused, decision-laden).
- The LLM-on-edge metabolized it into a form the receiver could act on.
- The receiver didn't agree or disagree — they **counter-emitted** a reframed signal. This is the move that never happens cleanly in Slack.
- The original emitter accepted the better third option.
- The decision crystallized to graph state, with full provenance, visible to all edges simultaneously.
- No meeting was needed. Two creative leads resolved a scope conflict async in ~90 seconds.

This is not Notion-with-AI. This is not Slack-with-AI. This is the organism moving.

## Demo script notes for the presenter

- **Pacing:** aim for ~2 minutes total. Longer kills the punchline.
- **Don't over-narrate the AI.** Let the UI do the talking. When the ⚡ chip lights up on both browsers, pause. Don't explain. Let the judge feel it.
- **If IMAssist doesn't classify the first message as `decision`:** that's a prompt issue, not a product issue. Fall back to typing an explicitly decision-shaped message ("We should drop X because Y.") and try again.
- **If you have time after the chain:** scroll through Maya's original intake, the parsed graph (`/projects/{id}/graph`), and the generated plan (`/projects/{id}/plan`). Shows the product is a whole workflow, not just the IM trick.

## Variations (if asked)

Judges may push back: *"But what if the CEO disagrees?"* → Log in as **Maya**, she can observe or override. The graph records her override as another crystallization.

Or: *"What about external signals?"* → Gesture at `docs/vision.md §5.12` (membranes). Not built yet. Roadmap.

Or: *"Can this scale past a 6-person team?"* → The same primitive scales: signals, response profiles, crystallization, ripple. What changes at scale is the subgraph-slicing (`§5.5`), which routes relevance.
