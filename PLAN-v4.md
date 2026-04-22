# PLAN-v4 — Close the north-star + hierarchical KB

**Status:** started 2026-04-22. Supersedes the "Deferred to V4" list in `PLAN-v3.md`. V3 shipped: license / citations / dissent / scrimmage + UI refactor + chat-stream layout.

**Read first:**
1. `docs/north-star.md` — primitives we're closing (§5.9 silent consensus, §5.11 ambient onboarding, §5.12 membranes) and §"Documents, knowledge, and edits" (file-system prerequisite).
2. `docs/vision.md §5` — primitive depth.
3. `memory/project_state_20260421.md` (agent memory) — shipped-state audit.

## V4 thesis

V3 closed the *trust* gap (license + citations) and the *deliberation* gap (dissent + scrimmage). V4 closes:

1. **The behavioral-agreement gap.** Dissent captures explicit disagreement, but the complementary primitive — *silent consensus*, when the graph shows everyone is acting on the same assumption — is unshipped.
2. **The first-day-on-the-job gap.** Handoff docs exist for departing members, but a new hire arriving today has no ambient walkthrough. Vision §5.11 promised "10 minutes replacing 2 weeks of ramp."
3. **The outside-world gap.** Vision §5.12 said membranes ingest market / tech / regulatory / customer signals. Backend row exists, no active puller. Graph is currently blind to the world.
4. **The meetings-happen-anyway gap.** Meetings are a pain signal in our thesis, but they still happen. Transcripts metabolized into signals close the loop without waiting for voice ASR.
5. **The hierarchy-and-rich-artifact gap.** KB is flat; every creative artifact (design refs, PDF specs, Figma exports) lives in foreign tools with a link. Book rendering and enterprise ACLs both block on a hierarchical file system with per-node licenses.

## Out of scope (V4 kill-list)

- **Voice / ASR meeting capture.** Upload-transcript path is V4; real-time ASR is V5 if a customer pays.
- **Mobile-native.** Still deprioritized as individual-layer.
- **Org layer above projects.** Earlier thinking put this in V4; moved to V5 to keep V4 focused. Cross-project org graph view is already shipped for the narrower "lightweight aggregation" use case.
- **Book rendering.** Requires file system (Phase 3). Once file system lands, book rendering becomes a v4.5 follow-up.
- **Open agent SDK.** V5.
- **Counterfactual at scale (`drop_person`, `delay_milestone`).** V5.

## Phase 1 — north-star closers, pair A (parallel)

### 1.A Silent consensus (~3k LOC)

Graph infers agreement from behavior (commits, task starts, risk closes) — not polls. When a decision-shaped opportunity has N members acting consistently AND no open dissent or counter, surface it as an auto-detected "silent consensus" proposal that humans can ratify.

**Touches:**
- `SilentConsensusRow` ORM — `id, project_id, topic_text, supporting_action_ids: JSON, inferred_decision_summary, member_ids: JSON, confidence: float, status: 'pending'|'ratified'|'rejected', created_at`. Migration `0009_silent_consensus`.
- `services/silent_consensus.py` — scanner runs on periodic cadence (reuse the existing event-bus tap for drift) across TaskRow status changes + DecisionRow applications + DissentRow absence. Emits SilentConsensusRow proposals with confidence.
- `routers/silent_consensus.py` — `GET /api/projects/{id}/silent-consensus` (list pending) + `POST …/{sc_id}/ratify` (creates DecisionRow with lineage) + `POST …/{sc_id}/reject`.
- Frontend: stream renders `silent-consensus` kind as a soft card: "5 of 5 engineers acted on approach A — ratify as decision?" with ratify/reject buttons. Paired with existing dissent UX on decision cards.
- Perf panel gets a `silent_consensus_ratified` count (additive column).

**Tests:** 4+ — scanner detects unanimous action, ratification crystallizes a DecisionRow, dissent on the topic suppresses proposal, rejection clears the row.

### 1.B Ambient onboarding Day-1 walkthrough (~5k LOC)

New member's first visit to `/projects/[id]` triggers an overlay: sub-agent narrates their graph slice, recent decisions, adjacent teammates, active tasks, open risks — with citations back to nodes. 10-minute compressed ramp.

**Touches:**
- `OnboardingStateRow` ORM — `id, user_id, project_id, first_seen_at, walkthrough_completed_at: nullable, last_checkpoint: str`. Migration `0010_onboarding_state`.
- `services/onboarding.py` — builds a structured walkthrough script given (user_id, project_id) — uses `LicenseContextService` for the slice, sub-agent LLM to narrate, returns ordered sections: vision, recent decisions, adjacent teammates, your tasks, open risks.
- `routers/onboarding.py` — `GET /api/projects/{id}/onboarding/walkthrough` (returns structured script + checkpoint state), `POST …/checkpoint` (advance/complete).
- Frontend: full-viewport overlay on first visit; progress indicator; "Skip for now" dismisses, "Done" marks complete. Re-triggerable from `/settings/profile` ("Replay onboarding"). Citations from walkthrough deep-link to `/projects/[id]/nodes/[nodeId]`.

**Tests:** 4+ — first visit triggers, completed state persists, dismissal persists, license-scoped walkthrough excludes out-of-view nodes.

## Phase 2 — north-star closers, pair B (parallel, after Phase 1 merges)

### 2.A Active membrane ingestion (~6k LOC)

Backend row exists; nothing pulls. Build the active side: URL paste tool, RSS subscription, a single search provider (Tavily) as a function-call tool, a cron agent that wakes periodically and proposes signals.

**Touches:**
- `services/tools/fetch_url.py`, `services/tools/rss_subscribe.py`, `services/tools/web_search.py` (Tavily wrapper, env-gated).
- `services/membrane_ingest.py` — cron agent: given project context, generates 3–5 search queries, fires tool calls, LLM-filters for relevance, writes MembraneSignalRow proposals with source provenance.
- Schedule: reuse existing async task pattern (grep `async def _background` across services). Run every 30 min in dev / hourly in prod. Config via env.
- `routers/membrane.py` — add `POST /api/projects/{id}/membrane/paste` for user-pasted URLs (normalize, fetch, ingest).
- Frontend: `/projects/[id]/page.tsx` composer paste handler detects URLs → offers "Ingest as signal" inline action. `MembraneCard` (existing) renders ingest results.
- Security: prompt-injection gate per vision §5.12 — ingested content never issues graph mutations directly; always human-confirmable. Use existing license-lint as the precedent.

**Tests:** 5+ — URL paste ingests, LLM-filter rejects unrelated content, cron generates queries, Tavily tool stubs cleanly, prompt-injection payload does not mutate graph.

### 2.B Meeting transcript upload (~4k LOC)

Upload-transcript path only. Skip ASR. Feishu Minutes export / Zoom transcript / plain text paste. Metabolized into signals by the edge LLM.

**Touches:**
- `MeetingTranscriptRow` ORM — `id, project_id, uploader_user_id, title, transcript_text, participants: JSON (user_ids best-effort), uploaded_at, metabolism_status: 'pending'|'done'|'failed', extracted_signals: JSON`. Migration `0011_meeting_transcripts`.
- `services/meeting_ingest.py` — on upload, fires the edge LLM to extract: decisions reached, action items (→ TaskRow proposals), risks raised, participants' stances. Writes structured signals into respective rows as *proposals* (not auto-applied).
- `routers/meetings.py` — `POST /api/projects/{id}/meetings` (upload + metabolize), `GET …` list, `GET …/{id}` detail with extracted signals.
- Frontend: `/projects/[id]/meetings` route — upload form, transcript list, detail page with extracted signals + "accept all" / per-signal accept.
- i18n: zh/en 12 keys under `meeting.*`.

**Tests:** 4+ — upload + metabolize extracts signals, empty transcript fails cleanly, signals render as proposals not facts, project-member-only gate enforced.

## Phase 3 — hierarchical KB (alone, after Phase 2 merges)

### 3.A File system / hierarchical KB (~15k LOC)

Flat KB → tree. Per-node licenses. Prerequisite for book rendering and enterprise per-file ACLs.

**Touches:**
- ORM: `KbFolderRow` (id, project_id, parent_folder_id nullable, name, created_by, created_at) + `KbItemRow` gains `folder_id` (nullable during migration, then filled) + `KbItemLicenseRow` (per-item override of project license tier). Migration `0012_kb_hierarchy`.
- `services/kb.py` — folder CRUD, move-item, reparent-folder, cycle detection, per-item license check layered on top of `LicenseContextService`.
- `routers/kb.py` — folder routes + hierarchical list + per-item license override.
- Frontend: `/projects/[id]/kb` becomes a tree browser (left nav: folder tree, right pane: item list or item detail). Drag-reparent. New folder / new item buttons. Per-item license dropdown (inherit / override).
- Audit: existing `/detail/graph` and lineage views continue citing kb items by ID — URLs stable.
- Migration backfill: every existing KbItemRow lands in a root-level `/` folder for that project.

**Tests:** 6+ — folder create/move, item move, cycle detection, license inherit vs override, license-lint on cross-boundary queries, backfill idempotent.

## Dependency diagram

```
  Phase 1 (parallel)                    Phase 2 (parallel)                    Phase 3 (alone)
    1.A Silent consensus ──┐              2.A Active membrane ─┐                3.A File system
    1.B Ambient onboarding ─┤  merge ───► 2.B Meeting upload ──┤  merge ──────►  (hierarchical KB)
                            │                                  │
                            └── gate: pytest + tsc green       └── gate: same
```

## Definition of done (V4)

1. Silent consensus detects unanimous action on the Moonshot demo seed.
2. New-hire walkthrough renders for a cold profile on `/projects/[id]` and respects license slicing.
3. Active membrane ingests an RSS feed and a pasted URL, filters via LLM, surfaces proposed signals.
4. Meeting transcript upload produces extracted signals as proposals (not facts).
5. KB browseable as a tree, drag-reparent works, per-item license override enforced.
6. Full backend suite green (excluding the known `test_ws*` DEEPSEEK env flake + the known `test_profile_auto_evolution` cross-file flake).
7. `bunx tsc --noEmit` clean.
8. Migrations `0009`–`0012` clean on prod DB.

## Deferred to V5

- Org layer above projects (vision cascade, cross-project theses)
- Book rendering (on top of V4 file system)
- Open agent SDK
- Counterfactual at scale (`drop_person`, `delay_milestone`)
- Voice / ASR meeting capture (upload-transcript already covers 80%)
- Mobile-native
