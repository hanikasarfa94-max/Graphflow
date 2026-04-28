# PLAN-Next.md — WorkGraph Next build plan

**Status:** drafted 2026-04-28. Active build plan, supersedes the implicit "v2 is done" state. PLAN-v2/v3/v4 are historical (per CLAUDE.md).

**Spec sources, in priority order:**
1. `new_concepts.md` — current product/system doctrine. Authoritative for product behavior.
2. `docs/north-star.md` — load-bearing v1/v2 spec; gets a "Correction R" (Phase N.0) noting what changed.
3. `workgraph-ts-prototype/` — reference UI prototype. Patterns ported, not the code.
4. Memory: `project_workgraph_next_design_20260428.md` — design decisions ledger.

**Architectural invariants that do NOT change** (per CLAUDE.md):
- Thin routers, single membrane per cell, LLM orchestration only in `packages/agents/`, single license gate.

**URL/schema decisions locked 2026-04-28:**
- No URL rename (`/projects/[id]` stays — cell terminology is internal).
- No schema rename of `KbItemRow.scope='group'` — legacy value continues to mean cell-scope. New scope values are added for Department + Enterprise tiers.

---

## Phase N.0 — Doc finalize (cheap, blocks downstream)

Goal: the spec reads consistently before code work begins.

- [ ] Renumber `new_concepts.md` to fix the duplicate §7. Algorithmic Doctrine stays §7; Agent and Service Design becomes §8; Product Modules → §9; Design Principles → §10; Differentiation → §11; Examples → §12/§13/§14; Strategic Conclusion → §15.
- [ ] Sweep `new_concepts.md` for residual "Home" / "team room" (singular) phrasings; confirm only the §6.11 / §8.1 / §8.4 versions remain authoritative.
- [ ] Add a "Correction R" subsection to `docs/north-star.md` (after Correction Q) noting:
  - `/` home dropped — entry is general-agent stream
  - Single team room per project relaxed — multi-room with smallest-relevant-vote
  - Cell terminology adopted; project = cell; four-tier scope
  - Manual creates flow through Membrane as candidates
- [ ] Cross-link: `new_concepts.md` §6.11 references north-star Correction R; north-star Correction R points to `new_concepts.md` §6.11 + §8.1 + §8.4.

**Definition of done:** a fresh reader can read `new_concepts.md` end-to-end without contradicting paragraphs; north-star is consistent.

**Estimate:** 1 day, no code.

---

## Phase N.1 — Backend prerequisites (blocking)

Goal: schema + service surface supports the new model. Frontend port cannot start before this.

### B1 — Scope tier values

- [ ] Audit current `KbItemRow.scope` to confirm only `'personal'` and `'group'` are emitted/read. Map every reader (`MembraneService`, `LicenseContextService`, repository queries, agent prompts).
- [ ] Add scope values `'department'` and `'enterprise'` without touching legacy `'group'`. Migration is additive; existing rows untouched.
- [ ] Extend `LicenseContextService.allowed_scopes(...)` to consider Department membership and Enterprise membership when computing tier admissions.
- [ ] Add a `DepartmentRow` (or reuse an existing org-graph node — verify in code first; the graph report mentions "Organizations & Org Graph" community).

### B2 — Multiple team rooms per cell

- [ ] Today's project↔team-stream is 1:1. Either:
  - (a) extend the stream model with `cell_id` + `member_ids` + `kind='room'` so multiple per cell are valid, or
  - (b) introduce a `RoomRow` keyed on `cell_id`.
- [ ] Update routes that create/list streams to accept `cell_id` and return all rooms in the cell.
- [ ] Membership: a room's members must be a subset of the cell's members. Enforce at write boundary.

### B3 — Decision scope stream

- [ ] Add `DecisionRow.scope_stream_id` (nullable; falls back to `cell_id` for legacy decisions).
- [ ] Crystallization Agent stamps `scope_stream_id` when it identifies the smallest-relevant stream for a decision (DM / room / cell).
- [ ] Vote/quorum logic derives from the stream's member list, not the cell's.
- [ ] Backfill: leave existing decisions with `NULL` scope_stream_id (cell-wide vote, current behavior).

### B4 — Leader read bypass

- [ ] Confirm whether a leader-bypass mechanism already exists (org-graph community in graphify report suggests yes — verify).
- [ ] If not: add `is_lead_for(scope, scope_id)` helper. Bypass `is_member` for **read** only. Writes still require explicit cell membership (preserves single-membrane).
- [ ] Wire into `LicenseContextService.allowed_scopes()`.

### B5 — Manual creates as candidates

- [ ] Extend `CandidateKind` enum: `manual_project`, `manual_task`, `manual_room`, `manual_kb_item`.
- [ ] Wire create-form endpoints to write a candidate row + dispatch to Membrane review, NOT direct canonical create.
- [ ] Membrane prompt update: candidate handlers cover the new kinds.

**Definition of done:** all five subtasks merged with tests; existing membrane / license / KB tests still green; one new e2e test verifies a manual-task create lands as a candidate that membrane resolves.

**Estimate:** 1.5 weeks. B1 + B5 are quick (enum + value additions). B2 + B3 are the meat. B4 depends on the org-graph audit.

---

## Phase N.1.5 — Attention-engine eval

Goal: decide how much of `new_concepts.md` §7 lands in v-Next vs. defers. Settles the "does an LLM with a big context window obviate the explicit retrieval stack" question with data, not opinion.

- [ ] Build a bench corpus simulating one cell: 200 nodes (KB items, stream turns, decisions, tasks, risks). Hand-curated for realistic shape.
- [ ] Hand-label 30–50 query/answer pairs with ground-truth: which nodes *should* be in context, which *must not* (private/suppressed/superseded).
- [ ] Implement three retrieval configs:
  - **A** — pure LLM with all 200 nodes in context window
  - **B** — vector-only top-K → LLM
  - **C** — full §7 stack (hybrid retrieval + RRF + rule membrane + ranking) → LLM
- [ ] Scale tests: rerun at corpus = 200 / 1,000 / 5,000 to find where A breaks.
- [ ] Measure per config: tokens-per-query, p50/p95 latency, F1 vs ground truth, **suppressed-node leak rate**, audit explainability.

**Decision rule (lock outcome of eval into the build):**
- If A has acceptable F1 AND 0% leak rate at 200-node scale → ship A; defer §7 stack.
- If A leaks suppressed nodes → ship §7.7 membrane post-filter as a non-negotiable floor regardless of other layers.
- If A's F1 drops at 1k+ nodes → ship §7.2 hybrid retrieval; skip RRF + LTR.
- §7.14 Stage 7 (learning-to-rank) deferred past v-Next regardless. Needs feedback data we won't have for months.

**Definition of done:** eval report committed; decision rule applied to Phase N.2 scope; floor (§7.7) shipped if applicable.

**Estimate:** 3–5 days.

---

## Phase N.2 — Frontend port

Goal: port `workgraph-ts-prototype/` patterns to `apps/web/`, with adjustments. Stream-card polymorphism is fused in here — same surface.

### Layout port

- [ ] Leftmost rail: 6 icons (Home + 5 module shortcuts to `/detail/*`). Keep prototype's choice — already aligned (icons-only periphery, not promoted peers).
- [ ] IM nav (column 2): drop specialist-agent picker. Drop fixed `#频道` concept. Replace with cell-scoped rooms (multiple per cell) + DM list.
- [ ] Center: stream view, polymorphic cards (see "Stream cards" below).
- [ ] Right workbench: keep as opt-in side composer. Drop workflow panel (fixed-pipeline rejected). Each remaining panel must shortcut into a real `/detail/*` page.

### Stream cards (polymorphism)

- [ ] Build/reuse Card components for: human turn, edge agent turn, attributed sub-agent turn (clarifier, conflict, planner), ⚡ decision crystallization with expandable lineage, ambient signal (task created / risk closed / drift), routed-inbound preview.
- [ ] No vanilla bubbles. Prototype's bubble component is a starting shell only.

### Top bar

- [ ] "+ 新建" dropdown: keep Project + Task + Room. **Drop** Agent. All three flow through Membrane as candidates (see B5).
- [ ] ProjectBar pills: replace info pills with **scope-tier toggles** — Personal / Cell / Department / Enterprise. Each toggle is wired to `LicenseContextService.allowed_scopes()` per turn.

### Routed inbound (north-star Q.2)

- [ ] Header badge with count.
- [ ] Slide-in drawer with rich option card: Label / Background / Reason / Trade-off / Weight (north-star §"Option design").
- [ ] Resolve → status updates → drawer closes; user's own stream undisturbed.
- [ ] **Not** a workbench panel; routed inbound has its own affordance.

### Routing

- [ ] `/` redirects to general-agent stream (`/agent` or `/me/stream`).
- [ ] `/projects/[id]` URL preserved (no rename, locked decision).
- [ ] `/projects/[id]/rooms/[roomId]` — new route for room streams.
- [ ] `/detail/*` audit routes survive from v1, accessed via leftmost rail icons.

### i18n

- [ ] Wire `next-intl` zh+en (north-star locked, prototype is zh-only).

**Definition of done:** prototype patterns visible in `apps/web/`; stream renders polymorphic cards; routed inbound is a drawer; manual-create dropdown writes candidates; scope pills are wired.

**Estimate:** 1.5–2 weeks. Most velocity-gating piece is stream-card polymorphism.

---

## Phase N.4 — Multi-room UX + smallest-relevant-vote

Goal: the room-creation gesture and the vote-quorum surface that the architecture now supports.

- [ ] "+ 新房间" affordance inside a cell sidebar. Opens a small modal: name + members (subset of cell members).
- [ ] Room creation writes a `manual_room` candidate; Membrane confirms; on accept, room appears in cell sidebar.
- [ ] Vote UI on a decision card: shows quorum count and **explains scope** ("voting with this room's 4 members because the discussion stayed in #design"). Reveal `decision.scope_stream_id` lineage on expand.
- [ ] Cell-level decision detection: when a decision's scope is wider than any single room, it falls back to all cell members. Surface this fallback explicitly in the card.

**Definition of done:** create a 4-person room from inside a cell, hold a discussion that crystallizes a decision, see the vote quorum = 4 (not the whole cell), see the scope-explanation copy.

**Estimate:** 1 week.

---

## Phase N.5 — Polish (continuous, post-launch)

- [ ] Mobile-native stream + compose (north-star R15).
- [ ] Catch-up summaries for absence > a few hours (north-star R10/R11/R14').
- [ ] Notification → deep-link routing (north-star R2/R13/R15).
- [ ] Render triggers visible (north-star Q.7) — postmortem / handoff buttons on `/projects/[id]/status`.
- [ ] Browseable `/projects/[id]/kb` with light editing (north-star Q.6).

---

## Open questions (need user lock before the affected phase starts)

- **Functional-tier scope value name.** Plan uses `'department'`. Alternative: `'discipline'` (knowledge-work flavor) or `'function'`. Locked value goes into B1 enum. Pick before N.1.
- **Eval bench timing.** N.1.5 sits between backend prereqs and frontend port. Acceptable, but could be parallelized with N.0/N.1 if a second pair of hands is available. Decide based on team size.
- **Department data source.** Does an existing org-graph node already represent a department, or is `DepartmentRow` net-new? Resolve in B1 audit.
- **Room creation default privacy.** When a user creates a room inside a cell — is membership default-empty (creator only, invite explicit) or default-all-cell-members (opt-out)? Prefer empty + invite (matches the "creation does not imply memory" principle), but confirm.

---

## Phase ordering at a glance

```text
N.0  doc finalize           (1d, no code)
  ↓
N.1  backend prereqs         (1.5w)  — B1 → (B2+B3) → B4 → B5
  ↓
N.1.5 attention engine eval   (3-5d)  — outcome scopes N.2 §7 work
  ↓
N.2  frontend port            (1.5-2w)  — fuses stream-card polymorphism
  ↓
N.4  multi-room UX            (1w)
  ↓
N.5  polish                   (continuous)
```

Total to v-Next ship: ~5 weeks of focused build, assuming no stalls in the eval or backend audits.
