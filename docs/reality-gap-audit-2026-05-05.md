# Reality Gap Audit - 2026-05-05

Purpose: catch gaps between the GraphFlow product thesis and what the
current code actually enforces. This is not a feature wishlist. It is a
QA map for places where the noun exists in the product, but the shipped
behavior may still be advisory, stubbed, partial, or easy to miss in
dogfood.

Current baseline: repository HEAD `b71e595` plus the local Membrane Agent
M1 work in progress.

## Audit Method

For every load-bearing product claim, ask five questions:

1. What code path enforces it?
2. Is it blocking, advisory, display-only, or absent?
3. What user action is the smallest counterexample?
4. What automated test would fail if the claim regressed?
5. What debug surface lets us inspect it without guessing?

Use these labels:

- `solid`: enforced by code and covered by tests.
- `partial`: real code exists, but only for some paths or statuses.
- `advisory`: code notices but does not block mutation.
- `display`: UI/projection only; not source of truth.
- `stub`: named in code/docs, not behaviorally wired.

## P0 Gaps

### 1. Pending-review knowledge can still pollute agent context

Claim: Membrane prevents unapproved objects from entering shared team
context.

Reality: `RetrievalService.retrieve_kb_items()` and `SkillsService._kb_search`
exclude `archived`, `draft`, and `rejected`, but not `pending-review`.
That means externally ingested rows held by Membrane as `pending-review`
can still be returned to `kb_search` / `candidate_set` and fed to Edge
as context.

Why this matters: this is the same class of failure as the KB conflict
bug. The UI can say "awaiting review" while the agent already reasons
from it.

Modify spec:

- Introduce a canonical retrieval status whitelist, not a blacklist.
- For user-authored KB: only `published`.
- For ingest KB: only statuses that mean "approved as context". Decide
  whether that is `approved`, `routed`, or only one of them. Do not
  include `pending-review`.
- Apply the same whitelist in:
  - `RetrievalService.retrieve_kb_items`
  - `RetrievalService.candidate_set`
  - `SkillsService._kb_search_substring`
  - any direct KB pretext builder
- Add tests:
  - `kb_search_excludes_pending_review`
  - `candidate_set_excludes_pending_review`
  - `edge_context_excludes_pending_review`

### 2. Membrane Agent pretext-build failure currently auto-merges

Claim: Membrane Agent failure should fail closed.

Reality: `MembraneAgentReviewer.review_candidate()` itself fails closed
on invalid LLM output. But `_agent_review_kb_candidate()` catches a
pretext-build exception and returns `None`, which lets the caller
continue to `auto_merge`.

Modify spec:

- Pretext build failure for a shared-memory candidate must return
  `request_review`, not `None`.
- The only allowed skip-to-auto-merge case is a successfully built
  packet with no relevant `retrieved_context` and no relevant
  `recent_decisions`.
- Add a test where `_build_kb_review_packet` raises and the KB item
  lands as `draft`.

### 3. Membrane review still falls through for known-but-unimplemented kinds

Claim: all objects entering the cell cross the same boundary.

Reality: `CandidateKind` includes `manual_project` and `manual_room`, but
`review()` returns `auto_merge/no_check_for_kind` for unhandled kinds.
Room creation explicitly has a TODO saying it is not routed through
Membrane yet. `decision_crystallize` is advisory-only.

Modify spec:

- Unknown or known-unimplemented `CandidateKind` must not silently
  `auto_merge`.
- Use either:
  - `request_review` with reason `kind_not_implemented`, or
  - reject at type/route level until the path is wired.
- Room creation must call `MembraneService.review(kind="manual_room")`
  before persistence, or remove `manual_room` from `CandidateKind` until
  it is real.
- Add tests:
  - `review_unknown_known_kind_fails_closed`
  - `create_room_calls_membrane`
  - `create_room_membrane_request_review_defers_creation`

## P1 Gaps

### 4. KB Membrane Agent M1 is real, but still narrow

Claim: Membrane has semantic teeth.

Reality: M1 only runs for `kb_item_group`, only after deterministic
checks, and only against a simple overlap pretext built from existing
published rows plus recent decisions. It does not yet reuse the richer
RRF/BM25 retrieval path and does not scan existing polluted rows.

Modify spec:

- Keep M1 as a good first slice, but mark it `partial`.
- Replace simple overlap pretext with the same retrieval primitive used
  by `kb_search`, filtered to canonical statuses.
- Include same-folder siblings and recent decisions in the packet.
- Add an owner-visible one-shot audit for existing group KB conflicts:
  it flags, never auto-demotes.

### 5. Task promote has no semantic Membrane Agent

Claim: tasks flow between humans, boosted by AI.

Reality: task promotion uses deterministic checks: duplicate title,
budget warning, assignee-coverage warning, orphan downstream warning.
It does not ask the Membrane Agent whether a task semantically duplicates
another task, contradicts the latest requirement, reopens intentionally
closed work, or depends on stale KB.

Modify spec:

- Add M3 `task_promote` packet:
  - candidate task fields
  - latest requirement
  - active plan tasks
  - done/cancelled sibling tasks
  - linked KB/decision refs if present
  - warnings from fixed checks
- Blocking shapes:
  - semantic duplicate active task
  - contradicts latest requirement or decision
  - reopens done/cancelled work without explicit reopen intent
  - depends on rejected/draft/pending-review KB
- Also wire `handle_clarification_reply` for `task_promote`, not just KB.

### 6. Decision Membrane is advisory-only

Claim: decisions are load-bearing graph state.

Reality: `decision_crystallize` always returns `auto_merge`. Warnings
may be surfaced, but the graph still accepts the decision even if it
overlaps a prior decision or lacks rationale.

Modify spec:

- Keep human-approved gates fast, but do not treat all upstream gates as
  equivalent.
- Add M4 modes:
  - `advisory_only` for low-risk paths
  - `request_review` for contradictions/supersession ambiguity
  - `request_clarification` for missing scope/rationale in low-context
    crystallization
- Add tests where a decision contradicts a prior decision and does not
  mint a new `DecisionRow` until owner review.

### 7. Edge prompt schema is out of sync with executable tools

Claim: Edge can use the product's tool surface.

Reality: Python allows `propose_wiki_entry`, `active_tasks`, and
`propose_task`, but the prompt's JSON schema still lists only
`kb_search`, `recent_decisions`, `risk_scan`, `member_profile`,
`why_chain`, and `routing_suggest`.

Modify spec:

- Generate the prompt schema list from the Python allowed-tool list, or
  add a test that compares prompt text to `_ALLOWED_TOOL_NAMES`.
- Add examples for:
  - save-to-wiki via `propose_wiki_entry`
  - "what are my tasks" via `active_tasks`
  - task draft via `propose_task`

### 8. Flow Packets are not yet task visibility

Claim: tasks flow between humans, with agents on every edge.

Reality: Flow Packets currently project routed signals, KB draft review,
and handoff drafts. They do not yet project normal plan tasks, personal
task drafts, blocked tasks, review tasks, QA tasks, or task handoffs.

Modify spec:

- Add task-related packet recipes only after defining lifecycle semantics:
  - `task_promote_to_plan`
  - `task_blocked_by_human`
  - `task_review_request`
  - `task_handoff`
  - `task_waiting_on_decision`
- Keep "Flow Stage is display, not source of truth": derive from
  `TaskRow.status`, assignment rows, dependencies, routed signals, and
  Membrane suggestions.
- Add a task visibility table:
  - task owner
  - assignee
  - upstream/downstream owners
  - project owners
  - room members if scoped to a room

### 9. Time display is only partially GMT+8

Claim: demo-facing ISO time is GMT+8.

Reality: `formatIso()` now appends GMT+8, but several stream components
still call `new Date(...).toLocaleString()` directly, and `SlaCard`
renders a visible target date that way.

Modify spec:

- Ban direct `toLocaleString()` / `toLocaleDateString()` for timestamps
  in app code.
- Add a small lint or test that fails on direct timestamp formatting
  outside `apps/web/src/lib/time.ts`.
- Replace existing direct calls with `formatIso` or `formatIsoSeconds`.

## P2 Gaps

### 10. Existing pollution remains after forward-only fixes

Forward Membrane fixes do not clean already-published conflicts.

Modify spec:

- Add `MembraneAuditService.scan_project(project_id)`:
  - read-only by default
  - emits candidate conflict notes for owners
  - never auto-demotes published rows
- Add a CLI/admin endpoint for demo cleanup.

### 11. Stub mode disables the Membrane Agent review path

`WORKGRAPH_USE_STUBS=true` wires `membrane_reviewer = None`. That is fine
for offline UI work, but dangerous if a demo/prod environment silently
boots in stub mode.

Modify spec:

- Health endpoint should expose agent modes:
  - Edge live/stub
  - Membrane ingest live/stub
  - Membrane review live/disabled
  - Render live/stub
- Production boot should warn loudly, or fail, when stub mode is on.

### 12. Graph UI skips unrendered node kinds

GraphCanvas comments say unrendered kinds are silently skipped. That can
make "Graph is the state" visually false if the backend has nodes the UI
does not know how to show.

Modify spec:

- Unknown node kinds should render as neutral nodes with explicit
  `unknown kind` labeling in debug mode.
- Add a graph test fixture with one future node kind.

## Reflection: Why This Class Of Gap Is Easy To Miss

The failure mode is "noun satisfaction": seeing `MembraneService`,
`MembraneAgent`, `CandidateKind`, `FlowPacket`, or `DecisionRow` and
mentally granting the product claim before checking the exact mutation
path. The antidote is to trace the write:

user action -> router -> service -> review/gate -> repository write ->
retrieval/pretext -> UI/debug visibility.

Every product invariant needs a negative fixture. The useful question is
not "does Membrane run?" It is "can I construct one realistic candidate
that should not enter shared context, and prove it stays out of both the
database's canonical statuses and the agent pretext?"

