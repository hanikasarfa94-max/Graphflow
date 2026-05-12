# CLAUDE.md — project conventions for AI agents

**Current spec (2026-05-12 pivot):** Read `graphflow_handoff_v062/DESIGN_LOCK.md` for product doctrine, `graphflow_handoff_v062/API_CONTRACT.md` for backend contract, `graphflow_handoff_v062/FRONTEND_IMPLEMENTATION.md` for routes + components, `BUILD-v062.md` for the phased build plan, and `DESIGN.md` for the visual system v3.

`docs/north-star.md` and `docs/architecture.md` are **superseded on IA and shell** but still authoritative on product thesis (decision crystallization, three-graph framing, memory atoms, signal chain). Read them for the *why*, not the *what*.

## Codebase map

**Before any non-trivial code change, read `graphify-out/GRAPH_REPORT.md` first.** It carries the structural map: god nodes (`LLMResult`, `UserRow`, `LicenseContextService`, ORM rows), 646 community clusters with names like *KB / Membrane Domain*, *API Backend Spine*, *Routing & Personal Services*, surprising cross-community edges, and the load-bearing hyperedges (e.g. *"Membrane is the single boundary"*, *"Thin-router pattern"*).

Use it before searching files directly. Two reasons:
- **Cheap**: ~22K tokens per query vs ~600K reading the corpus blind (27× compression).
- **Honest**: every edge is tagged EXTRACTED / INFERRED / AMBIGUOUS, so you know what's structural fact vs model inference.

When the graph and the code disagree, trust the code — but update the graph (`/graphify --update` re-extracts only changed files). The graph is a snapshot in time; treat it like git blame, not a live source of truth.

When using graphify for architectural orientation, skip test-mirror communities unless investigating a specific regression. Test-mirror communities mostly reflect production structure and should not be loaded for general architecture diagnosis. (61 such communities exist as of the 2026-04-27 snapshot, ~20% of all nodes — full list in `graphify-out/GRAPH_REPORT.md` under any community whose label contains "Tests".)

## Architectural invariants (graph-confirmed)

These patterns are universal in the codebase and confirmed by graph hyperedges (`graphify-out/GRAPH_REPORT.md` §Hyperedges). Violating them creates drift; new code must follow them.

- **Thin routers.** Routers do exactly four things: pydantic validation → membership gate (via `ProjectMemberRepository.is_member`) → service call → service-error → HTTP status. **No business logic in routers.** If you find yourself reaching for a repository directly from a router, the logic belongs in a service. (Hyperedge: *"Thin-router pattern: pydantic validation + membership gate + service exception → HTTP status code"*, EXTRACTED 0.95.)
- **Membrane is one boundary.** All scope-into-cell writes (`KbItemRow scope='group'`, decision crystallization, edge promotion, route-confirm) flow through `MembraneService.review()`. Don't add a parallel review path for a new candidate kind — extend `CandidateKind` instead. (Hyperedge: *"Membrane is the single boundary"*, EXTRACTED 1.00. See `docs/membrane-reorg.md`.)
- **LLM orchestration lives in `packages/agents/`.** All `LLMClient` instantiation is in agent files; no exceptions. Services orchestrate (DB writes, lifecycle, event emission, accept-as-row plumbing); agents call LLMs and own the prompt + structured-output schema. New LLM-using code goes in `packages/agents/`, not `apps/api/services/`.
- **License gate is single-source.** Tier filtering goes through `LicenseContextService`; emitted replies are validated by `lint_reply()`. Don't bypass either — the fail-closed default ("unknown tier → observer") only works if both paths are honored.

## Bug Graphify protocol

Before fixing a bug involving state, async behavior, API contracts, permissions, persistence, agent behavior, or UI rendering, do not patch immediately.

First perform a graph-based diagnosis:

1. Identify the visible symptom.
2. Use graphify to explain the suspected node.
3. Use graphify to trace the path from the user action or API entrypoint to the symptom.
4. Mark all mutation points, async boundaries, persistence boundaries, and rendering boundaries.
5. Identify the first divergence between expected and actual behavior.
6. Patch the earliest responsible boundary, not the latest visible symptom.
7. Add or update a regression test for the same path.

## Design System

**Always read `DESIGN.md` before making any visual or UI decisions.** All font choices, colors, spacing, and aesthetic direction are defined there. Do not deviate without explicit user approval.

- Inline `style={{}}` blocks are a code-smell — prefer the `<Button> / <Card> / <Heading> / <Text> / <EmptyState>` primitives in `apps/web/src/components/ui/`.
- Hex literals outside `globals.css` and `DESIGN.md` are not allowed. Reference CSS variables.
- Motion is load-bearing for 5 specific moments (see `DESIGN.md §Motion`). Everywhere else: restraint.
- `prefers-reduced-motion: reduce` respected everywhere.
- Dark mode is a full redesign, not an inversion. Author every component with both modes in mind.
- In QA / code review: flag any code that doesn't match `DESIGN.md`.

## Plans

- `BUILD-v062.md` — **current build plan** (Phase A → F, written 2026-05-12).
- `graphflow_handoff_v062/` — locked v0.6.2 spec bundle (DESIGN_LOCK, API_CONTRACT, FRONTEND_IMPLEMENTATION, INVARIANT_TESTS, BUILD_PLAN, PRODUCTION_GAP_LIST, schemas).
- `DESIGN.md` — visual system v3 (rewritten 2026-05-12).
- `docs/north-star.md` — product thesis (IA superseded; thesis stands).
- `docs/architecture.md` — three-graph framing reference (IA superseded; framing stands).
- `PLAN-v3.md`, `PLAN-v4.md` — completed build plans, historical record.
- `docs/competition.zh-CN.md` — ByteDance competition submission (competition over).

## Archived docs (do not read as current spec)

- `docs/dev.md`, `docs/eng_backlog.md`, `docs/prompt-contracts.md`, `docs/resume.md`, `docs/signal-chain-plan.md`
- `PLAN.md`, `PLAN-v2.md`
- `AGENT.md`
- `docs/shell-v-next.txt` (v-Next direction abandoned; superseded by v0.6.2 pivot)

All carry archive banners. Treat as historical.
