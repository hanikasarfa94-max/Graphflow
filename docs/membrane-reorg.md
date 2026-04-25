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

## Next move (separate session, when prioritized)

1. Rename `MembraneIngestService` → `MembraneService`. Document the
   broadened role in its docstring.
2. Move `ConflictExplanationAgent` invocation into the membrane
   accept-path: when a candidate enters, run conflict detection
   against the cell snapshot before write.
3. Collapse `ConflictService.kick_recheck` (post-write detection) into
   the membrane pre-write check. Rule-based detection stays; the LLM
   explainer becomes a sub-step of the membrane's "explain why
   rejected" output.
4. Background heuristic: a periodic membrane sweep that scans recent
   group-room messages without IMSuggestion rows and proposes
   `wiki_entry` candidates the LLM didn't catch in real time.
