# Routing / disappearing-broker — reference (extracted before deletion)

> Status: reference note, captured 2026-06-03 when the dead pre-pivot stream
> island was deleted. `RouteProposalCard.tsx` (send side) and
> `RoutedInboundCard.tsx` (reply side) were the old heavy UI for the
> disappearing-broker loop. They were unmounted post-v0.6.2 and are deleted
> here; this note preserves their **semantics** so the slim Phase-1 surface
> can be rebuilt without resurrecting the cards. **Do not restore the old
> cards** — see `git show <pre-deletion-sha>:apps/web/src/components/stream/RouteProposalCard.tsx`
> if you need the literal source.

## The loop (Phase 1 keystone — PRD Story 4, north-star "human↔human ties ↑")

`A asks agent → agent proposes routing to B → A confirms (disclosure-gated) →
signal lands in B's inbox → B replies/accepts → A sees the reply`. Backend is
fully alive (`routing.py`); only the two UI ends were dead.

## Canonical backend API (`routing.py`, keep — has response_models)

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/routing/dispatch` | create a routed signal (send) |
| `GET`  | `/api/routing/inbox?status=pending` | recipient queue (LIVE via `/inbox`) |
| `GET`  | `/api/routing/outbox` | sender queue |
| `GET`  | `/api/routing/{id}` | single signal detail |
| `POST` | `/api/routing/{id}/reply` | recipient answers (option or free text) |
| `POST` | `/api/routing/{id}/accept` | recipient accepts |

`api.ts` helpers to KEEP and reuse: `RoutingSignal`, `PersonalRouteTarget`,
`dispatchRoutingSignal`, `replyRoutingSignal`, `acceptRoutingSignal`,
`getRoutingSignal`, `RoutingInboxResponse`, inbox/outbox list types.

> Legacy alternate send path `POST /api/personal/route/{id}/confirm`
> (`confirmRouteProposal`) is superseded by `/api/routing/dispatch`. Prefer
> dispatch; let confirm + `parseRouteProposalFromBody` die with the cards.

## `RouteProposalCard` — send side (what to re-express slimly)

- **Fields shown:** agent `framing`; 1–3 targets (`PersonalRouteTarget`:
  `display_name`, `rationale`, `b_facing_draft`); `background[]` grounding
  snippets (`source` + `snippet`); timestamp.
- **Actions:** "Ask [name]" → dispatch to that target; **editable B-facing
  draft per target** (the disclosure-gate — what B sees, rewritten as A→B);
  local dismiss.
- **Disclosure-gate (preserve):** the user edits `b_facing_draft` before send;
  the refined text becomes the routed signal's framing so B gets a clean ask,
  not A's raw private reasoning. (Dual-loyalty rule T4.)
- **Drop (do NOT port):** scrimmage toggle, gated-proposal sign-off,
  pre-answer preview — demoted decision mechanics, not routing.

## `RoutedInboundCard` — reply side (what to re-express slimly)

- **Fields shown:** `framing`; reply `options[]` (label + body); `background[]`;
  status.
- **Actions:** pick an option or write free-text reply → `replyRoutingSignal`;
  `acceptRoutingSignal`. (Old UI opened a drawer via `shell/v062/DrawerHost`.)

## Slim target (replaces ~2,080 LOC of cards with ~240–340 LOC)

- **Reply:** make `/inbox`'s `#routing-{id}` deep-link work — on anchor, fetch
  `getRoutingSignal`, show framing + background + options, post reply/accept.
- **Send:** tiny inline suggestion in the composer — "Route to Alice? [Send]
  [Edit] [Dismiss]" — Edit exposes the B-facing draft, Send → dispatch.
