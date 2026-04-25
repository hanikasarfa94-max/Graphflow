# Membrane reorg — direction (2026-04-25)

Captured from a user clarification on agent responsibilities. This is a
direction note, not yet a build plan. Most of the code stays as-is for
now; the new `wiki_entry` flow shipped today already lives on the
membrane line of thinking, and future agent consolidation can land
incrementally.

## The model

The **cell** = the project's canonical knowledge center. Concretely:

- `ProjectGraphRepository` nodes (deliverables, goals, risks, milestones)
- `PlanRepository` tasks
- `DecisionRow`s (crystallized decisions)
- `KbItemRow scope='group', status='published'` (group KB / wiki)
- `MembraneSignalRow status='approved'` (legacy wiki + ingested signals)

The **membrane** = the boundary that decides what enters the cell.
Inputs to the membrane:

1. **External signals** — URLs, fetched docs, future fetch agents.
   Today: `MembraneIngestService` + `MembraneAgent.classify`.
2. **User contributions** — personal notes promoted to group, IM
   messages nominated as wiki entries, decisions raised by humans.
   Today: `KbItemService.promote_to_group`, the new
   `IMSuggestion(kind='wiki_entry')` flow, gated proposals.
3. **Cross-team routing replies** — when a routed reply from B lands
   on A's stream, it implicitly re-enters the cell context for A.
   Today: `RoutingService.reply` + `PersonalStreamService.handle_reply`.

When a candidate hits the membrane, the membrane's job is one of:

- **accept** → write into the cell at appropriate scope
- **reject** → log + drop, optionally explain to the proposer
- **defer to human** → queue as a suggestion for owner approval
- **conflict-resolve** → detect that the candidate contradicts
  existing cell content; trigger the conflict-resolution flow
  before deciding accept/reject

The conflict-resolution flow today is `ConflictService` — detection
runs over the EXISTING graph (internal contradictions), not at the
membrane boundary. The user's reframe is: conflict detection should
fire at the membrane, against the candidate-vs-cell pair, before the
candidate joins the cell. That makes "conflict" a sub-step of
"membrane decision," not a separate agent.

## Why merge ConflictAgent into the membrane

Today's split:
- `ConflictExplanationAgent` (LLM) explains rule-detected conflicts in
  the existing graph — runs after a write that broke an invariant.
- `MembraneAgent` (LLM) classifies inbound external signals.

Both are checking "is this consistent with what we know" — just at
different points in the lifecycle. Merging them into one **Membrane
agent** with a unified contract reduces the number of LLM personas the
team has to reason about, and matches the user's mental model of the
cell as a single boundary-protected entity.

## Out of scope for v1 (today)

- No code refactor of `ConflictService` or `ConflictExplanationAgent`.
  They keep their current rule-engine + post-write-explain role.
- No rename of `MembraneIngestService` to a broader name.
- No data migration of wiki rows from `MembraneSignalRow` into
  `KbItemRow`. The KB tree page already shows both.

## What did ship today (2026-04-25) that aligns with this model

- `IMSuggestion(kind='wiki_entry')` + `proposal.action='save_to_wiki'`.
  IM-assist agent (one of the membrane personas in spirit) nominates
  load-bearing group-room messages for promotion. Owner approves
  through the existing accept/dismiss flow.
- `IMService._apply_proposal` handles `wiki_entry` → creates
  `KbItemRow scope='group', source='llm', status='published'`.
- `propose_wiki_entry` skill on the EdgeAgent — same primitive,
  callable from a personal stream agent loop.
- `POST /api/projects/{id}/messages/{msg_id}/save-as-kb` for manual
  override (a user can also nominate without waiting for the LLM).

These three paths all converge on the same `KbItemService.create`
call, which is the membrane → cell write boundary. That convergence
is the foundation of the eventual unified membrane agent.

## v2 — the GitHub PR model

The clearest mental model (from a 2026-04-25 user clarification):

| GitHub | Membrane / cell |
| --- | --- |
| Fork | Personal-scope `KbItemRow` + any draft sitting in the user's own surface |
| `main` branch | The cell — group-scope items, graph nodes, decisions |
| Open PR | `promote_to_group` / IM-accept / route-confirm / decision-crystallize — every "this should join the cell" gesture |
| CI checks | Conflict detection against current cell snapshot (rule engine + LLM explainer) |
| Auto-merge "trivial" | Membrane decides the candidate is text-only / formatting / typo → accept silently |
| Request review | Membrane decides: semantic delta / contradicts an existing claim → defer to owner with explanation |
| Closed without merge | Reject with reason |
| PR description / linked issues | The "clarify" sub-step — membrane prompts the proposer when intent isn't obvious from the diff |

The "clarify" step is the part nobody else has built well. Most tools
either auto-merge everything (Notion-style) or queue everything for
human review (Confluence-style). Membrane sitting in between —
"this looks like a semantic change to the X convention; can you
confirm you mean to override the prior decision in D-37?" — is what
turns this from a notes app into something that actually protects
the cell.

### Code shape (target)

One unified entry point:

```python
class MembraneService:
    async def review(
        self,
        *,
        candidate: Candidate,        # the proposed change (KB item, decision, edge, …)
        cell_snapshot: CellSnapshot, # what's in the cell right now
        proposer_user_id: str,
    ) -> MembraneReview:
        ...

@dataclass
class MembraneReview:
    action: Literal["auto_merge", "request_review", "request_clarification", "reject"]
    reason: str
    diff_summary: str | None = None    # human-readable "what changed"
    clarify_question: str | None = None  # populated when action='request_clarification'
    conflict_with: list[str] | None = None  # node ids the candidate contradicts
```

Every promote path calls `MembraneService.review()` and acts on the
result. The four actions correspond to GitHub PR outcomes:
- `auto_merge` → write to cell directly + log
- `request_review` → queue as `IMSuggestionRow` (existing primitive,
  reused for KB / decision / edge promote paths)
- `request_clarification` → open a thin Q&A back-channel with the
  proposer (new primitive — could ride on the personal stream as a
  `kind='membrane-clarify'` message)
- `reject` → log + notify proposer with reason

### Why this is achievable incrementally

Today's three trigger paths (IM-assist auto-classifier, EdgeAgent
`propose_wiki_entry` skill, manual save-to-wiki button) all already
converge on `KbItemService.create`. The membrane review function
slides in front of that single call without changing the trigger
paths. Same pattern for `RoutingService.dispatch`,
`DecisionService.crystallize`, etc.

The conflict detection already exists in `ConflictService`. Stage 2
moves its invocation from "post-write recheck" to "pre-write membrane
review" — same rules, different timing.

### Migration order (tentative)

1. **Stage 1 — rename + docstring**. `MembraneIngestService` →
   `MembraneService`. Broaden the docstring to describe the cell /
   boundary model. No behavior change.
2. **Stage 2 — extract review() shell**. Add the empty
   `MembraneService.review()` method that today just does
   `return MembraneReview(action='auto_merge', reason='no checks yet')`.
   Wire `KbItemService.create` to call it. Same path for promote.
3. **Stage 3 — wire conflict detection**. Pull `ConflictService.recheck`
   logic into `review()` for the relevant candidate kinds. Old
   post-write recheck stays as a backstop until parity is verified.
4. **Stage 4 — `request_review` action**. When review returns
   `request_review`, create an `IMSuggestionRow(kind='membrane_review')`
   instead of writing. Owner accept = approval = real write. Today's
   `wiki_entry` flow becomes a degenerate case of this.
5. **Stage 5 — `request_clarification`**. New `kind='membrane-clarify'`
   stream message. Proposer sees a Q from the membrane, replies, the
   reply re-enters the same `review()` with the clarification
   appended to the candidate. The Q&A back-channel lives in the
   proposer's personal stream — never in DM, never in the cell.
6. **Stage 6 — collapse the conflict agent**. Once stage 3 + 4 are
   stable, `ConflictService.kick_recheck` becomes a no-op (post-write
   recheck only runs as paranoia mode). `ConflictExplanationAgent`
   moves to be the "explain why" sub-component of the membrane's
   review output.

Each stage is independently shippable and reversible. Stage 2's
shell is the load-bearing change — once `review()` exists in the
write path, every later stage is just filling in its body.

## Original next-moves (subsumed by the v2 plan above)

1. Rename `MembraneIngestService` → `MembraneService`. (= stage 1)
2. Move `ConflictExplanationAgent` invocation into the membrane
   accept-path. (= stage 3)
3. Collapse `ConflictService.kick_recheck`. (= stage 6)
4. Background heuristic: periodic membrane sweep that scans recent
   group-room messages without IMSuggestion rows and proposes
   `wiki_entry` candidates the LLM didn't catch in real time. (still
   independent — runs at the IM-assist layer, not the membrane.)
