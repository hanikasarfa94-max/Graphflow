# PLAN-v3 — Trust floor + evidence + judgment accumulation

**Status:** started 2026-04-21. Supersedes the v2 roadmap in `docs/competition.zh-CN.md §10` (four of five items shipped; mobile-native deferred as individual-layer). Builds on the chat-centered surface + backend primitives from `PLAN-v2.md` (complete).

**Read first:**

1. `docs/north-star.md` — current product intent
2. `docs/vision.md` — depth thesis (organism, signal chain §6, primitives, especially §5.5 license = subgraph visibility slice)
3. `memory/project_state_20260421.md` (agent memory) — actual shipped state audit

## V3 thesis

Four gaps prevent the system from scaling beyond a single trusted team:

1. **License leakage.** Sub-agents with full-tier context can leak strategy into lower-tier recipients' streams via routed replies. Observer-scope (V2 shipped) blocks direct reads; it does NOT block an LLM paraphrasing sensitive graph state into a reply destined for that observer.
2. **Evidence-free claims.** The edge LLM emits paraphrased claims without pointing at their backing nodes. The graph stops feeling like ground truth and starts feeling like a chat bot.
3. **Dissent disappears.** When a member disagrees with a crystallized decision, no first-class primitive records it. The information is lost, and the member's *judgment accuracy over time* — the thing that should drive promotion and weighting — is un-capturable.
4. **Agents ask humans instead of deliberating.** `pre_answer.py` is single-sided. Two sub-agents never actually debate before bothering their owners. The "meeting-replacement" thesis is unfulfilled.

V3 closes these four gaps. Afterward the product is deployable beyond a single-team pilot without manual trust.

## Out of scope (V3 kill-list)

- **Mobile-native.** Individual-layer; deferred.
- **Rehearsal-as-distinct-stream.** Already covered by the `personal` stream type (v1 StreamRow).
- **File system / hierarchical KB.** Flat KB + renders sufficient for V3 scope. Prerequisite for v4 book-renderer.
- **Org layer above projects.** Deferred; competition §10 "cross-project slicing" satisfied at observer level in V2.
- **Voice / ASR meeting capture.** Upload-transcript scope only if meeting-ingest lands in V3 (not in Phases 1–2 below).
- **Open agent SDK, counterfactual simulation at scale, book renderer.** All V4.

## Phase 1 — trust floor (parallel, blocking for Phase 2)

### 1.A License system (~8k LOC)

**Scope:** scoped context + license-lint on replies + leader-escalation + audit log.

**Touches:**
- New `apps/api/src/workgraph_api/services/license_context.py` — builds a license-filtered graph+KB slice given `(viewer_id, project_id, audience_id?)`.
- Prompt-builder services (grep edge LLM prompt assembly in `services/collab.py`, `services/routing.py`, `services/pre_answer.py`) — call `license_context` with `audience_id = routed_recipient_id` when output is destined for another user.
- `routers/collab.py` + `routers/routing.py` — before emitting a routed reply, run license-lint on cited node IDs; if any fall outside recipient's license view, pause and prompt the source user.
- New `services/leader_escalation.py` — when a scoped sub-agent detects it lacks context to answer an in-license question, route the question to the leader's sidebar as a pending inbound; leader's full-license sub-agent drafts a reply via existing `pre_answer` pipeline; leader ships / edits / denies.
- New `LicenseAuditRow` ORM + migration `0006_license_audit` — records every cross-license reply (source, target, node IDs referenced, outcome).
- Frontend: escalation card renders on leader's sidebar; source-user confirmation dialog for license-lint pauses.

**Acceptance tests** (`apps/api/tests/test_license_privacy.py`):
1. Observer's sub-agent prompt excludes out-of-view nodes (scoped context load).
2. A routed reply whose citations reference out-of-view nodes triggers license-lint pause, not send.
3. Scoped sub-agent that can't answer an in-license question triggers leader-escalation; leader's inbound carries the question + proposed draft.
4. Audit log row written on every cross-license ship / edit / deny.
5. Full-tier member internal asks unaffected (regression).

### 1.B Citations on every claim (~5k LOC)

**Scope:** every edge-LLM reply carries structured citations. Uncited claims render visually weaker.

**Touches:**
- Prompt contract update: edge LLM outputs `{ text, citations: [{ node_id, kind }] }` per claim.
- Services emitting replies: `services/collab.py`, `services/clarification.py` (if present), `services/conflict.py` (if present), `services/drift.py`, `services/render.py`, `services/membrane.py`. Audit the agent catalog already wired into `main.py`.
- Frontend: claim cards render inline citation chips (click → `/projects/[id]/nodes/[nodeId]`); uncited text renders in a subtle gray.
- License-lint (Phase 1.A) reuses this citation field — the node IDs to check are the cited ones, not a post-hoc text scan.

**Acceptance tests** (`apps/api/tests/test_citations.py`):
1. Edge-LLM reply includes at least one citation when the prompt surfaces graph/KB context.
2. Uncited claim renders with `uncited: true` flag.
3. Citation click deep-links to the node detail page (`/projects/[id]/nodes/[nodeId]`).
4. Existing agent tests that stub LLM output still pass (citations tolerated as optional in v1; mandatory enforcement is a follow-up).

### Phase 1 merge gate

Both 1.A and 1.B land on master. Full suite green (`uv run pytest apps/api/tests/ --ignore test_ws*`). Frontend `bunx tsc --noEmit` clean. Deploy to prod with `0006_license_audit` migration clean. Then Phase 2 opens.

## Phase 2 — judgment + deliberation (parallel, after Phase 1 merge)

### 2.A Dissent + judgment accuracy (~5k LOC)

**Scope:** DissentRow linked to decisions, validated by outcomes, fed to perf panel.

**Touches:**
- ORM: `DissentRow` — id, decision_id, dissenter_user_id, stance_text (≤500 chars), created_at, validated_by_outcome (`supported` | `refuted` | `still_open`), outcome_evidence_ids JSON.
- Migration `0007_dissent`.
- New `routers/dissent.py` — create/list/get.
- New `services/dissent.py` — validation pipeline: on milestone-hit / decision-reversed / risk-materialized events, scan recent dissents on the affected decision and flag.
- `services/perf_aggregation.py` — extend per-member record with `dissent_accuracy: { total: n, supported: n, refuted: n, still_open: n }`.
- Frontend: decision cards gain "record dissent" action; dissent renders inline on decision lineage; perf panel gains dissent-accuracy column.

**Acceptance tests** (`apps/api/tests/test_dissent.py`):
1. Member records dissent on a crystallized decision.
2. Dissent renders on the decision's lineage view.
3. On `decision_reversed` event, matching dissent validates as `supported`.
4. On `milestone_hit` event supporting the decision, matching dissent validates as `refuted`.
5. Perf panel aggregation reflects dissent counts per member.

### 2.B Full agent-vs-agent scrimmage (~8k LOC)

**Scope:** multi-turn debate between source's and target's sub-agents before humans receive the routed question. License-aware (reuses 1.A context builder).

**Touches:**
- New `services/scrimmage.py` — orchestrates 2–3 turn back-and-forth. Each turn builds prompt via `license_context` scoped to the generating agent's owner. Convergence detector: both agents land on same proposal OR both surface the same unresolved crux.
- New `routers/scrimmage.py` — trigger endpoint, transcript fetch.
- ORM: `ScrimmageRow` — id, routed_signal_id, transcript_json, outcome (`converged_proposal` | `unresolved_crux`), created_at.
- Migration `0008_scrimmage`.
- Frontend: scrimmage mode toggle on routing card; when converged → propose as decision for human approval; when unresolved → humans receive debate summary + both positions inline, not a blank question.
- Builds directly on `pre_answer.py` seed: pre-answer becomes scrimmage turn 1.

**Acceptance tests** (`apps/api/tests/test_scrimmage.py`):
1. Convergence path: two stubbed sub-agents agree on a proposal by turn 2; proposal surfaces as pending-decision.
2. Non-convergence path: two stubbed sub-agents diverge; humans receive summary with both positions.
3. License-aware regression: scrimmage on a question involving out-of-license nodes respects recipient's view (no leak via debate turn).
4. Transcript persisted and queryable via `/api/projects/{id}/scrimmages/{id}`.

## Dependency diagram

```
  Phase 1 (parallel)
    1.A License system  ───┐
    1.B Citations ─────────┤
                           ├──► Phase 1 merge gate ──► Phase 2 (parallel)
                                                         2.A Dissent
                                                         2.B Scrimmage ← reuses 1.A context builder
```

## Definition of done (V3)

1. License-lint blocks 100% of cited-leak test cases in `test_license_privacy.py`.
2. Every production edge-LLM reply carries ≥1 citation or an explicit `uncited: true` flag.
3. `dissent_accuracy` visible per member on `/projects/[id]/team/perf`.
4. Scrimmage converges on the Moonshot permadeath demo scenario without human intervention; non-convergence case surfaces both positions.
5. Full backend suite green (excluding the known `test_ws*` DEEPSEEK env flake).
6. `bunx tsc --noEmit` clean.
7. Production deploy clean with migrations `0006_license_audit`, `0007_dissent`, `0008_scrimmage` applied.
8. `docs/competition.zh-CN.md §10` updated — dissent + license + citation + scrimmage listed as shipped; mobile + file-system + book-renderer + org-layer + open-SDK listed as V4 roadmap.

## Deferred to V4

- File system / hierarchical KB (book-renderer prerequisite)
- Org layer / vision cascade above projects
- Book rendering (thesis-book per project, "authorship dies; rendering lives" taken to the limit)
- Voice / ASR meeting capture (upload-transcript path may sneak into V3 if time permits)
- Open agent SDK / third-party specialist agents
- Counterfactual simulation at scale (`drop_person`, `delay_milestone`, etc. — current is `drop_task` only)
- Mobile-native
