# GraphFlow — Architecture Organization Pass v1

**Status:** written 2026-05-07. This doc explains how the codebase's package layout maps to the north-star concepts (World Graph / Org Graph / Work Graph / Membrane / Router-Edge Agent), and what the in-progress reorganization is doing. It is the durable companion to `docs/north-star.md` (product intent) and `docs/architecture.md` (visual summary).

> Phase A is complete on disk. Phases B–F are running in parallel agents; their status here is a snapshot and may go stale within hours. Trust the code if it disagrees with this doc, then update this doc.

---

## 1. Why this pass exists

The codebase has strong concepts but several god files. `apps/api/src/workgraph_api/services/flow_projection.py` was 2 809 lines before Phase A; `services/membrane.py` is 2 563 lines, `services/im.py` 1 471, `services/personal.py` 1 503, `services/skills.py` 1 323, and `apps/web/src/lib/api.ts` is 3 123 lines. Each of these is a single Python or TypeScript module that mixes orchestration, contracts, persistence helpers, recipe-specific logic, and visibility rules. New contributors cannot tell which lines implement which concept; refactors create rebase pain; tests bind to internal symbols rather than to the boundary the concept actually defines.

This pass turns each load-bearing concept into a code boundary. Concepts → packages → sub-modules. No big-bang rewrites, no behavior changes in the first pass — just structural decomposition that makes the next round of feature work cheaper.

---

## 2. North-star concept → code package map

The five north-star primitives (cell, membrane, three graphs, router/edge agent) map onto packages as follows. Every path is verified to exist as of 2026-05-07.

| Concept (north-star / vision) | Code home |
|---|---|
| **World Graph** — facts, decisions, KB, conflicts, gated proposals (the cell's shared knowledge) | `apps/api/src/workgraph_api/services/{kb_items.py, decisions.py, conflicts.py, gated_proposals.py}` plus the supporting `kb_hierarchy.py`, `dissent.py`, `silent_consensus.py` |
| **Org Graph** — skills, capability atlas, project membership, manual policies | `apps/api/src/workgraph_api/services/{skills.py, skill_atlas.py, org_graph.py, org_capabilities.py, organizations.py, project.py}` plus the manual-skill-change / manual-invite / manual-room candidate kinds |
| **Work Graph** — tasks, progress, handoff, delivery, routed signals | `apps/api/src/workgraph_api/services/{task_progress.py, handoff.py, delivery.py, routing.py, commitments.py}` |
| **Membrane** — single boundary for scope-into-cell writes | `apps/api/src/workgraph_api/services/membrane.py` (today) → `services/membrane.py` + `services/membrane_policies/` (after Phase B) |
| **Router / Edge Agent** — per-user sub-agent, parent routing hub, IM surface | `apps/api/src/workgraph_api/services/{personal.py, im.py, routing.py, pre_answer.py}` plus all `LLMClient` instantiation sites in `packages/agents/src/workgraph_agents/{edge.py, clarification.py, conflict_explanation.py, drift.py, planning.py, pre_answer.py, render.py, membrane_reviewer.py, meeting_ingest.py}` |
| **Flow Packets** — projection over the Graph layer | `apps/api/src/workgraph_api/services/flow_packets/` (internals) + `services/flow_projection.py` (facade, public import path preserved) |
| **License gate** — fail-closed tier filter, single source | `apps/api/src/workgraph_api/services/license_context.py` + `services/license_lint.py` |

**Bidirectional invariant.** No service in any of those packages instantiates `LLMClient` directly. LLM orchestration lives in `packages/agents/`; services orchestrate (DB writes, lifecycle, event emission, accept-as-row plumbing) and call into `workgraph_agents` for the LLM step. Routers (`apps/api/src/workgraph_api/routers/*.py`) stay thin — pydantic validation → membership gate via `ProjectMemberRepository.is_member` → service call → service exception → HTTP status code. (Confirmed by the *"Thin-router pattern"* hyperedge in `graphify-out/GRAPH_REPORT.md`, EXTRACTED 0.95.)

---

## 3. Phase-by-phase status

The pass is split into seven phases, A–G. Each phase carves out one god file or one frontend layout convention. Phases run mostly independently; the only ordering constraint is that Phase A had to land first because every later phase uses its facade pattern as a template.

### Phase A — `flow_projection.py` decomposition `[done]`

The original `flow_projection.py` (2 809 lines) held the projection contract types, eight per-recipe derivation functions, viewer-side visibility filters, sort/limit, the participants sidecar resolver, and the `FlowProjectionService` class itself. Phase A moved everything except the orchestration class into `apps/api/src/workgraph_api/services/flow_packets/`. The facade at `services/flow_projection.py` is now 165 lines (verified) and its only job is to import from the sub-package and run the six-step pipeline.

Sub-package layout, with line counts as of 2026-05-07:

```
apps/api/src/workgraph_api/services/flow_packets/
├── __init__.py            22   public read-order docstring
├── contracts.py          282   Bucket, PacketStatus, RecipeId, packet factories
├── visibility.py         114   _project_owner_ids, _visible_to, _matches_bucket
├── sorting.py             26   sort_and_limit
├── participants.py        53   _resolve_participants sidecar
└── projectors/
    ├── __init__.py        27   re-exports the eight derive_* functions
    ├── decision.py       573
    ├── handoff.py        193
    ├── kb_review.py      290
    ├── manual_invite.py  187
    ├── manual_room.py    212
    ├── manual_skill_change.py  204
    ├── route.py          442
    └── task_promote.py   273
```

The pre-existing `from workgraph_api.services import FlowProjectionService` import path is unchanged; tests pass without modification because the public surface is byte-identical. The shape — facade in original location, internals in a sibling sub-package, one sub-module per concern — is the template for phases B, C, E, F.

### Phase B — `membrane.py` decomposition `[in progress as of 2026-05-07, may be done by the time you read this]`

`apps/api/src/workgraph_api/services/membrane.py` is 2 563 lines and carries two parallel entry points (`ingest()` for external signals and `review()` for internal candidates), eight `CandidateKind` policies, the auto-approve gate, and the LLM-reviewer plumbing for shared-memory writes (see `docs/membrane-agent-review-spec.md`). Phase B intends to lift each `CandidateKind` policy into its own file under `services/membrane_policies/`, leaving `membrane.py` as the orchestration facade — the same pattern as Phase A. Today, `services/membrane_policies/` does not yet exist on disk; expect it to appear shortly. The single-membrane invariant ("Membrane is the single boundary", EXTRACTED 1.00 in the graph report) must be preserved: there is exactly one `MembraneService.review()` entry, and Phase B's job is to make that obvious in the layout, not to add a parallel review path.

### Phase C — `im.py` and `personal.py` decomposition `[in progress]`

These two services are the Router/Edge surface. `im.py` (1 471 lines) handles the IM stream and `IMService`'s suggestion flow; `personal.py` (1 503 lines) is the per-user general-agent stream and the routing inbox. They share concepts (stream membership, license-scoped slice assembly, sub-agent attribution, paste-to-dispatch parsing) but have grown side-by-side rather than through a shared core. Phase C will extract the shared concerns (stream visibility, paste parsing, attribution sub-turn formatting) into helpers and leave each service as a thin orchestrator over its own surface. Sibling helpers `_kb_visibility.py`, `_retrieval_primitives.py`, and `_embeddings.py` already follow this convention.

### Phase D — frontend `lib/api.ts` to feature modules `[in progress]`

`apps/web/src/lib/api.ts` is 3 123 lines and concentrates every TypeScript API client function for the entire web app. The migration target is `apps/web/src/features/<feature>/{api.ts, types.ts, hooks/, components/}` with imports via `@/features/<feature>/...`. The pilot extraction is `features/kb/api.ts` (the KB browseable-corpus client). `lib/api.ts` re-exports the `features/kb/api` symbols at lines 2 064–2 090 so existing call sites that import from `@/lib/api` continue to compile; the file becomes a re-export shim feature by feature until empty, at which point it can be deleted. Today, `apps/web/src/features/` contains only `kb/`; `rooms`, `decisions`, `streams`, `routing`, `tasks`, `kb-items`, `membrane`, `flows` all remain inside `lib/api.ts`.

### Phase E — `skills.py` decomposition `[in progress]`

`apps/api/src/workgraph_api/services/skills.py` is 1 323 lines. The Org-Graph concept it implements is well-defined (skills, skill assignments, manual-skill-change candidates, capability lookups) but the file mixes the read API, the write API, the manual-change candidate flow, and the skill-atlas computation. Phase E follows the Phase A template: facade at `services/skills.py`, internals split by concern. The Org-Graph concept includes adjacent files (`skill_atlas.py`, `org_capabilities.py`, `org_graph.py`); whether these get folded into a single `services/org/` package or kept as siblings is an open Phase E decision.

### Phase F — schema/contract surface tightening `[planned]`

The pass's principle that *invariants live in services / contracts / tests, not in prompts* implies that the contract types projected to the frontend (`FlowPacket`, `RecipeId`, `Bucket`, `PacketStatus`, the various router request/response models) need a single canonical home. Today they are scattered across `services/flow_packets/contracts.py`, `routers/*.py` pydantic models, and TypeScript shapes redeclared in `lib/api.ts`. Phase F's scope is to lift contract types into a discoverable layer (probably `apps/api/src/workgraph_api/contracts/` plus a generated TS definition file) so the frontend cannot drift from the backend silently. This phase is explicitly planned, not yet started.

### Phase G — this doc `[done]`

Phase G is documentation only: write `docs/architecture-organization.md` (this file), add one-line cross-references at the top of `docs/north-star.md` and `docs/architecture.md` pointing here. No code changes.

---

## 4. The four refactor principles

Every phase honors these four constraints. They are restated from the pass spec.

1. **No big-bang rewrite.** Each phase decomposes one god file, preserving the public import path via a facade. Other phases keep working in parallel because nothing imports from internals across phase boundaries.
2. **Concepts must become code boundaries.** A boundary is a directory or a module, not a comment. If two concepts live in the same file, future contributors will fail to keep them separate. The Phase A six-file `flow_packets/` package is the calibration point.
3. **Prompt rules are not architecture.** A rule that exists only inside an LLM prompt ("the membrane LLM should not approve PII") is not enforceable; it must also exist as a service-layer guard, a contract validator, or a test. Architecture invariants live in code paths, not in prompt text.
4. **Projection stays read-only. Routers stay thin.** `FlowProjectionService` cannot mutate source rows (§15 of `docs/flow-packets-spec.md`); routers do exactly four things (pydantic validation → membership gate → service call → exception-to-status mapping). New code that reaches for a repository directly from a router is a violation; the logic belongs in a service.

---

## 5. The Phase A pattern, as a template

Phases B, C, E, F all follow this shape. New contributors picking up an in-flight phase should reproduce it.

1. **Facade in original location preserves the public import path.** The original module file becomes the orchestration class plus its imports. External code (`from workgraph_api.services import X`) is not aware the decomposition happened.
2. **Internals move to a sibling sub-package** named after the concept (`flow_packets/`, `membrane_policies/`, etc.). The sub-package's `__init__.py` carries a read-order docstring telling new contributors which file to open first.
3. **One sub-module per concern.** The Phase A split was: `contracts.py` (pure types and factories), `visibility.py` (gating), `sorting.py` (sort/limit), `participants.py` (sidecar resolver), `projectors/<recipe>.py` (one file per polymorphic case). The recipe pattern — one file per `CandidateKind`, `RecipeId`, or comparable enum value — recurs in Phases B and E.
4. **Tests pass without modification.** Behavior is unchanged. The decomposition is structural. If a test breaks, the refactor is wrong.
5. **Line counts shrink on the facade and spread across small files.** Phase A: 2 809 → 165 in the facade; the rest spread across 13 files averaging ~210 lines each. The average is the goal — under ~600 lines per file, ideally under ~300.

---

## 6. Frontend feature module convention

Phase D extends the same idea to the web app.

```
apps/web/src/features/<feature>/
├── api.ts          fetch/request functions + response shapes
├── types.ts        shared types (FlowPacket, KbItem, etc.)
├── hooks/          react hooks bound to this feature's state
└── components/     feature-scoped UI primitives
```

Cross-imports go through `@/features/<feature>/...`. `apps/web/src/lib/api.ts` becomes a re-export shim until every feature has been pulled out, at which point the shim is empty and can be deleted. Until then, both import paths work. The pilot module is `apps/web/src/features/kb/api.ts`; `lib/api.ts` re-exports its public symbols at lines 2 064–2 090 with an explanatory comment noting the shim status.

Generic primitives — `<Button>`, `<Card>`, `<Heading>`, `<Text>`, `<EmptyState>` — stay in `apps/web/src/components/ui/`. Feature components are not generic primitives; they live next to the feature's API client.

---

## 7. Migration plan / open work

Rough sizing, useful for picking up an in-flight phase. Estimates assume a single contributor working in focused blocks; parallelism shortens elapsed time but not effort.

- **Phase B (membrane).** ~2 days. Eight `CandidateKind` policies, a shared LLM-reviewer call, the auto-approve gate. Risk: keeping the *single membrane* invariant visible in the new layout (the `__init__.py` should make this obvious or a future contributor will add a second review path).
- **Phase C (im + personal).** ~3 days. Two services that grew in parallel; some shared concerns are not yet factored. Likely outcome: a `services/streams/` shared core plus thin im/personal facades. Risk: stream membership and license slicing are touched by both — extraction order matters.
- **Phase D (frontend features).** ~1 day per feature, ~6 features remaining (rooms, decisions, streams, routing, tasks, membrane). Phase D can ship feature by feature; it has no all-or-nothing cutover. Risk: TypeScript types currently redeclared in `lib/api.ts` need to move with their feature, not be left behind.
- **Phase E (skills + org).** ~2 days. Open question: whether to fold `skill_atlas.py`, `org_capabilities.py`, `org_graph.py` into one `services/org/` package or keep them as siblings of a decomposed `services/skills/` package. Resolve before starting.
- **Phase F (contracts).** ~3 days. Larger because it spans backend and frontend. Should not begin until Phase D has migrated at least three features (the patterns we'd codify aren't visible until then).
- **Phase G (this doc).** Done. Maintenance is one-line updates as later phases land.

### Open architecture debt

A handful of north-star concepts do not yet have a clean code home. These are not failures of the current pass; they are observations worth recording so a later pass can pick them up.

- **Tasks.** The Work Graph map cites `services/task_progress.py` (verified to exist) but there is no `services/tasks.py` — task lifecycle and task progress are entangled across `task_progress.py`, `delivery.py`, and parts of `routing.py`. A future pass may want a dedicated `services/tasks/` package.
- **Edge agent.** The Router/Edge concept is implemented across `services/personal.py`, `services/im.py`, `services/routing.py`, `services/pre_answer.py`, and `packages/agents/src/workgraph_agents/edge.py`. There is no single "edge agent" file or package; Phase C will help, but a longer-term consolidation is open.
- **Streams.** The four stream types (personal, project, dm, future rehearsal/group) share renderer logic on the frontend but are dispatched by ad-hoc switches in several services (`im.py`, `personal.py`, `streams.py`, `room_timeline.py`). A future pass may unify the stream-kind discrimination in one place.
- **Profile / signal-affinity.** `UserRow` profile fields and `signal_tally.py` / `profile_tallies.py` / `perf_aggregation.py` together implement the response-profile primitive (north-star §Profile-as-first-class), but the boundary between rolling-window tallies and profile-as-routing-hint is not crisp. Not a Phase A–F target; flagged for later.

---

## 8. Verification rules for this doc

When updating this doc as later phases land, re-verify each cited path with a directory listing — do not trust the previous edit. Phase A's `flow_packets/` line counts are pinned to disk reality as of 2026-05-07; if they drift by more than ~10% the doc should be re-counted, not patched. Two specific spot-checks:

- `wc -l apps/api/src/workgraph_api/services/flow_projection.py` should be roughly 165 (the facade). If it grows past ~250, someone added orchestration logic that probably belongs in a sub-module.
- `apps/web/src/features/` should contain a directory per migrated feature. If `lib/api.ts` line count is dropping but `features/` is not gaining directories, the migration is being done as raw deletes rather than as feature extractions, which would break the re-export shim contract.

---

## 9. Where to look first

For new contributors arriving without context: read in this order.

1. `docs/north-star.md` — what the product is.
2. `docs/architecture.md` — the visual summary.
3. This file — how the code is organized to embody those concepts.
4. `graphify-out/GRAPH_REPORT.md` — the structural snapshot, including hyperedges naming the architectural invariants ("Thin-router pattern", "Membrane is the single boundary", "License gate is single-source"). Use it before searching files blindly; it's ~22 K tokens to query vs. ~600 K to read the corpus.
5. `apps/api/src/workgraph_api/services/flow_packets/__init__.py` — the canonical example of the package read-order docstring pattern this pass uses.

`CLAUDE.md` at repo root is the operational summary of the same invariants for AI agents working on the code; this doc is the human-readable companion.
