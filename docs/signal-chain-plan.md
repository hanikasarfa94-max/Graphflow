> ✅ **COMPLETE 2026-04-21 — BUILT IN PHASES 7'/7''. HISTORICAL RECORD.**
>
> The counter / escalate routes, `source_suggestion_id` on DecisionRow, and
> the 4-button SuggestionCard described below are live in the codebase.
> Keep as reference for the contract shape; do not read as an open task list.

---

# Signal Chain — Build Plan

**Scope:** the canonical signal chain from `docs/vision.md §6`. Two users, LLM-mediated decision crystallization over a shared graph, WS ripple. Minimum end-to-end.

**Non-scope:** response profiles, thesis-commit, membranes, escalation-to-actual-meeting, drift detection. All deferred.

## Shared API Contract

Both backend and frontend agents work from this. Any deviation must be cross-checked.

### Extended `IMSuggestion` shape (wire format)

```jsonc
{
  "id": "uuid",
  "message_id": "uuid",
  "project_id": "uuid",
  "kind": "none" | "tag" | "decision" | "blocker",
  "confidence": 0.0,
  "targets": ["..."],
  "proposal": { "action": "...", "summary": "...", "detail": {} },
  "reasoning": "≤240 chars",
  "status": "pending" | "accepted" | "dismissed" | "countered" | "escalated",
  "created_at": "ISO-8601",
  "resolved_at": "ISO-8601 | null",

  // new fields for signal chain
  "counter_of_id": "uuid | null",       // if this suggestion is itself a counter, points at the one it counters
  "decision_id": "uuid | null",         // if accepted and crystallized, FK to DecisionRow
  "escalation_state": "requested | null"
}
```

### New routes

```
POST /api/im_suggestions/{id}/counter
  body: { "text": string }   // the counterer's own framing
  semantics:
    - original suggestion's status -> "countered"
    - post a new MessageRow authored by the counterer, body=text
    - run IMAssistAgent on that new message (normal flow)
    - the resulting new IMSuggestion has counter_of_id = original suggestion id
  response 200: {
    "original_suggestion": IMSuggestion,
    "new_message": Message,
    "new_suggestion": IMSuggestion | null   // null if word count < 5 (classification skipped)
  }
  WS fanout: "suggestion" (updated original), "message" (new), "suggestion" (new if any)

POST /api/im_suggestions/{id}/escalate
  body: {}
  semantics:
    - suggestion status stays "pending" OR moves to "escalated" (choose one; doc says "escalated")
    - escalation_state = "requested"
    - no meeting is scheduled — v0 is just a flag
  response 200: IMSuggestion
  WS fanout: "suggestion"
```

### Extended `IMService.accept` semantics

Existing behavior (graph mutation via `_apply_proposal`) stays. **Addition:**

- When `kind == "decision"` AND `confidence >= 0.6`, also create a `DecisionRow` linked to the suggestion. This is the "crystallization" step from vision §6.
- `DecisionRow.source_suggestion_id = suggestion.id`
- `DecisionRow.conflict_id = NULL` (new schema — see below)
- `DecisionRow.rationale` = suggestion.reasoning
- `DecisionRow.apply_actions` = [{ "kind": proposal.action, "detail": proposal.detail }]
- `DecisionRow.apply_outcome` = "ok" if graph mutation succeeded, "advisory" if no mutation was possible
- Updated `IMSuggestion.decision_id = decision.id`
- WS fanout: existing `suggestion` frame + existing `decision` frame (decisions.py-style broadcast). No new frame type needed.

### Schema changes

**`IMSuggestionRow`** (`packages/persistence/src/workgraph_persistence/orm.py`):

Add three nullable columns:
- `counter_of_id: String(36), FK→im_suggestions.id, nullable=True, indexed`
- `decision_id: String(36), FK→decisions.id, nullable=True, indexed`
- `escalation_state: String(16), nullable=True` (values: `"requested"` or null)

**`DecisionRow`** (same file):

- Change `conflict_id` FK to **nullable** (was required). IM-originated decisions have no conflict.
- Add `source_suggestion_id: String(36), FK→im_suggestions.id, nullable=True, indexed`

Dev mode uses SQLite `init_schema` which drops + recreates tables on boot — no Alembic migration needed. Just update the ORM definitions and restart. Existing dev data will be lost on restart; that's fine for this phase.

### Status enum extension

`IMSuggestionRow.status` now accepts: `pending` | `accepted` | `dismissed` | `countered` | `escalated`. No enum column in the DB (currently `String(16)`) so just update the literals everywhere.

## Backend agent brief

Owns: everything under `apps/api/`, `packages/persistence/`, `packages/domain/`. Tests in `apps/api/tests/`.

Delivers:
1. Three schema edits above
2. `IMSuggestionRepository` getters: `get_by_id`, `mark_countered`, `mark_escalated`, plus existing `resolve` kept
3. `DecisionRepository.create_from_suggestion(...)` helper (or extend `create()` to accept `source_suggestion_id` + nullable `conflict_id`)
4. `IMService.counter(suggestion_id, text, user_id)` and `IMService.escalate(suggestion_id, user_id)` methods
5. `IMService.accept` extended to crystallize DecisionRow when kind=="decision" and confidence>=0.6
6. Routes `POST /api/im_suggestions/{id}/counter` and `POST /api/im_suggestions/{id}/escalate` in `apps/api/src/workgraph_api/routers/collab.py`
7. Tests in `apps/api/tests/test_collab.py` (or new `test_signal_chain.py`) covering: counter happy path, counter-on-already-resolved suggestion fails, escalate happy path, accept-with-decision creates DecisionRow, accept low-confidence does not create DecisionRow

Before reporting done: `uv run pytest apps/api/tests/test_collab.py apps/api/tests/test_im_assist_eval.py` (whatever test file you added) and paste the pass count.

## Frontend agent brief

Owns: everything under `apps/web/src/app/projects/[id]/im/`, `apps/web/src/lib/api.ts`, `apps/web/src/app/console/[id]/canvas/`.

Delivers:
1. Update `apps/web/src/lib/api.ts` — extended `IMSuggestion` type, new API calls `counterSuggestion(id, text)` + `escalateSuggestion(id)`
2. Refactor `SuggestionCard` in `apps/web/src/app/projects/[id]/im/ChatPane.tsx`:
   - Replace 2-button row with 4 buttons: `Accept` | `Counter` | `Escalate` | `Dismiss`
   - Clicking `Counter` inline-expands a textarea + Send button; submits to counter endpoint, optimistic-updates UI
   - Clicking `Escalate` hits escalate endpoint, then shows "⚠ Awaiting sync" amber badge inline
   - Show "countered" and "escalated" states on resolved suggestions (not just accepted/dismissed)
3. When a `MessageBubble` renders a suggestion whose `counter_of_id` is set, show a subtle "↳ counter to earlier decision" note linking to the countered message
4. When a `MessageBubble`'s suggestion has `decision_id` set, show a terracotta "⚡ Decision recorded" crystallization indicator on the message (not buried in the chip)
5. WS `decision` frame handler: currently the ChatPane ignores `type === "decision"`. Add handler that flashes the relevant message's crystallization indicator if the decision's `source_suggestion_id` matches a suggestion on-screen
6. Visual ID stays on-brand: terracotta accent for crystallization, amber for escalation, existing neutral for pending

Before reporting done: run the ai-slop-check script, start the web dev server (`bun dev` — already running on 3000), hit the IM page manually, verify the 4-button layout renders without TS errors. Paste any console warnings.

## Division of labor between agents

- **No file conflicts:** backend agent edits nothing under `apps/web/`; frontend agent edits nothing under `apps/api/`, `packages/`.
- **One shared file:** `apps/web/src/lib/api.ts` typings — frontend agent owns this but must match the backend wire format above exactly.
- **Shared contract:** the JSON shapes in this doc. If the backend agent changes field names, it must update this doc and the frontend agent re-reads.

## Integration step (after both sub-agents return)

1. Kill API server, restart (SQLite will recreate with new schema)
2. Kill + restart web dev server to pick up new API client
3. Register two users (e.g. `alice` / `alice1234` and `bob` / `bob1234`)
4. Alice creates a project, invites `bob`
5. Open `/projects/{id}/im` in two browser profiles (or one incognito)
6. Alice posts a confused decision-like message ("we should drop the export feature, it's too much scope")
7. Both see message; IMAssist classifies (decision-kind), suggestion chip appears
8. Bob counters with: "actually export is already 80% done, we should keep it"
9. Alice sees Bob's counter as a new message with suggestion linking back
10. Alice accepts Bob's counter → DecisionRow crystallizes, both see ⚡ indicator
11. Verify: `SELECT * FROM decisions WHERE source_suggestion_id IS NOT NULL` returns the row

Demo pass = all 11 steps land in <3 min of clicking.
