# PLAN-v2 — Chat-centered surface build

**Status:** 2026-04-18. Supersedes `PLAN.md` Phases 11–13 for the web surface. Builds on the backend from Phases 1–10 (backend agents and signal-chain code stay live).

**Read first:**
1. `docs/north-star.md` — product intent + locked decisions
2. `docs/vision.md` — depth thesis (organism, signal chain §6, primitives)
3. `docs/signal-chain-plan.md` — backend signal-chain contract (already built, Phase 7'/7'')
4. `docs/demo-game-company.md` — Moonshot demo, live-moment script

## Out of scope (explicit kill-list)

- Multi-pane web console (Phase 11 shape). Existing panes demote to `/detail/*` for audit only.
- "Conflict Center" / "Clarify Panel" as destination pages.
- Plan DAG / Graph viz / Tables view as primary UI.
- Project-creation wizard (replaced by modal on `/`).
- Delivery-engine framing in any new code or copy.
- Group streams (3–10 ad-hoc). 1:1 DM only in v1.
- Private thinking stream, devil's-advocate mode, drift detection UX, full subgraph slicing. Deferred to v2+.

## Phase A — Doc groundwork ✓

- [x] Archive banner on `AGENT.md`, `docs/dev.md`, `PLAN.md`
- [x] `docs/north-star.md` — operational product intent
- [x] `PLAN-v2.md` — this file

## Phase B — Backend data model

**Owner:** backend agent. **Touches:** `packages/persistence/src/workgraph_persistence/{orm,repositories}.py`, `packages/domain/`, `apps/api/src/workgraph_api/routers/`.

### B.1 Stream primitive
- `StreamRow` — id, type (`'project'|'dm'`), project_id (nullable, FK), created_at, updated_at, last_activity_at
- `StreamMemberRow` — stream_id, user_id, joined_at, last_read_at, role_in_stream (`'member'|'admin'|'observer'`)
- Backfill migration: one `StreamRow{type='project'}` per existing `ProjectRow`; all current project members become `StreamMemberRow`s
- Existing `MessageRow` gains `stream_id` (nullable during migration, then filled from `project_id` lookup)
- Dev SQLite `init_schema` drops + recreates — no Alembic needed per existing convention

### B.2 DM creation
- `POST /api/streams/dm` body `{ other_user_id }` — creates-or-returns the canonical 1:1 stream between authenticated user and other_user_id (dedup by sorted member pair)
- `GET /api/streams` — list streams the authenticated user belongs to, sorted by `last_activity_at` desc, returns type + members summary + project_id + unread count

### B.3 Profile fields on UserRow
- `UserRow.profile` JSONB default `{}` — keys: `declared_abilities` (string[]), `role_hints` (string[]), `signal_tally` (dict of signal-type → rolling-window count)
- `UserRow.display_language` — `'en'|'zh'` default `'en'`
- `GET /api/users/me` returns profile; `PATCH /api/users/me` updates declared fields + language
- Signal-tally update is fire-and-forget on every message/decision crystallization (no-op for now if tally stays empty; wire in v2)

### B.4 Scoped license (3 tiers)
- `ProjectMemberRow.license_tier` — `'full'|'task_scoped'|'observer'` default `'full'`
- Route guards enforce tier: observers can't POST messages, task_scoped only on their assigned tasks (v1 MVP: enforce full/observer; task_scoped full enforcement v2)

### B.5 Tests
- `apps/api/tests/test_streams.py` — stream CRUD, DM dedup, message-stream link, backfill
- `apps/api/tests/test_profile.py` — profile read/write, language persistence
- Before reporting done: `uv run pytest apps/api/tests/test_streams.py apps/api/tests/test_profile.py apps/api/tests/test_collab.py apps/api/tests/test_signal_chain.py` — paste pass count

## Phase C — Frontend i18n foundation

**Owner:** frontend-i18n agent. **Touches:** `apps/web/` root config, `apps/web/src/i18n/`, `apps/web/src/app/layout.tsx`, minimal per-page changes.

- Install `next-intl@^3` (`bun add next-intl` from `apps/web/`)
- `apps/web/src/i18n/locales/en.json`, `apps/web/src/i18n/locales/zh.json` — initial catalogs (common chrome only: nav, buttons, placeholders, date labels). Aim 50–100 keys.
- Middleware for locale detection from cookie → Accept-Language → default `en`
- `<LocaleProvider>` wraps root layout
- Language switcher component in header (uses `PATCH /api/users/me { display_language }` to persist)
- Validation: login, register, `/`, `/projects` list pages fully translated as smoke test
- Before reporting done: `bun tsc --noEmit` clean + visual check both languages render

## Phase D — Frontend route restructure

**Owner:** frontend-routing agent. **Touches:** `apps/web/src/app/`.

### D.1 Move existing panes to `/detail/*`
- Move `apps/web/src/app/projects/[id]/{graph,plan,im,conflicts,decisions,events}/` → `apps/web/src/app/projects/[id]/detail/{graph,plan,im,conflicts,decisions,events}/`
- Update internal links / nav references
- Keep `/projects/[id]/im` route alive as a redirect → `/projects/[id]` for any external links

### D.2 Create route stubs (empty/placeholder content, filled by Phase E/F/G)
- `apps/web/src/app/page.tsx` — new personal home, replaces current `/` redirect
- `apps/web/src/app/projects/[id]/page.tsx` — new team stream (currently the landing shows project overview; replace entirely)
- `apps/web/src/app/projects/[id]/status/page.tsx` — status dashboard stub
- `apps/web/src/app/projects/[id]/settings/page.tsx` — settings stub
- `apps/web/src/app/projects/[id]/nodes/[nodeId]/page.tsx` — graph-node deep-link stub
- `apps/web/src/app/projects/[id]/renders/[slug]/page.tsx` — LLM-rendered artifact stub
- `apps/web/src/app/streams/[id]/page.tsx` — DM stream stub
- `apps/web/src/app/settings/profile/page.tsx` — user profile stub

### D.3 Primary nav component
- Header with: logo, current-project switcher (if on a project route), DM list (badge for unread), profile menu, language switcher
- `/detail/*` routes accessible via a demoted "Audit" link inside a project — not in primary nav
- Before reporting done: `bun tsc --noEmit` clean; visit every new route, no 404

## Phase E — Stream renderer + compose

**Owner:** me (primary — most integration-sensitive) or a focused agent. **Touches:** `apps/web/src/components/stream/`, `apps/web/src/app/projects/[id]/page.tsx`, `apps/web/src/app/streams/[id]/page.tsx`.

### E.1 `<StreamView>` component
- Vertical scroll of polymorphic cards, newest-at-bottom with auto-scroll-on-new unless user has scrolled up
- Card types (discriminated union from backend):
  - `HumanTurnCard` — author + avatar + timestamp + body + reactions row
  - `EdgeLLMTurnCard` — "🧠 edge" attribution, body, optional "why this was routed" tooltip
  - `SubAgentTurnCard` — "❓ clarifier" / "⚖ conflict" / other agent-typed
  - `DecisionCard` — ⚡ terracotta accent, summary + "View lineage" → `/projects/[id]/nodes/[id]`
  - `GatedApprovalCard` — "⚠ pending legal" state, accept/reject inline
  - `AmbientSignalCard` — light gray, "3 tasks created" / "risk closed" / "commit abc123 linked"
  - `CatchUpSummaryCard` — renders at top after absence > threshold
- Default cursor: newest routed-to-me turn (or bottom if none)
- WS integration via existing `/ws/projects/{id}` channel

### E.2 `<Composer>` component
- Text input (growing textarea), send button
- Paste-ingest: image → upload + inline render; URL → inline preview card; text → message
- Emoji picker (basic, popular-emojis only)
- Read-receipt silent update on message visible in viewport
- V1 does NOT include pre-commit rehearsal interjection — placeholder for v2

### E.3 Presence indicator
- Small dot on avatar: green (online, active ≤5min), yellow (away, 5–60min), gray (offline >1h)
- Computed from `StreamMemberRow.last_read_at` on any stream plus WS connection state

### E.4 Sub-agent attribution
- Existing `IMSuggestion` / clarifier / conflict-agent output renders as `SubAgentTurnCard`, NOT as a side-chip on a message. When user clicks Accept/Counter/Dismiss, backend flow is the existing signal-chain.

## Phase F — Personal home `/`

**Touches:** `apps/web/src/app/page.tsx` + supporting components.

- Sections (ordered):
  1. **Pending needs your response** — routed questions across all your streams, newest first, click to jump to the exact turn
  2. **Gated approvals** — visible to admin roles only; filtered pending list
  3. **Active task context** — renders when (1) and (2) are empty; shows current task, status, upstream why, downstream dependents, adjacent teammate statuses, edge-LLM offer
  4. **Projects** — simple list, last-activity sort
  5. **Direct messages** — recent DMs, unread badge
- Primary action: "+ new project" button → modal (name, description, invite users by handle). Modal creates `ProjectRow` + `StreamRow` + `StreamMemberRow` for each invitee.

## Phase G — Status dashboard `/projects/[id]/status`

**Touches:** `apps/web/src/app/projects/[id]/status/page.tsx`.

- Read-only panels: members (with presence), active tasks (owner, status, age), open risks (severity, age), recent decisions (with lineage link), linked external artifacts (git commits, doc URLs)
- Data from existing queries on the graph — no new backend work
- Renders well for finance / observer roles

## Phase H — DM streams

**Touches:** `apps/web/src/app/streams/[id]/page.tsx`, profile-card component anywhere user avatars appear.

- Uses `<StreamView>` with stream type 'dm' — renders same cards, LLM passive
- "Message [name]" button on profile cards → `POST /api/streams/dm { other_user_id }` → redirect to `/streams/[id]`

## Phase I — Agent output → stream integration

**Touches:** backend WS broadcast, frontend card mapping.

- Clarification agent, conflict agent, planning agent emit structured signal events
- Events broadcast as sub-agent turns in the project stream
- No separate panels — the existing `/detail/conflicts` and `/detail/decisions` remain as audit views but are not where the user sees these agent outputs in-flow

## Phase J — Dogfood + Moonshot demo verification

- Reseed if needed: `uv run python scripts/demo/seed_moonshot.py`
- Two browsers (raj @ EN, aiko @ ZH) → `/projects/{id}`
- Run the signal chain (`docs/demo-game-company.md`): permadeath-drop → counter → accept → ⚡
- Verify: both browsers show crystallization live, UI chrome rendered in respective languages, existing panes reachable via Audit nav only

## Phase K — 1:1 DM minimal demo

- Raj DMs James: "free to pair on save-system Thu?"
- James replies
- Verify: stream renders, WS live, no LLM noise (stays passive)

## Dependencies and parallelization

```
Phase A (done) ──┐
Phase B (backend) ──┐
Phase C (i18n) ──┬──→ Phase D (routes) ──→ Phase E (stream) ──→ Phase F (home), Phase G (status), Phase H (DM)
                                                                          │
                                                      Phase I (agent integration) ─→ Phase J, K (demo)
```

**Parallel-eligible:** B, C, (D after C). E depends on D. F/G/H can run parallel after E ships.

## Definition of done (v1)

- Moonshot signal chain runs end-to-end in the new `/projects/[id]` stream, not in the old `/im` pane
- Bilingual UI chrome works (language switcher persists, all chrome translated)
- Old panes reachable but demoted
- 1:1 DM round-trip works
- Status dashboard renders at `/projects/[id]/status`
- Personal home at `/` shows pending + active-task context + project list + DM list
- All backend tests pass: `uv run pytest apps/api/tests/` (existing 125 + new streams/profile ~15)
- Frontend typecheck clean: `bun tsc --noEmit`

**Estimated CC scope:** 2–3 focused days with agent parallelization.
