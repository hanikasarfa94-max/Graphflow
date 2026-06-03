# Disappearing-Broker Loop — Alpha Demo Script & Operator Checklist

The complete send → suggestion → disclosure-edit → inbox → reply → accept →
sender-sees-reply loop, runnable in under 3 minutes with two seeded users.

> Surfaces: `RouteSuggestion` (My-AI) · sidebar footer Inbox badge ·
> `/inbox` · `RoutingReplyPanel` (Conversations) · sender-side
> `RoutedReplyInline`. Backend: `routing.py` + `confirm_route`, deterministic
> `DemoEdgeAgent`, `POST /api/demo/seed-broker`, `GET /api/demo/routing-events`.

---

## 0. Personas

- **Sender** (`demo_sender`) — has a question, doesn't know who to ask.
- **Recipient** (`demo_recipient`) — the only skilled teammate in the project
  (skills: backend / data-export / crm), so the agent grounds the route on them.

Both are created by the seed; use the credentials the seed **returns** (the
dev password is disposable — don't hardcode or paste it into commits).

## 1. Enable deterministic demo mode

The demo uses a deterministic agent so routing fires every time (not LLM
roulette). Set, then start the API:

```
WORKGRAPH_USE_STUBS=true
WORKGRAPH_DEMO_ROUTING=true
```

Both flags are required: `use_stubs` selects stub agents; `demo_routing` swaps
the silent stub for `DemoEdgeAgent`. Neither is ever on in prod.

## 2. Seed command

```
curl -X POST http://localhost:8000/api/demo/seed-broker
```

Returns `{ project_id, sender_username, recipient_username, sender_id,
recipient_id, recipient_display_name, password }`. Keep this response — you
log in with these.

## 3. The loop (what to click)

| Step | Who | Action | Expected screen |
|---|---|---|---|
| 1 | Sender | Log in, open **/my-ai** | composer |
| 2 | Sender | Type the prompt below, send | inline **RouteSuggestion**: "Route to {recipient}?" + rationale |
| 3 | Sender | Click **Edit**, tweak the B-facing draft, click **Send** | card → "Routed to {recipient} · waiting for reply…" |
| 4 | Recipient | (separate browser/incognito) log in | sidebar footer **Inbox** badge shows **1** |
| 5 | Recipient | Click **Inbox** → open the row | lands on `/conversations#routing-…` → **RoutingReplyPanel** (framing + options) |
| 6 | Recipient | Pick an option or type a reply → **Send reply** | panel → replied |
| 7 | Sender | (back on /my-ai, kept open) | card updates to **"{recipient} replied"** + body |
| 8 | Sender | Click **Close the loop** | card → "Closed with {recipient}." |

**Exact prompt** (must be a question, ≥8 chars, ends with `?`):

> `Who knows the CRM export quirk for the launch?`

## 4. Verify telemetry (optional, after the run)

```
curl http://localhost:8000/api/demo/routing-events
```

Expect non-zero `count` for `routing.dispatched`, `routing.opened`,
`routing.replied`, `routing.accepted` — proof the loop fired end to end.

## 5. Fallback steps

- **Routing won't fire reliably?** You're probably on the real LLM. Confirm
  `WORKGRAPH_DEMO_ROUTING=true` **and** `WORKGRAPH_USE_STUBS=true`, restart the
  API, re-seed.
- **Need a clean slate?** Re-run the seed on a fresh DB (the seed re-logs-in if
  the users already exist, but a fresh DB avoids stale signals/badges).
- **Demo the back half only?** Seed, then `POST /api/routing/dispatch` as the
  sender (target = `recipient_id`) to land a signal directly in the inbox, and
  start the demo at step 4.

## 6. What to say (3-minute narration)

- *0:00* — "Aïsha has a question. Watch what the AI does **instead** of
  answering."
- *0:30* — send the prompt → "It didn't answer. It found the person who'd
  know, and drafted the ask **in their voice** — and she controls exactly what
  they'll see." (click Edit, tweak, Send.)
- *1:20* — cut to recipient: "It arrived — one badge, no channel noise." Open,
  reply.
- *2:10* — cut back to sender: "The loop closes where it started. A new working
  tie just formed — the AI made it, then got out of the way."
- *2:40* — (optional) show `routing-events` JSON: "and it's all measurable."

## 7. Troubleshooting

- **Route proposal doesn't appear** — flags not both set / API not restarted;
  message isn't a question (needs `?` and ≥8 chars); you're not in the seeded
  project (the recipient must be a member). Check `routing-events` later to
  confirm whether a dispatch ever happened.
- **Recipient badge doesn't update** — the badge polls every 30s and on window
  focus; click into the recipient window. Ensure you're logged in as the
  **recipient** (the target), not the sender. Confirm the dispatch succeeded
  (`routing.dispatched` count > 0).
- **Hash route doesn't open the panel** — you must be on **/conversations** with
  a `#routing-{id}` hash. The panel reads `location.hash` on mount and on
  `hashchange`. Verify the id resolves: `GET /api/routing/{id}` should return
  the signal. A hard reload preserves the hash; a link without the hash won't
  open it.
- **Reply not visible to sender** — the sender-side card is **ephemeral React
  state**: it must still be mounted (sender stayed on /my-ai). The reply always
  persists (see `routing.replied` in `routing-events`); only the *inline*
  sender view requires staying on the page. This is a known Alpha limitation —
  see Product Judgment below.

---

## Product Judgment Note

**What this Alpha slice proves**
- The disappearing-broker thesis is **demoable and coherent end-to-end**: the
  agent declines to answer and instead connects two humans; the sender controls
  disclosure (the B-facing draft); the loop visibly **closes on both ends**; and
  the funnel is **measurable** from the persisted event log.
- The mechanism works on the canonical happy path with real API surfaces (the
  seed and loop drive the same endpoints a user would).

**What it does NOT prove**
- **Demand.** Nothing here shows users *prefer* routing over a self-answer, or
  that recipients reply in a real org. It proves the machine, not the want.
- **LLM routing quality.** The demo uses a deterministic agent. Real-EdgeAgent
  target selection, grounding quality, and route/answer/clarify discrimination
  are untested at the demo layer.
- **Robustness.** Sender-side visibility is poll-based and ephemeral (lost on
  navigation; no WebSocket); multi-target negotiation, counter-back, decline,
  and concurrent load are out of scope.
- **Scale.** Grounding with many skilled members (the 422 path) isn't exercised
  by the single-recipient seed.

**Next real user test**
- A small **real-group dogfood with the real EdgeAgent** (`use_stubs=false`) on
  a genuinely grounded project. Instrument with the existing events and read two
  ratios from `routing-events` / the event log:
  - `suggestion_accepted / suggestion_shown` — do people trust the agent's
    target picks?
  - `routing.replied / routing.dispatched` — do routed asks actually get
    answered?
- That is the first read on **demand and trust**, which this Alpha deliberately
  does not attempt to answer.
