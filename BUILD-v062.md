# BUILD-v062.md

Build plan for the v0.6.2 pivot. Source-of-truth specs:

- `graphflow_handoff_v062/DESIGN_LOCK.md` — product doctrine + locked IA
- `graphflow_handoff_v062/API_CONTRACT.md` — backend contract
- `graphflow_handoff_v062/FRONTEND_IMPLEMENTATION.md` — routes + components
- `graphflow_handoff_v062/INVARIANT_TESTS.md` — CI gates
- `graphflow_handoff_v062/schemas.graphflow.json` — enum lock
- `DESIGN.md` (rewritten 2026-05-12) — visual system v3

`docs/north-star.md` and `docs/architecture.md` are **superseded on IA and shell**. Product thesis (decision crystallization, signal chain, memory atoms, three-graph framing) still holds.

---

## Cutover policy

- **Big-bang.** No parallel-live week. The day Phase A ships, `/` redirects to `/my-ai` and `/projects/[id]/*` returns 404.
- Every existing audit URL migrates to a global route (`/decisions/[id]`, `/nodes/[id]`, `/kb-items/[id]`, `/docs/[id]`).
- The competition is over; we own demo URL breakage and re-record.

---

## Phases

### Phase 0 — Invariant tests (gate)

Port `graphflow_handoff_v062/INVARIANT_TESTS.md` (11 tests) into the existing FE test suite (`apps/web/src/__tests__/` or wherever Vitest lives — confirm at start). Tests **fail on `master` today**; passing them is the cutover gate.

Deliverable: 11 tests landed and red. CI configured to allow red on these specific tests during Phase A only.

### Phase A — Shell, design refresh, route shells (1-2 days)

Single PR. Replaces shell, applies new visual system, scaffolds the 5 new routes empty, deletes the old `/projects/[id]/*` tree, adds the `/` → `/my-ai` redirect.

**A.1 Design tokens.** Rewrite `apps/web/src/app/globals.css` per `DESIGN.md` v3. Keep `--wg-*` token namespace; only values + font imports change. New radii + spacing scale. Dark mode authored, not inverted.

**A.2 New shell.** New `apps/web/src/components/shell/AppShellV3.tsx`, `AppSidebar.tsx` (rewritten), `Topbar.tsx` (rewritten), `ScopeBand.tsx` (new), `DrawerHost.tsx` (new). 5-surface nav locked: My AI / Conversations / Tasks / Documents · KB / Flow Center.

Delete from `apps/web/src/components/shell/`: project-tree code in `AppSidebar.tsx` (ProjectNode, ProjectRoomsSection), `NewDMPicker.tsx` (moves into Conversations surface).

**A.3 Route shells.** Empty pages at:
- `apps/web/src/app/my-ai/page.tsx` (placeholder; full landing lands in Phase B)
- `apps/web/src/app/conversations/page.tsx` + `conversations/[id]/page.tsx`
- `apps/web/src/app/tasks/page.tsx` + `tasks/[id]/page.tsx`
- `apps/web/src/app/docs/page.tsx` + `docs/[id]/page.tsx`
- `apps/web/src/app/flow-center/page.tsx`

Each renders a `<Heading>` + `<EmptyState>` so the shell can be sanity-checked.

**A.4 Redirect + 404.** `apps/web/src/app/page.tsx` returns `redirect('/my-ai')`. New `apps/web/src/app/projects/[id]/page.tsx` returns `notFound()` (overrides anything still resolving there). Delete the rest of `apps/web/src/app/projects/[id]/**` entirely.

**A.5 Legacy URL sweep.** Grep `apps/web/src/**` for `/projects/${` and `href="/projects/`. Wrap each in a temporary `legacyProjectUrl(...)` helper that returns `'#'` and console-warns. Phase E rewrites them properly.

**A.6 Auth + layout.** `apps/web/src/app/layout.tsx`: theme color in metadata updated to new accent; `themeColor` light/dark values reflect the new palette.

**Invariants passing after Phase A:**
- Primary nav = exactly the 5 surfaces
- `GET /projects/:id` → 404
- `/` redirects to `/my-ai`
- Create menu (when wired) excludes blank-start task/topic/flow_request/memory

**Out of scope for Phase A:** API endpoints, drawer contents, scope-aware filtering, mobile breakpoints, the actual Flow / Memory / Tasks features.

### Phase B — API contract additions (1 week)

New FastAPI routers, each wrapping existing service-layer code. No DB column renames. `project_id` is the underlying column; `scope_id` is the v0.6.2 API alias.

New routers under `apps/api/src/workgraph_api/routers/`:
- `my_ai.py` — `GET /api/my-ai/landing`, `POST /api/my-ai/messages`
- `conversations.py` — `GET /api/conversations`, `GET /api/conversations/:id`, `POST /api/conversations/:id/messages` (wraps existing `streams.py`)
- `scopes.py` — `GET /api/scopes`, `GET/POST /api/user/active-scope`
- `proposals.py` — generic `GET/POST /api/proposals/:id/{accept,dismiss,mark-stale}` (replaces today's per-kind suggestion endpoints; routes by `ProposalType`)
- `flow_requests.py` — v0.6.2 surface: `POST /draft`, `PATCH /:id/attachments`, `POST /:id/send`, `POST /:id/respond`, `POST /flow-responses/:id/generate-memory-candidate`. Wraps existing `flows.py`.
- `memory_candidates.py` — wraps `membrane.py`. Includes compression_analysis shape with the required `caveat` field.
- `tasks_global.py` — `GET /api/tasks?scope_id=&view=`, `POST /api/tasks/candidates`, `POST /api/tasks/:id/promote`. Wraps `task_progress.py`.
- `documents.py` — `GET /api/documents`, `GET /api/scopes/:id/project-brief`, `POST /api/documents/:id/publish`. Wraps `kb_items.py` + `render.py`.
- `right_rail.py` — `GET /api/right-rail?surface=&object_id=` (refresh-only)
- `ai_assistance.py` — `POST /api/ai-assistance/run` returning `mutates_state: false` envelope
- `create_menu.py` — `GET /api/create-menu` returning the locked allow/exclude list

**Authority pattern.** Add `services/authority.py` that computes `AuthorityCheck` for any (user, object) pair. Every mutation endpoint returns 403 with `{required_roles, user_roles, allowed_actions}` envelope on failure. Roles from `schemas.graphflow.json` AuthorityRole enum.

**Invariants passing after Phase B:**
- `POST /api/ai-assistance/run` → `mutates_state: false`
- Unauthorized memory accept → 403 with required_roles
- Memory candidate accept records full lineage (`verbatim_source_id`, `ai_distillation_id`, `accepted_by`)
- Compression analysis caveat present

### Phase C — Flow Center + Memory Candidate Review (1-2 weeks, doctrine-load-bearing)

The hardest surfaces. Doctrine: AI proposes, authority accepts; flow acceptance does not auto-accept memory; lineage preserved.

**C.1 Flow Center page.** `apps/web/src/features/flow-center/`:
- `FlowCenter.tsx` — header + 4 metric tiles (Needs me / Waiting on others / Awaiting Membrane / Recently completed)
- `FlowTable.tsx` — source→target, title, requester, authority, evidence count, status, next action
- `FlowDrawer.tsx` — opened via DrawerHost; flow request detail with edit-before-send

**C.2 Memory Candidate Review drawer.** `apps/web/src/features/memory-review/`:
- `MemoryReviewDrawer.tsx` — 6 sections per `API_CONTRACT.md`:
  - VerbatimSource (cited text from origin)
  - AIExtractedClaim
  - CompressionAnalysis (status / warning_count / caveat — must render the caveat)
  - ProposedMemoryAtom (with revise affordance)
  - AuthorityState (renders from server `authority_check`, never infers)
  - LineageTimeline (verbatim → distillation → revision → accepted)
- `MemoryPromptDrawer.tsx` — after-flow-response prompt with actions [review, skip, later]
- 6 actions wired: accept / revise / reject / defer / skip / reopen
- Skip is reversible: `POST /api/flow-responses/:id/generate-memory-candidate`

**C.3 Right Rail spine.** `apps/web/src/components/right-rail/RightRail.tsx` with fixed sections in order: Context / Related Work / Evidence · Sources / AI Assistance / Primary Action. AI Assistance actions are secondary buttons that return proposals only.

**Invariants passing after Phase C:**
- Flow response prompt actions = [review, skip, later]
- Memory candidate accept requires server authority (403 else)
- Compression caveat visible in UI
- AI Assistance buttons don't mutate state

### Phase D — Conversations + Tasks + Documents (1 week)

**D.1 Conversations.** `/conversations`:
- `ConversationIndex.tsx` — left list (Recent = DMs+Rooms; Active Topics separate)
- `ConversationShell.tsx` — three modes (DM / Room / Topic)
- Topic dedup invariant: a conversation in Recent must not appear in Active Topics

**D.2 Tasks.** `/tasks`:
- `TaskIndex.tsx` with `?view=my_tasks|all` and scope filter
- `TaskCard.tsx` + `RecognitionPolicyBadge` per `TaskRecognitionPolicy` enum
- Promote-from-candidate flow

**D.3 Documents · KB.** `/docs`:
- `DocumentIndex.tsx` — Project Brief pinned (`ProjectBriefBadge`)
- `DocumentEditor.tsx` — publish flow returns memory candidates (never accepted memory)

### Phase E — Audit URL migration (3-5 days, tedious)

Every reference to `/projects/[id]/...` URLs in `apps/web/src/**` swept. Migration table:

| Old | New |
|---|---|
| `/projects/[id]/detail/decisions` | `/decisions?scope_id=[id]` |
| `/projects/[id]/detail/decisions/[did]` | `/decisions/[did]` |
| `/projects/[id]/nodes/[nid]` | `/nodes/[nid]` |
| `/projects/[id]/kb/[kid]` | `/kb-items/[kid]` |
| `/projects/[id]/renders/[slug]` | `/docs/[did]` |
| `/projects/[id]/detail/graph` | embed in `/nodes/[id]` related-work; no top-level graph page |
| `/projects/[id]/detail/plan` | embed under Tasks scope filter |
| `/projects/[id]/detail/tasks` | `/tasks?scope_id=[id]` |
| `/projects/[id]/detail/risks` | `/tasks?view=risks&scope_id=[id]` |
| `/projects/[id]/status` | `/scopes/[id]` (read-only X-ray) |
| `/projects/[id]/team` | `/scopes/[id]/members` |
| `/projects/[id]/settings` | `/scopes/[id]/settings` |

`CitedClaimList` updated to emit new URLs. `legacyProjectUrl()` helper deleted after sweep.

### Phase F — Cleanup (1-2 days)

- Delete `apps/api/src/workgraph_api/routers/vnext_prefs.py`, `vnext_streams.py`
- Delete any FE `shell-v-next` files in `apps/web`
- Sweep `docs/` — add archive banners to `docs/shell-v-next.txt`, anything else superseded
- Update `CLAUDE.md` to point at `graphflow_handoff_v062/DESIGN_LOCK.md` instead of `docs/north-star.md`
- Update `docs/north-star.md` + `docs/architecture.md` with archive banners

---

## Order of execution

Strict sequential phases, but inside each phase work parallelizes. Phase 0 + Phase A in the same PR (tests + shell together, ship together). Phase B in its own PR. Phase C in two PRs (Flow Center, then Memory Review). Phase D parallelizable across three sub-PRs. Phase E one sweep PR. Phase F one cleanup PR.

Total estimate: 4-6 weeks of focused work for a one-person shop, faster if multiple sub-agents pick up Phase D in parallel.

## What's deliberately not on this plan

- **i18n string sweep.** Keep zh + en working throughout. Any new strings land with `next-intl` keys. Not a phase, a discipline.
- **Mobile.** Desktop-first per v0.6.2 PRODUCTION_GAP_LIST. Mobile is a Phase 8 follow-up.
- **Sub-agent specialist picker.** Rejected in correction R.6. Specialist sub-turns appear as attributed turns inside the user's stream.
- **Project as page.** Hard invariant. Don't reintroduce it.
- **Animation choreography** beyond DESIGN.md v3 motion section. Tokens land in Phase A.3; the 5 motion moments wire later.

## Risk register

- **Backend column naming.** `project_id` stays in DB; APIs alias as `scope_id`. Sweeping renames at the DB layer is out of scope and would break the membrane invariant.
- **Personal stream untrap.** Today's personal stream is project-scoped. Phase B needs a "no-scope" personal mode for `/my-ai` landing. Existing `personal.py` is 1503 lines — start by reading the existing `personal/{project_id}/post` endpoint and generalize.
- **Membrane authority.** Today's membrane gates KB writes. v0.6.2 expects authority-gating across decisions, tasks, documents. Backend extension in Phase B.
- **/projects URL breakage.** 404 is the intended behavior per the invariant — accept the breakage. No 301 redirects to global routes; force the global routes to stand on their own.
