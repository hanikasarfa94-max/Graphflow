# Slice C.1 — Source-Side Reply Symmetry — Design Memo

**Status:** approved 2026-05-05 (user sign-off with edits applied)
**Date:** 2026-05-05
**Owner:** product / architecture
**Scope:** First mutation slice of the Flow Packets system. Closes the
§7.5 invariant gap: when the source receives a reply, they must be able
to accept / counter / escalate / follow-up symmetrically, the same way
the target had options when responding.

## Sign-off changelog (2026-05-05)

- §4.2 counter_back atomicity: spawn-first-then-mutate, with
  compensating rollback on spawn failure. Reverses the original
  draft's "record original, fail loudly on spawn" — a partial-success
  outcome on counter_back is bad UX and hard to recover from.
- §4.4 custom_followup response status: original packet is `completed`
  (was incorrectly written `active` in the draft). Underlying signal
  stays `replied`; the projection maps that to packet status
  `completed`. The new packet is the only `active` one.
- §5.1 source_accept strictness: explicit note that the new endpoint
  is stricter than legacy `RoutingService.accept()`, which is
  idempotent on already-accepted. Source_accept errors with
  `not_ready_for_source_action` if state isn't `replied`.
- §8 concurrency: remove the "UPDATE ... WHERE status='replied'" claim
  (existing repos do SELECT-then-mutate). C.1 adds a repository-level
  conditional-update helper (`update_status_if`) — first mutation
  endpoint deserves the proper primitive, not a soften.
- New §11 — projection lifecycle revision: routed packets currently
  conflate "target replied" with "packet completed." C.1 fixes the
  projection so `replied` → packet active + current_target = [source];
  `accepted/escalated/declined/expired` → packet completed.
- §12 implementation slices: C.1.b includes the projection update so
  C.1.c FE only reads `next_actions` and renders buttons; FE never
  re-derives source-side affordances from the underlying signal id.

---

## 1. Summary

Add `POST /api/projects/{pid}/flows/{flow_id}/actions` for **source-side
only** actions on **`ask_with_context` packets only**. Backend extends
`RoutingService` with four new source-side methods. A new
`FlowActionService` owns the dispatch table; the HTTP router stays thin
per the CLAUDE.md invariant.

`accept` closes the packet — it does **not** crystallize a decision.
"Accept reply" and "record decision" stay separate domains.

---

## 2. In / Out of scope

### In scope (C.1)

- `accept`, `counter_back`, `escalate_to_gate`, `custom_followup`
- Source-side only. `actor.id == packet.source_user_id`.
- `flow_id` shape: `route:{routed_signal_id}` only.
- Source state precondition: routed signal `status='replied'`.
- Response: packet's new status + (when applicable) the spawned
  follow-up packet's id.

### NOT in scope

- Target-side actions (`delegate_up`, target's own counter, etc.) —
  those land in C.2.
- KB or handoff packet actions — recipe support is `ask_with_context`
  only for now. The router rejects other recipes with
  `unsupported_flow_recipe`.
- Decision crystallization. `accept` does not auto-create a
  `DecisionRow`. If a project later wants "accept and crystallize," that
  is a separate user gesture against `DecisionService`, not a side
  effect of `accept`.
- Auto-fan-out to authority on `escalate_to_gate`. The status flips to
  `escalated`; routing the matter to a gate-keeper is C.2 work, where
  the right hook into `GatedProposalService` lands.
- Free-text on the original signal. Notes attach to the packet's
  evidence audit trail, not to the underlying `RoutedSignalRow.framing`.
- Slice F snapshot table.

---

## 3. Endpoint contract

```
POST /api/projects/{project_id}/flows/{flow_id}/actions
```

### Request body

A discriminated union on `action`:

```json
{ "action": "accept", "note": "optional, ≤ 1000 chars" }
```

```json
{
  "action": "counter_back",
  "framing": "required, 1-4000 chars — the counter ask",
  "note": "optional, ≤ 1000 chars"
}
```

```json
{ "action": "escalate_to_gate", "note": "optional, ≤ 1000 chars" }
```

```json
{
  "action": "custom_followup",
  "framing": "required, 1-4000 chars — the follow-up ask",
  "note": "optional, ≤ 1000 chars"
}
```

`note` is the human's explanation, persisted on the audit trail (Slice
D will surface it in the evidence packet's `human_gates` array). Empty
for the source's spontaneous click; populated when the source typed
context for posterity.

### Response (success)

```json
{
  "ok": true,
  "flow_id": "route:{original_signal_id}",
  "status": "completed" | "active",
  "spawned_flow_id": "route:{new_signal_id}" | null
}
```

`status` is the original packet's new status. `spawned_flow_id` is set
when the action created a new routed signal (counter_back,
custom_followup); null otherwise (accept, escalate_to_gate).

### Response (error)

```json
{ "ok": false, "error": "{code}", "detail": "{human-readable}" }
```

### Error codes → HTTP status

| code                         | status | meaning                                                                        |
|------------------------------|--------|--------------------------------------------------------------------------------|
| `flow_not_found`             | 404    | `flow_id` resolves to no projection in this project                            |
| `unsupported_flow_recipe`    | 400    | recipe other than `ask_with_context` (KB / handoff / etc.)                     |
| `unsupported_action`         | 400    | action kind unknown, or known but not yet wired (target-side in C.1)           |
| `not_source_user`            | 403    | viewer is not `packet.source_user_id`                                          |
| `not_ready_for_source_action`| 409    | underlying signal not in `replied` state (still pending, already terminal)     |
| `validation_error`           | 422    | pydantic body shape invalid (missing `framing` on counter, oversize note, etc.) |
| `domain_error`               | 400    | downstream domain service refused; `detail` carries the sub-error verbatim     |

### Membership gate

Standard project-membership check before any other validation. If the
viewer isn't a project member, `403 not_a_project_member` (existing
shape from kb / handoff routers — same code, not a new error).

---

## 4. Action behaviors

All four require: `flow_id` starts with `route:`, viewer ==
`packet.source_user_id`, signal `status == 'replied'`. Failures emit
the error codes from §3.

### 4.1 `accept`

| step | what                                                      |
|------|-----------------------------------------------------------|
| pre  | signal.status == 'replied'                                |
| do   | signal.status = 'accepted'; record gate event             |
| post | packet projects as `status: completed`, no new packet     |

`accept` does not call `DecisionService`. Per the design choice locked
above: keep "accept reply" separate from "record decision."

### 4.2 `counter_back`

| step | what                                                                                |
|------|-------------------------------------------------------------------------------------|
| pre  | signal.status == 'replied'; framing ≥ 1 char                                        |
| do   | (1) verify precondition; (2) dispatch new RoutedSignalRow; (3) update original via conditional update — `status='replied' → 'countered'` |
| post | original packet `status: completed`; new packet `route:{new_id}` `status: active`   |

**Atomicity (revised per sign-off Q3):** spawn first, then conditionally
update. If the spawn fails, the original signal is untouched and the
error surfaces as `domain_error`; the user retries with the same
counter framing. If the conditional update fails (someone else changed
status in the meantime — extremely rare with the precondition), the
spawn is **compensated** by deleting the just-created signal so the
caller doesn't see a phantom counter packet without the original being
counter-marked.

The new signal carries source/target unchanged (source still source).
For C.1 we do NOT add a `counter_of_id` chain column to
`routed_signals`; the chain is implicit (same source/target/project,
recent timestamp). Adding a proper chain field is a Slice D concern
when evidence drawer needs it for lineage rendering.

**Compensating rollback shape:** the spawn returns a `signal_id` from
`RoutingService.dispatch`. If the conditional update on the original
returns 0 affected rows, `RoutingService.source_counter` deletes the
spawned row in the same session before raising
`not_ready_for_source_action`. The deletion is unconditional (we're
in the same request, no other actor can be racing the *spawn* itself).

### 4.3 `escalate_to_gate`

| step | what                                                              |
|------|-------------------------------------------------------------------|
| pre  | signal.status == 'replied'                                        |
| do   | signal.status = 'escalated'; record gate event                    |
| post | packet `status: completed`; no new packet, no fan-out             |

`escalated` is a new terminal state on `RoutedSignalRow.status`. The
column is `String(16)` so no schema migration is needed; the value
sits alongside the existing `accepted / declined / expired` set.
**C.1 does not auto-route to authority.** Source has flagged the
matter; downstream routing to a gate-keeper is C.2's hook into
`GatedProposalService`. The `escalated` status is the audit trail.

### 4.4 `custom_followup`

| step | what                                                                                |
|------|-------------------------------------------------------------------------------------|
| pre  | signal.status == 'replied'; framing ≥ 1 char                                        |
| do   | original signal **untouched**; dispatch new RoutedSignalRow with body.framing       |
| post | original packet `status: completed`; new packet `route:{new_id}` `status: active`   |

`custom_followup` is "thanks for the reply, but I have one more thing
to ask." Original signal's status stays `replied`. A new RoutedSignalRow
ships with the follow-up framing.

**Response shape on success:**

```json
{
  "ok": true,
  "flow_id": "route:{original}",
  "status": "completed",          // original packet (NOT a delta)
  "spawned_flow_id": "route:{new}"
}
```

The `status: completed` here means "the original packet is in the
completed bucket from your viewpoint" — it has been there since the
target replied, and `custom_followup` doesn't change that. The new
follow-up is the only `active` thing now. Returning `active` here
(as the draft incorrectly did) would have confused FE refresh logic
into thinking the original got reactivated.

**Spawn failure semantics (per sign-off Q3):** because the original
isn't being mutated, partial failure is harmless. If the spawn fails,
return `domain_error` with the dispatch's sub-detail; original stays
exactly as it was. No compensating rollback needed.

---

## 5. Service architecture

Two new modules; one extension to existing.

### 5.1 `RoutingService` extension (existing module)

Four new instance methods that own the domain mutations. Each returns
a small dict the dispatcher passes through to the HTTP response.

> **Strictness vs. legacy `RoutingService.accept()`** — that legacy
> method is idempotent on `accepted` (calling accept on an already-
> accepted signal is a no-op success). The new `source_accept` is
> deliberately stricter: it errors with `not_ready_for_source_action`
> if the signal is not currently `replied`. This is because the flow
> action endpoint is the audit trail for "the source clicked accept,"
> and a no-op success would mask state confusion (e.g., a stale tab
> double-firing). The legacy endpoint stays as-is; a future deprecation
> can converge if the call sites consolidate.

```python
async def source_accept(
    self, signal_id: str, source_user_id: str, *, note: str | None = None,
) -> dict:
    """Source accepts the target's reply as final. Returns
    {ok: True, signal_id, status: 'accepted'}.

    Errors: not_found, not_source_user, not_ready_for_source_action.

    Stricter than legacy RoutingService.accept(): errors on already-
    accepted instead of no-op success.
    """

async def source_counter(
    self, signal_id: str, source_user_id: str, *,
    framing: str, note: str | None = None,
) -> dict:
    """Source counters; original → 'countered'; spawn new dispatch.
    Returns {ok: True, signal_id, status: 'countered',
             spawned_signal_id: '<new>'}.
    """

async def source_escalate(
    self, signal_id: str, source_user_id: str, *, note: str | None = None,
) -> dict:
    """Source escalates; original → 'escalated'. Returns
    {ok: True, signal_id, status: 'escalated'}.

    Note: does not auto-fan-out to authority — see §4.3.
    """

async def source_followup(
    self, signal_id: str, source_user_id: str, *,
    framing: str, note: str | None = None,
) -> dict:
    """Source sends a follow-up ask; original untouched; spawn new
    dispatch. Returns {ok: True, signal_id, status: 'replied',
                       spawned_signal_id: '<new>'}.
    """
```

Each method validates the row, mutates, optionally calls
`RoutingService.dispatch()` for the spawn cases, and emits an
event for any subscribers (existing `event_bus` pattern). Notes are
recorded on `RoutedSignalRow.reply_json` under a new key
`source_action_notes` (an array; multiple actions over time accumulate).

### 5.2 `FlowActionService` (new module)

A thin dispatcher that owns the flow-id parsing, recipe routing, and
maps domain results to the HTTP response shape. Pattern mirrors the
spec §10 invariant: this service may **choose** the domain service,
not own the mutation.

```python
class FlowActionService:
    def __init__(self, routing_service: RoutingService) -> None:
        self._routing = routing_service

    async def execute(
        self, *, flow_id: str, project_id: str, viewer_user_id: str,
        action: ActionPayload,
    ) -> dict:
        kind, source_id = _parse_flow_id(flow_id)  # raises flow_not_found
        if kind != "route":
            raise UnsupportedFlowRecipe(kind)
        if action.action == "accept":
            return await self._routing.source_accept(...)
        if action.action == "counter_back":
            return await self._routing.source_counter(...)
        if action.action == "escalate_to_gate":
            return await self._routing.source_escalate(...)
        if action.action == "custom_followup":
            return await self._routing.source_followup(...)
        raise UnsupportedAction(action.action)
```

The dispatch table is **explicit** so a future code reader can audit
the recipe-to-domain mapping at a glance. Adding a recipe (KB review,
handoff finalize) is a deliberate addition to this table, not an
emergent behavior.

### 5.3 `flows.py` router extension (existing module)

Adds the action handler. Stays thin.

```python
@router.post("/api/projects/{project_id}/flows/{flow_id}/actions")
async def post_flow_action(
    project_id: str, flow_id: str, body: ActionRequest, request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    project_service: ProjectService = request.app.state.project_service
    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        raise HTTPException(403, detail="not_a_project_member")
    service: FlowActionService = request.app.state.flow_action_service
    try:
        return await service.execute(...)
    except FlowError as e:
        raise HTTPException(_STATUS_FOR[e.code], detail=e.detail)
```

`FlowError` is a single exception class with a `code` and `detail`;
the router maps codes to status via a small dict literal. No
business logic in the router.

---

## 6. Pydantic schema sketch

```python
class _AcceptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept"]
    note: str | None = Field(default=None, max_length=1000)

class _CounterBackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["counter_back"]
    framing: str = Field(min_length=1, max_length=4000)
    note: str | None = Field(default=None, max_length=1000)

class _EscalateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["escalate_to_gate"]
    note: str | None = Field(default=None, max_length=1000)

class _FollowupBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["custom_followup"]
    framing: str = Field(min_length=1, max_length=4000)
    note: str | None = Field(default=None, max_length=1000)

ActionRequest = Annotated[
    Union[_AcceptBody, _CounterBackBody, _EscalateBody, _FollowupBody],
    Field(discriminator="action"),
]
```

Discriminated union → FastAPI routes the body to the right model based
on `action`. Validation_error emerges with field-level detail (e.g.,
`framing` missing on a counter_back).

---

## 7. Spec invariants honored

| Invariant | How C.1 honors it                                                                            |
|-----------|----------------------------------------------------------------------------------------------|
| §6 — `current_target_user_ids` is derived | Unchanged; on terminal status, derivation already empties the slice.   |
| §7.1 — human judgment at nodes | Every action requires explicit click; no agent autonomy adds.            |
| §7.2 — Membrane is the boundary | C.1 doesn't write team memory; KB/handoff stay out of scope.            |
| §7.4 — target options ≠ re-routes | C.1 is source-side only; target-side `delegate_up` deferred to C.2.    |
| §7.5 — source symmetry | Endpoint exposes the four spec-named actions; this slice exists to fix this gap.  |
| §10 — thin router, FlowActionService | Implemented exactly as spec sketches; dispatch is the only logic.    |
| §15 — no source-row mutation outside domain services | RoutingService owns all signal-status mutations.       |

The §7.6 invariant ("evidence before completion") is partially
addressed: notes are persisted, and Slice D will fold them into the
evidence packet's `human_gates` array. C.1 lays the groundwork; D
renders it.

---

## 8. Race conditions / concurrency

Two source-side actions racing on the same signal (e.g., source
double-clicks accept in two tabs).

### 8.1 Repository primitive

Existing `RoutedSignalRepository` does SELECT-then-mutate, which has a
classic check-then-act race. C.1 adds a conditional-update helper at
the repository layer — first mutation endpoint deserves the proper
primitive rather than a soften:

```python
class RoutedSignalRepository:
    async def update_status_if(
        self, signal_id: str, *, expect: str, set_to: str,
    ) -> bool:
        """Atomic conditional update. Returns True if exactly one row
        was updated (signal existed AND was in the expected status),
        False otherwise. Caller maps False → not_ready_for_source_action.
        """
        result = await self._session.execute(
            update(RoutedSignalRow)
            .where(RoutedSignalRow.id == signal_id)
            .where(RoutedSignalRow.status == expect)
            .values(status=set_to)
        )
        return result.rowcount == 1
```

### 8.2 Per-action concurrency

- `accept`, `escalate_to_gate`: single conditional update. Losing race
  raises `not_ready_for_source_action`. No partial state.
- `counter_back`: spawn first (always succeeds or raises domain_error;
  no original mutation yet). Then conditional update on original. If
  the conditional update returns False, **delete the spawned row** and
  raise `not_ready_for_source_action`. The deletion is unconditional
  (we just created the row in this request; no other actor has it yet).
- `custom_followup`: spawn only; original untouched. Spawn failure →
  `domain_error`; otherwise success. No race possible on the original.

### 8.3 What about the SELECT-then-mutate paths the existing
`RoutingService.reply()` uses?

Out of scope for C.1. The new `source_*` methods use the conditional
helper; legacy `reply()` stays SELECT-then-mutate. A converged
primitive can land in C.2 when target-side actions need the same
atomicity guarantees.

---

## 9. Test plan

Backend (`apps/api/tests/test_flow_actions.py`, new file):

| test                                            | assertion                                                        |
|-------------------------------------------------|------------------------------------------------------------------|
| `accept` happy path                             | signal status flips to 'accepted'; response.status='completed'   |
| `counter_back` happy path                       | original 'countered'; new signal exists; response carries spawned_flow_id |
| `escalate_to_gate` happy path                   | signal status flips to 'escalated'; no new signal                |
| `custom_followup` happy path                    | original untouched; new signal exists; response.status='active'  |
| non-source caller                               | 403 `not_source_user`                                            |
| signal still pending                            | 409 `not_ready_for_source_action`                                |
| signal already terminal (accepted)              | 409 `not_ready_for_source_action`                                |
| KB flow_id (`kb:{id}`)                          | 400 `unsupported_flow_recipe`                                    |
| handoff flow_id (`handoff:{id}`)                | 400 `unsupported_flow_recipe`                                    |
| unknown flow_id (`route:nonexistent`)           | 404 `flow_not_found`                                             |
| body missing `framing` for counter_back         | 422 `validation_error`                                           |
| body with unknown action                        | 422 `validation_error` (discriminator catches)                   |
| non-member viewer                               | 403 `not_a_project_member`                                       |
| race: two concurrent accepts                    | first wins, second gets `not_ready_for_source_action`            |

13 tests, mirroring the size of `test_flow_projection.py`. No new FE
tests in this slice — drawer doesn't render action buttons until the
FE part of C.1 (separate slice if you prefer; could ship together).

---

## 10. Design decisions (signed off 2026-05-05)

### Q1. `note` persistence location → reuse `reply_json`

`RoutedSignalRow.reply_json["source_action_notes"]` as an append-only
array of `{action, note, at}` records. No migration. Promote to its
own column in C.3 if the audit shape gets messy.

### Q2. `escalated` representation → status value

Add `escalated` to the existing string-enum on
`RoutedSignalRow.status`. The column is `String(16)` — accepts the
new value without migration.

### Q3. Spawn failure semantics on counter_back → spawn-first + compensating rollback

**Reversed from the draft.** A failed counter that left the original
as `countered` with no new signal is bad UX. C.1 spawns first, then
conditionally updates the original; if the conditional update fails
(state changed under us), the just-spawned row is deleted as
compensation. Implementation owns this in
`RoutingService.source_counter`. See §4.2 + §8.2.

For `custom_followup`, partial failure remains acceptable: the original
isn't being mutated, so a failed spawn just reports `domain_error` and
leaves nothing inconsistent. See §4.4.

### Q4. `accept` and decision crystallization → hold the line

`accept` closes the packet only. No `DecisionRow` side effect, even
when the ask was decision-shaped. A "record as decision?" UI gesture
can land separately in Slice D's evidence drawer if the pattern proves
common. Keeping `accept` simple here prevents `FlowActionService` from
quietly growing decision-domain logic.

---

## 11. Projection lifecycle revision (added per sign-off)

Slice A's projection conflates "target replied" with "packet completed":

```python
# current — flow_projection.py _route_packet_from_row
status_alive = (row.status or "pending") == "pending"
packet_status = "active" if status_alive else "completed"
```

This worked before C.1 because there was no source-side action — the
only "active" state was awaiting target. With C.1 the routed signal
lifecycle has two active states:

| signal status | who is currently blocking         | packet status |
|---------------|-----------------------------------|---------------|
| `pending`     | target (target hasn't replied)    | active        |
| `replied`     | source (target replied; awaiting source's accept/counter/escalate/followup) | active |
| `accepted`    | nobody — terminal                 | completed     |
| `countered`   | nobody — terminal (new packet active in its place) | completed |
| `escalated`   | nobody — terminal (gate fan-out is C.2) | completed |
| `declined` / `expired` | nobody — terminal        | completed     |

C.1.b updates the projection accordingly:

```python
ACTIVE_STATUSES = {"pending", "replied"}
status_alive = (row.status or "pending") in ACTIVE_STATUSES

if row.status == "pending":
    current_target = [row.target_user_id]
elif row.status == "replied":
    current_target = [row.source_user_id]      # NEW — source is now blocking
else:
    current_target = []                          # terminal
```

The `next_actions` array also changes: when status='replied' AND
viewer==source, emit four entries (`accept`, `counter_back`,
`escalate_to_gate`, `custom_followup`) so the FE renders them with
zero re-derivation. The existing single-entry "Reply" action
(target-side, when status='pending') stays unchanged for C.1; it's
formally part of C.2 to lift target reply through the flow endpoint.

This change cascades into `bucket=needs_me` correctness: a
replied-and-awaiting-source packet now lands in the source's
`needs_me`, not in `recent`. Tests must include this transition.

---

## 12. Implementation slices (after sign-off)

C.1 lands in three commits. Order is locked: **a → b → c, with c
gated on b shipping the `next_actions` affordances.**

1. **C.1.a — repository primitive + RoutingService source methods.**
   `RoutedSignalRepository.update_status_if` (new conditional helper).
   `RoutingService.source_accept / source_counter / source_escalate /
   source_followup` (four new methods). Unit + integration tests for
   each. No HTTP surface yet; tests call services directly.

2. **C.1.b — FlowActionService, endpoint, projection update.**
   `FlowActionService` with the dispatch table. `POST /api/projects/
   {pid}/flows/{flow_id}/actions` thin router. Update
   `flow_projection.py` per §11 — `replied` → active + source-blocking
   + four-entry `next_actions`. End-to-end HTTP tests covering all 13
   cases from §9 plus the projection lifecycle update.

3. **C.1.c — FE action buttons.** `FlowsPanelBody` reads
   `next_actions` and renders buttons for every entry whose `kind` is
   in `{accept, counter_back, escalate_to_gate, custom_followup}`.
   Counter / followup open a small inline form for `framing`. No
   re-derivation from `routed_signal_id` or `recipe_id`; the BE is the
   source of truth for what the source can do right now. Bilingual.
   Browser dogfood pass before deploy per CLAUDE.md.

**Ship cadence:** C.1.a + C.1.b ship together to prod (the projection
update is part of b, and shipping a alone produces a working endpoint
with no UI affordances yet — fine for back-end-only verification).
C.1.c ships separately after browser dogfood.

---

## 13. What's deferred to C.2 / C.3

- `delegate_up` (target-side: target pushes to authority with stance)
- Target-side `counter` / `dismiss` — currently lives in
  `RoutingService.reply` as the option_id pick; lifting to the flow
  endpoint is C.2.
- Auto-fan-out on `escalate_to_gate` — wire `GatedProposalService`
  hook so escalation ships to the gate-keeper without manual dispatch.
- `counter_of_id` chain column on `routed_signals` — Slice D when
  evidence rendering needs it.
- KB review actions — only land when ChatPane gets a per-suggestion
  anchor, otherwise the action surface and the open-link surface
  diverge.
- Handoff finalize — that's already a finalize button on `/skills`;
  whether to mirror it through the flow action endpoint is a UX
  taste call, not a correctness one.
