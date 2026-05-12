# GraphFlow v0.6.2 — Engineering Handoff

Status: engineering interaction spec, desktop-first prototype, not final production UI.

## Package contents

- `graphflow_v062_production_handoff.html`: cleaned handoff HTML. Prototype-only design controls removed.
- `graphflow_v062_adjustable_layout_prototype.html`: original adjustable layout prototype with design controls.
- `DESIGN_LOCK.md`: locked product doctrine and IA.
- `API_CONTRACT.md`: backend API contract.
- `FRONTEND_IMPLEMENTATION.md`: routes, components, state boundaries.
- `INVARIANT_TESTS.md`: CI tests to prevent doctrine drift.
- `PRODUCTION_GAP_LIST.md`: edge states still requiring specs.
- `BUILD_PLAN.md`: suggested implementation order.
- `schemas.graphflow.json`: enum/type map.

## Locked primary surfaces

1. My AI
2. Conversations
3. Tasks
4. Documents / KB
5. Flow Center

Do not add Project, Graph, Memory, Capability, or Embedded Views as primary navigation.

## Locked doctrine

- My AI is the landing surface.
- Project is scope, not page.
- Project Brief is a pinned KB document.
- Graph / Memory / Capability are embedded, not primary pages.
- AI Assistance creates proposals only.
- Actions mutate state.
- Task / Topic / Flow / Memory are context-born objects.
- Memory acceptance is authority-gated and lineage-preserving.
- Server computes permissions; client renders allowed actions.

## First engineering move

Implement the shell, nav invariant, scope band, drawer host, right rail spine, and create-menu exclusions first. Then wire Flow → Memory Candidate Review because it carries the hardest doctrine contracts.
