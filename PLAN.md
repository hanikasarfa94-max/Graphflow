# PLAN.md

Current implementation plan for **WorkGraph AI**.

This file is the execution sequencing document for engineering agents and human collaborators.
It should be read after `docs/dev.md` and `AGENTS.md`.

---

## 1. Goal of This Plan

This plan exists to answer one question:

**What should be built now, in what order, and what counts as done at each step?**

This is not the full system specification.
The source of truth for behavior remains `docs/dev.md`.

This plan is optimized for:
- Codex execution
- Opus / Claude execution
- human implementation tracking
- fast MVP convergence
- demo reliability

---

## 2. Build Strategy

The MVP must be built as an **end-to-end vertical slice**, not as disconnected subsystems.

The correct build order is:

1. intake
2. parsing
3. graph initialization
4. planning
5. state sync
6. conflict detection
7. human decision loop
8. delivery summary
9. demo polish

Do not prioritize polish, abstraction, or advanced infrastructure before the core workflow works.

---

## 3. MVP Success Condition

The MVP is successful when the following scenario works end-to-end:

1. a Feishu message creates a project
2. the requirement is parsed into structured workflow state
3. the system asks a small number of useful clarification questions
4. the system generates tasks, risks, and dependencies
5. the system syncs state into Feishu Base and Docs
6. the system detects a scope-vs-deadline conflict
7. the system proposes 2–3 resolution options
8. a human approves one option
9. the graph state updates correctly
10. the system generates a delivery summary

This is the canonical demo path.
Anything that does not support this path is secondary.

---

## 4. Delivery Phases

## Phase 0 — Freeze the MVP Shape

### Objective
Lock the MVP shape so implementation does not drift.

### Deliverables
- `docs/dev.md`
- `AGENTS.md`
- `PLAN.md`
- `docs/engineering-backlog.md`
- `docs/prompt-contracts.md`
- `docs/demo-script.md`

### Exit Criteria
- architecture direction is fixed
- MVP scope is fixed
- canonical demo scenario is fixed
- domain objects and states are fixed

### Notes
No coding expansion should happen before this phase is clear.

---

## Phase 1 — Project Skeleton

**Status:** ✅ Complete (2026-04-17). 15/15 tests passing. All three apps boot; `x-trace-id` roundtrip verified; `/_debug/boom` returns `ApiError` shape with `trace_id`; web at :3000 and web `/api/health` green.

### Objective
Create a runnable repository skeleton with the correct module boundaries.

### Scope
- monorepo or multi-app structure
- backend app
- worker app
- web app
- shared schema/domain packages
- base environment configuration

### Tasks
- initialize repository layout
- create backend app
- create worker app
- create web app
- create shared package folders
- configure lint/format/test commands
- add `.env.example`

### Acceptance Criteria
- all apps boot locally
- shared packages can be imported
- repository structure matches `docs/dev.md`
- environment variables fail clearly when missing
- `ApiError` Pydantic model exists in shared schema package with `code`, `message`, `details` fields (2C5)
- unified error handler converts uncaught exceptions to `ApiError` responses
- unit tests exist and pass for env loader + error handler (2C1)
- structured logging configured with `trace_id` propagation (2C2)

### Validation
- API app starts
- worker app starts
- web app starts
- basic health endpoint passes
- induce a 500; verify response matches `ApiError` schema

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 2 — Requirement Intake

**Status:** ✅ Complete (2026-04-17). 34/34 tests green across unit + integration + canonical E2E. API path and Feishu webhook both route through `IntakeService.receive()` → identical `IntakeResult` shape. Dedup enforced via `UniqueConstraint(source, source_event_id)`; race-safe via IntegrityError fallback. `intake.received` events persisted with trace_id on every attempt (including dedup). EventBus is the Phase 12 Inngest swap point.

**Deferred to later phases:**
- Real Inngest dashboard visibility (Phase 12 swap per decision 1A)
- Real Feishu SDK signature verification (Phase 7)
- UTC timezone normalization on SQLite read-back (cosmetic; fixes itself under Postgres at Phase 5)

### Objective
Allow raw requirement input to enter the system and create a project.

### Scope
- Feishu event intake path
- direct intake API
- normalized intake event
- project and requirement persistence

### Tasks
- implement Feishu event receiver
- normalize incoming messages
- deduplicate repeated events
- persist raw event log
- create `POST /api/intake/message`
- create Project record
- create Requirement record

### Acceptance Criteria
- a message can create one project exactly once
- duplicate events do not create duplicate projects
- intake state is persisted
- API path and Feishu path produce the same domain result
- unit + integration tests exist and pass (dedup, persistence, API↔Feishu parity) (2C1)
- `intake.received` Inngest event emitted with `trace_id`; visible in Inngest dashboard (2C2)
- `tests/e2e/canonical_event_registration.py` created with intake assertion; will be extended in every subsequent agent phase (3B)

### Validation
- send a local API request
- trigger a Feishu event or mock payload
- inspect DB rows for project + requirement + event log
- run canonical E2E fixture; passes at this phase's assertion set

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 2.5 — Eval Harness

### Objective
Build the LLM quality ruler before any agent ships. You cannot measure regressions on an agent you haven't evaluated from day one.

### Scope
- eval dataset (canonical + adversarial fixtures)
- pytest-compatible eval runner
- per-agent pass-rate thresholds
- CI gate blocking agent-phase merges on regression

### Tasks
- create `tests/eval/dataset/` directory with YAML/JSON fixtures for Requirement, Clarification, Planning, Conflict Explanation, Delivery agents (10-20 cases each, including the canonical event-registration scenario + 3-5 adversarial cases per agent)
- implement `tests/eval/runner.py` — loads fixtures, invokes agent with versioned prompt, compares output to expected shape + key fields
- emit per-agent pass-rate metric + drift-vs-prior-prompt-version metric (ties to 2C3 prompt versioning)
- wire CI: fail PR if eval pass rate <80% OR drops ≥5pp vs main on touched agent
- pick eval tooling: promptfoo suggested as Layer 1 starting point (free, local, prompt versioning built-in); LangSmith optional later for tracing
- document how each subsequent agent phase adds its eval fixtures + thresholds

### Acceptance Criteria
- runner executes one agent × N fixtures, returns pass/fail per case
- CI fails a PR that introduces a ≥5pp regression on any agent
- golden-path canonical event-registration fixture scores 100% on a baseline Requirement-agent prompt
- unit tests exist and pass for fixture loader + scoring functions (2C1)
- eval runs emit structured logs per case (agent, prompt_version, pass/fail, drift) (2C2)
- Phase 2.5 is a hard prerequisite for Phases 3, 4, 6, 8, 10

### Validation
- run evals locally against a stub Requirement agent; confirm pass/fail output
- submit a PR that intentionally breaks a prompt; CI blocks merge
- confirm dashboard output is readable and shows drift

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 3 — Requirement Parsing

### Objective
Convert raw requirement text into structured workflow objects.

### Scope
- Requirement Agent
- parsing schema
- confidence handling
- open question detection

### Tasks
- implement `parse_requirement()`
- define schema for parser output
- extract summary
- extract goals
- extract deliverables
- extract constraints
- extract risks
- extract open questions
- implement fallback handling for malformed LLM output

### Acceptance Criteria
- parsing returns valid structured JSON
- unknown information is not hallucinated
- blocking ambiguities are surfaced as open questions
- parsed result is stored in the database
- unit + integration tests exist and pass, including the 4 canonical-scenario fields (event_registration intent, 2026-04-24 deadline, 4 scope items, 2-3 open_questions) (2C1)
- Requirement-agent eval suite passes ≥80% via Phase 2.5 harness (3A)
- `agent_run_log` row written per call with `prompt_version`, `latency_ms`, `token_count`, `cache_read_input_tokens`, `outcome` (ok|retry|manual_review); `requirement.parsed` Inngest event visible in dashboard with `trace_id` (2C2)
- LLM failure recovery: retry-once on malformed JSON → Instructor/Pydantic fallback parser → third failure raises `manual_review` flag; fault-injection test asserts graceful degradation, never 500 (2C4)
- prompts use `cache_control` breakpoints; integration test asserts `cache_read_input_tokens > 0` on warm call; p50 agent latency <1.5s warm / <4s cold (4A)
- prompts stored at `packages/agents/prompts/requirement/v<N>.md` with version bump on every change (2C3)
- canonical E2E fixture extended: asserts 4 scope items, deadline, confidence >0.7 (3B)

### Validation
- run parser on canonical demo requirement
- run parser on incomplete requirement
- run parser on noisy requirement
- verify JSON shape and persistence
- run Phase 2.5 eval suite against requirement agent
- run canonical E2E fixture; Phase 3 assertions pass

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 4 — Clarification Loop

### Objective
Ask only the minimum useful questions required to unblock planning.

### Scope
- Clarification Agent
- clarification question generation
- reply submission endpoint
- requirement version update

### Tasks
- implement clarification question generator
- limit questions to 3 or fewer
- add `POST /api/projects/{project_id}/clarify-reply`
- merge clarification answers into updated requirement version
- update project stage after clarification

### Acceptance Criteria
- unclear requirements generate focused questions
- over-questioning does not happen
- answers update the requirement version
- clarified requirement can move to planning
- unit + integration tests exist and pass (question-count cap, answer-merge, stage transition) (2C1)
- Clarification-agent eval suite passes ≥80% via Phase 2.5 harness (3A)
- `agent_run_log` + `clarification.generated` / `clarification.answered` Inngest events with `trace_id` (2C2)
- LLM failure recovery: retry-once → fallback parser → `manual_review` flag; fault-injection test (2C4)
- prompt caching enabled; cache-hit assertion + latency budget (4A)
- prompts stored at `packages/agents/prompts/clarification/v<N>.md` (2C3)
- canonical E2E fixture extended: ≥1 open_question generated, routed to correct Feishu channel (3B)
- transition away from Clarification triggered by graph query, not a `current_stage` field write (1E)

### Validation
- canonical requirement with one missing detail
- vague requirement with multiple ambiguities
- answered clarification triggers next stage
- run Phase 2.5 eval suite against clarification agent
- run canonical E2E fixture; Phase 4 assertions pass

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 5 — WorkGraph Initialization

### Objective
Create stable internal workflow state from parsed and clarified input.

### Scope
- domain entities
- DB schema
- graph builder
- relation storage
- project stage update

### Tasks
- implement domain models
- create database migrations
- create repositories
- build graph initialization service
- create Goal / Deliverable / Constraint / Risk records
- support requirement version linking

### Acceptance Criteria
- graph state can be reconstructed from DB
- relationships are explicit
- one requirement produces a stable project snapshot
- stage transitions are valid
- **no `Project.current_stage` column exists; project stage is derived by graph traversal over entity statuses** (1E — graph-native state)
- derived "stage" views (if any) are materialized via Postgres view or computed property, never a denormalized column write
- unit tests exist and pass for graph builder + traversal queries that answer "what stage are we in" (2C1)
- graph state changes emit domain events visible in Inngest dashboard with `trace_id` (2C2)
- canonical E2E fixture extended: graph entities (Goal/Deliverable/Constraint/Risk) present and queryable (3B)

### Validation
- create project from canonical requirement
- inspect stored goals, deliverables, constraints, risks
- verify project stage is computed correctly from a graph query, not read from a denormalized field
- grep for `project.current_stage =` — zero writes allowed
- run canonical E2E fixture; Phase 5 assertions pass

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 6 — Planning Engine

### Objective
Generate a usable delivery plan from confirmed requirement state.

### Scope
- Planning Agent
- task generation
- dependency generation
- milestone generation
- planning persistence

### Tasks
- implement Planning Agent
- define planning output schema
- persist Deliverables
- persist Tasks
- persist Dependencies
- persist Milestones if modeled
- persist new Risks found during planning

### Acceptance Criteria
- planning output is valid JSON
- generated tasks are executable, not vague
- dependencies are explicit
- acceptance criteria exist for tasks
- planned project can be synced to Feishu Base
- unit + integration tests exist and pass (task decomposition, dependency validation, orphan/cycle detection) (2C1)
- Planning-agent eval suite passes ≥80% via Phase 2.5 harness (3A)
- `agent_run_log` + `planning.produced` Inngest events with `trace_id` (2C2)
- LLM failure recovery: retry-once → fallback parser → `manual_review` flag; fault-injection test (2C4)
- prompt caching enabled; cache-hit assertion + p50 <1.5s warm (4A)
- prompts stored at `packages/agents/prompts/planning/v<N>.md` (2C3)
- canonical E2E fixture extended: task DAG has ≥6 tasks; critical path includes backend + frontend + OTP (3B)

### Validation
- run planning on canonical scenario
- inspect tasks and dependencies
- verify no orphan tasks are produced
- verify no circular dependency is introduced by default
- run Phase 2.5 eval suite against planning agent
- run canonical E2E fixture; Phase 6 assertions pass

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 7 — Feishu State Sync

### Objective
Make the workflow visible in Feishu.

### Scope
- Base sync
- Docs sync
- object binding persistence

### Tasks
- create Base sync service
- create/update task records
- create/update risk records
- create/update conflict records
- create Docs summary service
- create requirement summary doc
- create planning summary doc
- persist Feishu object bindings

### Acceptance Criteria
- project state appears in Base
- repeated sync updates instead of duplicating
- docs are readable and consistent with graph state
- sync errors are logged and retriable
- **uses Feishu Base `batch_create` endpoint (100 rows/call)** — no per-row loops (4B)
- **outbound Feishu calls gated by token-bucket limiter: 20 QPS on Base API, 50/min on message API per bot; shared limiter across Inngest workers** (4B)
- **429 responses trigger exponential backoff with jitter, up to 3 retries; 5xx same policy; final failure surfaces to operator via Inngest audit UI** (4B)
- **load test: sync an 80-row graph (50 tasks + 20 requirements + 10 conflicts) completes with zero manual retries** (4B)
- unit + integration tests exist and pass (idempotency, binding persistence, rate-limit behavior) (2C1)
- `sync.started` / `sync.completed` / `sync.throttled` Inngest events with `trace_id`; `sync_log` table records per-call latency + outcome (2C2)
- fault-injection test: mocked 429 response produces successful retry, not failure (2C4)
- canonical E2E fixture extended: Feishu Base rows match parsed entities; zero manual retries in test run (3B)

### Validation
- run sync for canonical project
- verify Base tables contain tasks, risks, conflicts
- verify docs are created and updated
- re-run sync and confirm idempotent update behavior
- run 80-row load test; confirm no 429-induced failures
- run canonical E2E fixture; Phase 7 assertions pass

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 8 — Conflict Detection

### Objective
Detect delivery conflicts before humans need a meeting.

### Scope
- rule-based detection
- LLM-assisted explanation
- suggestion generation
- conflict persistence

### Tasks
- implement deadline-vs-scope rule
- implement dependency-blocking rule
- implement missing-owner rule
- implement blocked-downstream rule
- implement conflict explanation agent
- generate 2–3 options per conflict
- persist conflict objects

### Acceptance Criteria
- at least 3 conflict types are detectable
- every critical conflict has a summary and options
- conflict severity is explicit
- conflicts can trigger escalation
- unit + integration tests exist and pass (rule detection, option generation, severity classification) (2C1)
- Conflict-Explanation-agent eval suite passes ≥80% via Phase 2.5 harness (3A)
- `agent_run_log` + `conflict.detected` / `conflict.explained` Inngest events with `trace_id` (2C2)
- LLM failure recovery on explanation agent: retry-once → fallback parser → `manual_review` flag; fault-injection test (2C4)
- prompt caching enabled on explanation agent; cache-hit assertion + p50 <1.5s warm (4A)
- prompts stored at `packages/agents/prompts/conflict_explanation/v<N>.md` (2C3)
- canonical E2E fixture extended: deadline-overlap or assignee-collision conflict detected with ≥2 resolution options (3B)

### Validation
- simulate scope increase under fixed deadline
- simulate upstream blocked dependency
- simulate task without owner
- inspect conflict records and suggested options
- run Phase 2.5 eval suite against conflict explanation agent
- run canonical E2E fixture; Phase 8 assertions pass

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 9 — Human Decision Loop

### Objective
Allow humans to resolve critical tradeoffs and update workflow state.

### Scope
- conflict list endpoint
- decision submission endpoint
- decision persistence
- graph updates after decision

### Tasks
- implement `GET /api/projects/{project_id}/conflicts`
- implement `POST /api/conflicts/{conflict_id}/decision`
- support selecting option A/B/C
- support custom decision text
- apply decision to tasks / risks / conflicts / deliverables
- create decision audit record

### Acceptance Criteria
- a human decision updates the graph correctly
- approved decision is persisted
- affected state is re-synced to Feishu
- resolved conflict exits active state
- unit + integration tests exist and pass (decision application, audit record, re-sync trigger) (2C1)
- `decision.submitted` / `decision.applied` Inngest events with `trace_id` and `resolver` (2C2)
- "resolved" state derived from graph query (conflict has a decision edge), never written as a `current_stage` field (1E)
- canonical E2E fixture extended: decision recorded with resolver + rationale; graph state updated; Feishu re-sync triggered (3B)

### Validation
- choose "phase split" in canonical scenario
- verify deferred scope is updated
- verify affected tasks and conflict status change
- verify Docs / Base reflect new state
- run canonical E2E fixture; Phase 9 assertions pass

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 10 — Delivery Summary

### Objective
Generate final delivery output based on current approved project state.

### Scope
- Delivery Agent
- delivery summary generation
- completed vs deferred scope calculation
- evidence linking

### Tasks
- implement Delivery Agent
- generate delivery summary text
- list completed scope
- list deferred scope
- list key decisions
- list remaining risks
- include evidence references
- create/update delivery summary doc

### Acceptance Criteria
- delivery summary is readable and grounded in graph state
- deferred scope is explicit
- decisions are accurately reflected
- output is suitable for demo presentation
- unit + integration tests exist and pass (scope calculation, evidence linking, decision reflection) (2C1)
- Delivery-agent eval suite passes ≥80% via Phase 2.5 harness (3A)
- `agent_run_log` + `delivery.generated` Inngest event with `trace_id` (2C2)
- LLM failure recovery: retry-once → fallback parser → `manual_review` flag; fault-injection test (2C4)
- prompt caching enabled; cache-hit assertion + p50 <1.5s warm (4A)
- prompts stored at `packages/agents/prompts/delivery/v<N>.md` (2C3)
- QA pre-check step: before delivery summary is committed, a QA pass verifies all parsed scope items are accounted for (covered task OR explicitly deferred); fails loudly if coverage gap exists (brings QA agent behavior in from dev.md)
- canonical E2E fixture extended: delivery summary cites all 4 scope items + the approved decision (3B)

### Validation
- trigger delivery summary for canonical scenario
- verify completed/deferred scope is correct
- verify approved decision appears in output
- run Phase 2.5 eval suite against delivery agent
- run canonical E2E fixture; Phase 10 assertions pass

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 11 — Lightweight Web Console (Feishu-Mirror)

### Objective
Provide a minimal external surface for debugging and demo control AND a Feishu-mirror fallback that can replace Feishu if the live demo account fails. This console also serves as the foundation for post-competition platform-agnostic product (1H).

### Design Direction (from /plan-design-review 2026-04-17)

**Layout — Stage-driven canvas + graph sidebar + slide-out agent log** (design 1A)
The console is NOT a tabbed pane-switcher. It has one primary canvas that auto-follows the current workflow stage (messages during intake/clarify, tables during planning, conflict card during conflict, docs during delivery). A persistent right sidebar (280px) always shows the workflow graph. An agent-run-log drawer slides in from the bottom on demand. Feishu-mirror panes are not a separate mode — they are the canvas views, always rendered from local graph state.

```
+---------------------------------------+--------+
|                                       | GRAPH  |
|       CANVAS (auto-follows stage)     | sidebar|
|                                       | 280px  |
|  messages / tables / conflict / docs  |        |
|                                       |        |
+---------------------------------------+--------+
|     [agent log drawer — slides up from bottom] |
+------------------------------------------------+
```

**Graph sidebar — Compact vertical river** (design 7A)
Not a force-directed node-graph. Vertical flow top-to-bottom, stages as rows, entities as small terracotta-accent dots, fine charcoal lines for edges. Looks like a subway map, not a data-viz dashboard. Fits in 280px.

```
intake    ●
          │
parse     ●
        ┌─┴─┐
clarify ●   ●
        └─┬─┘
plan      ●
         ┌┼┐
tasks   ●●●
         │││
sync    ●●●
          │
conflict  ●
```

**Visual identity primitives** (design 4A)
- Type: **General Sans** (UI), **JetBrains Mono** (graph labels, agent log, structured output). NOT Inter, NOT system defaults.
- Surface: warm off-white `#FAFAF7` (not pure white). Text ink `#1A1A1A`.
- Accent: single — **terracotta `#C0471E`**. NOT purple/violet/indigo/gradient.
- Motif: the 4px filled dot — appears at graph nodes, as bullet, as status indicator, as pulse. Consistent across all panes.
- Weights: 400 + 600 only. Radius: 6px (rounded-md), never rounded-2xl.
- Two decorative rules: no colored-circle icons, no 3-column feature grids, no icon-in-badge patterns, no blue-to-purple anything.

**Initial empty state / landing** (design 2A)
First thing judges see. Canvas centers: small brand lockup "WorkGraph", one-line headline "Coordination as a graph, not a document.", one supporting sentence "Turn a single message into a coordinated team plan.", primary button `[ Run canonical demo ▶ ]` that auto-fires the event-registration scenario. Graph sidebar shows "Your workflow graph will appear here."

**Thinking state — named agent + streaming partial output** (design 2B)
Never a generic spinner. Canvas shows a badge (e.g., `[● Requirement Agent thinking...]`), streams partial structured output as tokens arrive (Anthropic streaming API), graph sidebar pulses the relevant node, agent-log drawer has a live tail with prompt + tokens. The 1-4s LLM wait becomes narrative, not dead time.

**Error / manual_review state — framed as checkpoint, not error** (design 2C)
When an agent raises `manual_review` (per 2C4), canvas shows a calm amber card (not red): headline "Requirement Agent paused", subhead "3 attempts, ambiguous output. Your call.", partial result visible, three actions: `[ Approve ]` `[ Retry ]` `[ Edit ]`. Graph sidebar marks that node amber (not red). Agent log auto-opens showing the 3 attempts. Turns a failure into a feature moment.

### Scope
- stage-driven primary canvas (auto-follows workflow)
- persistent graph sidebar (vertical river visualization)
- slide-out agent run log drawer
- **canvas views (auto-rendered based on stage):**
  - **messages view** — intake messages + clarification Q&A as a chat stream
  - **docs view** — requirement / planning / delivery summaries, Markdown-rendered in General Sans
  - **tables view** — Tasks / Risks / Conflicts / Decisions as dense readable tables
  - **conflict card view** — focused conflict with 2-3 options + resolve actions
- empty / thinking / manual_review states per above
- landing view (initial empty state with canonical-demo trigger)
- stage derived via graph query, never a denormalized field lookup (1E)
- the four patterns explicitly forbidden: blue-to-purple gradients, icon-in-colored-circle section decoration, 3-column symmetric feature grids, decorative blobs / wavy SVG dividers

### Tasks
- define design tokens (typography, color, spacing, motion) as CSS variables in a shared package; no hardcoded colors or font-families outside tokens
- build landing view (brand lockup + headline + canonical-demo trigger)
- build stage-driven canvas shell that swaps views based on current workflow stage (stage determined by graph query, per 1E)
- build messages view (chat stream, derived from intake + clarification events)
- build docs view (Markdown render of summaries)
- build tables view (sortable, dense, JetBrains-Mono for IDs/JSON cells)
- build conflict card view (amber checkpoint-card aesthetic for manual_review parity)
- build graph sidebar (compact vertical river; streaming node pulse during agent runs)
- build agent-run-log drawer (slides from bottom; live tail during LLM streaming)
- implement streaming agent-thinking UI using Anthropic streaming API
- implement manual_review checkpoint-card interaction (Approve / Retry / Edit)
- wire console to read local graph data; Feishu is a sync target, not a dependency of this UI
- visual regression: every view must pass the "AI slop sniff test" — no purple/indigo, no colored-circle icons, no 3-column symmetric grids, no blue-to-purple gradients, no centered-everything, no uniform bubbly radius

### Acceptance Criteria
- one can understand project state without digging into DB
- one can resolve a conflict through the UI
- views are demo-friendly and readable
- **console renders the full canonical scenario end-to-end without touching Feishu** (1H fallback gate)
- canvas auto-follows workflow stage (no manual tab-clicking required during demo)
- graph sidebar always visible; nodes pulse during agent runs
- LLM thinking state shows named agent + streaming partial output (no generic spinners)
- manual_review state renders as amber checkpoint-card with Approve/Retry/Edit (not red-error banner)
- landing view has brand lockup + one-line headline + canonical-demo trigger button
- design tokens defined as CSS variables; no hardcoded colors or font-families anywhere in the component tree
- General Sans + JetBrains Mono loaded via @font-face; no system-font fallback to Inter/Roboto/Arial in production
- unit + component tests exist and pass (rendering, sorting, filtering) (2C1)
- Playwright or equivalent E2E test for "landing → run canonical demo → resolve conflict → verify state" (3B)
- structured frontend error reporting wired to backend log (2C2)
- AI-slop sniff test passes: grep the final built CSS for `purple`, `violet`, `indigo`, `linear-gradient.*(purple|violet|indigo)`; must return zero matches. Visual review confirms no icon-in-colored-circle patterns, no 3-column symmetric feature grids.

### Validation
- load canonical project in UI
- resolve one conflict through UI
- verify backend state changes correctly
- **disable Feishu credentials entirely and run the full canonical scenario against the console only; demo flow must still be complete** (1H)
- run canonical E2E fixture; Phase 11 assertions pass

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 12 — Cross-Cutting Observability (Dashboards + Alerts)

### Objective
This phase shrinks per 2C2. Per-phase observability, retry, and LLM failure recovery are already baked into Phases 1-11. What remains: cross-cutting dashboards, alerts, and SLO instrumentation on top of the already-emitted logs and events. Inngest (adopted in 1A) provides event sourcing, retries, and an audit UI for free; this phase builds on top of it rather than reimplementing.

### Scope
- demo-day health dashboard
- per-agent latency + cache-hit dashboard
- Feishu sync rate-limit dashboard
- SLO alerts (workflow p95, agent p95, Feishu 429 rate)
- consolidated audit view across Inngest + `agent_run_log` + `sync_log`

### Tasks
- adopt Inngest as workflow engine (1A) — migrate any custom orchestration code from earlier phases into Inngest steps; Inngest state + audit UI replace a custom workflow log
- build demo-day health dashboard panel (workflow success rate, agent p95 latency, Feishu 429 rate, cache-hit ratio) — the one pane the narrator watches during demo
- build per-agent latency + cache-hit dashboard (uses `agent_run_log` data emitted by Phases 3, 4, 6, 8, 10)
- build Feishu sync rate-limit dashboard (uses `sync_log` data emitted by Phase 7)
- wire SLO alerts: workflow p95 >30s → warn; Feishu 429 rate >1% → warn; agent `manual_review` flag raised → notify operator
- consolidated audit view: link Inngest run ID ↔ `agent_run_log` rows ↔ `sync_log` rows via `trace_id`
- state integrity check: nightly job verifies no `project.current_stage` writes occurred (1E guardrail)

### Acceptance Criteria
- workflow failures are visible in Inngest dashboard (already true after 1A migration) AND surfaced in the demo-day health panel
- sync failures are not silent (already true after Phase 7) AND rate-limit dashboard surfaces throttle events
- invalid LLM output does not crash any flow (already true after 2C4 per-phase gates) AND `manual_review` flags show on demo-day panel
- critical decisions are auditable via consolidated audit view
- demo-day health panel loads in <2s and reflects live state
- unit + integration tests exist and pass for dashboard data aggregation (2C1)
- alerts are tested by injecting synthetic failures

### Validation
- simulate sync failure — appears on demo-day panel within 10s
- simulate malformed LLM JSON — Phase 3-10 recovery already handles; demo-day panel surfaces `manual_review` flag
- simulate duplicate intake — Phase 2 dedup handles; audit view shows the duplicate event was dropped
- rehearse demo with dashboards visible; confirm operator can spot issues without opening a terminal

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## Phase 13 — Demo Lock

### Objective
Make the demo deterministic and competition-ready.

### Scope
- fixed scenario fixtures
- seeded data
- fallback paths
- presentation timing

### Tasks
- seed canonical requirement
- seed clarification responses
- seed conflict-triggering dev feedback
- seed one approved decision
- prepare docs/base records for replay
- prepare fallback API path if Feishu live event fails
- rehearse demo click path
- freeze screenshots if necessary

### Acceptance Criteria
- demo can be replayed repeatedly
- every critical step has a fallback
- total flow fits the planned demo time (≤7 minutes)
- canonical narrative is stable
- `tests/e2e/canonical_event_registration.py` (evolved from Phase 2 through Phase 11) runs end-to-end in <90s with warm cache and is wired as the authoritative demo fixture (3B)
- **Feishu-mirror fallback (Phase 11) proven: full demo can run without live Feishu credentials** (1H)
- demo-day health dashboard (Phase 12) validated during dry-runs

### Validation
- run full demo from scratch
- run demo from seeded state
- simulate one live failure and confirm fallback works
- run full demo against Feishu-mirror console only (no live Feishu) — must succeed (1H)
- run canonical E2E fixture end-to-end; must pass

### Status
- [ ] not started
- [ ] in progress
- [ ] completed

---

## 5. Milestone View

## Milestone M1 — Intake to Parsed Requirement
Includes:
- Phase 1
- Phase 2
- Phase 2.5 (Eval Harness, new per 3A — hard prerequisite for all agent phases)
- Phase 3

Definition:
A message becomes a project with parsed workflow objects.

Completion standard:
- one raw requirement in
- one project snapshot out

---

## Milestone M2 — Parsed Requirement to Planned WorkGraph
Includes:
- Phase 4
- Phase 5
- Phase 6

Definition:
A clarified requirement becomes a planned workflow graph.

Completion standard:
- requirement is clarified
- tasks, risks, dependencies exist
- project is in planned state

---

## Milestone M3 — Planned WorkGraph to Visible Feishu State
Includes:
- Phase 7

Definition:
The internal graph is visible to users inside Feishu.

Completion standard:
- Base and Docs reflect project state

---

## Milestone M4 — Conflict to Decision
Includes:
- Phase 8
- Phase 9

Definition:
The system can detect a conflict and let a human resolve it.

Completion standard:
- conflict appears
- options appear
- decision updates graph

---

## Milestone M5 — Delivery and Demo
Includes:
- Phase 10
- Phase 11
- Phase 12
- Phase 13

Definition:
The entire canonical scenario is demoable from intake to delivery summary.

Completion standard:
- full demo runs cleanly
- fallback paths exist
- logs and state are inspectable

---

## 6. Suggested Execution Order for Codex / Opus

If using a coding agent, assign work in this order:

### Task Batch 1
- repository skeleton
- env setup
- database bootstrap
- health endpoints

### Task Batch 2
- intake event normalization
- project and requirement persistence
- parser service
- parser tests

### Task Batch 3
- clarification loop
- requirement versioning
- graph initialization

### Task Batch 4
- planning agent
- tasks / dependencies / risks persistence
- planning tests

### Task Batch 5
- Base sync
- Docs sync
- sync idempotency

### Task Batch 6
- conflict rules
- conflict explanation
- escalation logic

### Task Batch 7
- human decision API
- decision application
- state resync

### Task Batch 8
- delivery summary
- lightweight console
- demo fixtures
- demo fallback path

---

## 7. Validation Checklist by Milestone

## M1 Validation
- [ ] API intake works
- [ ] Feishu intake works or mock equivalent works
- [ ] project is created once
- [ ] parser output is valid JSON
- [ ] blocking ambiguities are surfaced

## M2 Validation
- [ ] clarification answers update requirement version
- [ ] graph entities are stored
- [ ] tasks and dependencies are created
- [ ] stage transitions are valid

## M3 Validation
- [ ] Base sync works
- [ ] Docs sync works
- [ ] re-sync is idempotent
- [ ] sync failure is logged

## M4 Validation
- [ ] conflict is detected
- [ ] options are generated
- [ ] one option can be approved
- [ ] graph updates correctly
- [ ] conflict status changes correctly

## M5 Validation
- [ ] delivery summary is generated
- [ ] demo flow is reproducible
- [ ] at least one fallback path is available
- [ ] canonical scenario can be shown in under 7 minutes

---

## 8. Stop Conditions

Stop and reassess if any of the following happens:

1. implementation starts drifting toward a generic chat product
2. tasks become vague or slogan-like
3. LLM outputs are being used without schema validation
4. approved decisions are silently overwritten
5. Base or Docs become the only source of truth
6. conflict detection depends entirely on free-form LLM reasoning
7. the canonical demo path becomes weaker, not stronger

If a stop condition is hit:
- halt feature expansion
- fix the architectural issue
- update `docs/dev.md` only if behavior truly changed

---

## 9. Definition of “Do Not Build Yet”

The following must be postponed unless the MVP is already complete:

- real repo automation
- actual coding agent execution pipelines
- full Feishu Tasks integration
- advanced UI graph visualization
- multi-project analytics
- knowledge memory across teams
- generalized workflow builder
- advanced permissions

These are future enhancements, not MVP requirements.

---

## 10. Canonical Demo Scenario

Use this exact scenario for development validation:

### Requirement
> We need to launch an event registration page next week. It needs invitation code validation, phone number validation, admin export, and conversion tracking.

### Clarification
- invitation codes are single-use
- export includes phone numbers
- admin management is not required in version one

### Conflict Trigger
Engineering feedback:
> We cannot complete both advanced invitation code logic and admin export support by next week without cutting scope or splitting phases.

### Expected Resolution Options
1. drop admin export
2. delay release
3. ship phase one now and defer phase two

### Human Decision
Select:
> phase one now, phase two later

### Expected Final State
- project continues
- deferred scope is recorded
- delivery summary reflects approved tradeoff

This scenario must remain the default test fixture.

---

## 11. Progress Tracking Format

When updating this plan, use this format:

### Completed
Short factual list of completed milestones or phases.

### In Progress
Current focus area.

### Next
Immediate next milestone or task batch.

### Risks
Any build risks, drift risks, or demo risks.

### Decisions
Any decisions that changed implementation path.

---

## 12. Current Build Order

This is the current recommended live order.

### Current
- Phase 1: Project Skeleton (includes ApiError model)
- Phase 2: Requirement Intake (creates canonical E2E fixture)
- Phase 2.5: Eval Harness (hard prerequisite for Phases 3, 4, 6, 8, 10)
- Phase 3: Requirement Parsing

### Next
- Phase 4: Clarification Loop
- Phase 5: WorkGraph Initialization (drops `current_stage` field; graph-native state)
- Phase 6: Planning Engine

### Then
- Phase 7: Feishu State Sync
- Phase 8: Conflict Detection
- Phase 9: Human Decision Loop

### Finalize
- Phase 10: Delivery Summary (includes QA pre-check)
- Phase 11: Lightweight Web Console (Feishu-Mirror fallback, per 1H)
- Phase 12: Cross-Cutting Observability (dashboards + alerts; per-phase logs already live)
- Phase 13: Demo Lock

---

## 13. Final Instruction

If there is any uncertainty about what to build next, default to this rule:

**Build the smallest possible change that makes the canonical delivery workflow more real, more testable, and more demoable.**

That is the standard for this plan.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| Eng Review | `/gstack-plan-eng-review` | Architecture & tests (required) | 1 | PASS_WITH_CHANGES | 16 decisions + 3 stated fixes; all 19 phase-level edits applied |
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | recommend if pursuing Feishu-pivot (1H) further |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | skipped per user (outside-voice A) |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | PASS_WITH_CHANGES | Phase 11 design 3/10 → 8/10; 6 decisions applied (IA, states, visual ID, graph viz) |

**VERDICT:** PLAN.md is design-complete and eng-complete for Phase 11. Ready for implementation. Eng test plan: `~/.gstack/projects/feishu/hanikasarfa94-nogit-eng-review-test-plan-20260417-102450.md`.

---

### Decisions Log (2026-04-17)

**Step 0 — Scope Challenge:** Approach B confirmed (13-phase Feishu-native competition build). Layer 1 Eureka findings: Inngest (workflow engine), Instructor+Pydantic (schema-safe LLM parsing), FastAPI BackgroundTasks (simpler than Celery for some paths), Feishu SDK dedup.

**Section 1 — Architecture (8 decisions):**
1. **1A** — Use Inngest as workflow engine (replaces custom orchestration in Phase 12).
2. **1B** — Keep LLM in Orchestrator (user override; rule-based router rejected).
3. **1C** — Keep all 7 agents separate (user override; consolidation rejected).
4. **1D** — Keep Celery + Redis as spec'd.
5. **1E** — Drop `Project.current_stage` denormalized field. Graph IS the state. LangGraph analogy: "we are graphflow, we have a graph to tell the status." Derived views OK for UI, never source of truth.
6. **1F** — Phase 4 (Clarification) stays P0.
7. **1G** — Orchestrator calls Agents (control flow direction confirmed).
8. **1H** — Stay Feishu for competition + expand Phase 11 console into a Feishu-mirror (messages + docs + Base panes) as demo fallback AND post-competition MergeBot v0 foundation. Full pivot deferred to /plan-ceo-review.

**Section 2 — Plan Quality (5 items):**
9. **2C1** — Add "tests exist and pass" to every phase's Acceptance Criteria.
10. **2C2** — Bake observability (agent_run_log, Inngest event visibility, error logging) into every phase. Phase 12 shrinks to cross-cutting dashboards + alerts.
11. **2C3** — Prompt versioning pattern: `packages/agents/prompts/<agent_name>/v<N>.md`. Stated as obvious fix, no decision needed.
12. **2C4** — Add "LLM failure recovery tested" (retry-once → fallback parser → manual_review flag + fault-injection test) to every agent phase (3, 4, 6, 8, 10).
13. **2C5** — `ApiError` Pydantic model added in Phase 1. Stated as obvious fix.

**Section 3 — Tests (2 decisions):**
14. **3A** — Insert new Phase 2.5 "Eval Harness" before any agent ships. Build eval dataset + runner + CI gate. promptfoo suggested as Layer 1 starting point.
15. **3B** — Create `tests/e2e/canonical_event_registration.py` in Phase 2, evolve per phase. Runs on every PR.

**Section 4 — Performance (3 decisions):**
16. **4A** — Prompt caching enabled per LLM agent phase. `cache_control` breakpoints, cache-hit integration test (>60%), latency assertion (p50 <1.5s warm) in E2E fixture.
17. **4B** — Phase 7 (Feishu State Sync) ships with token-bucket rate limiter + Feishu Base batch_create API + exponential backoff on 429. Load test with 80-row sync must pass.
18. **4C** — Keep strict sequential orchestration for competition. Parallel Clarification+Planning deferred to post-competition backlog.

### Memories Saved This Review

- `feedback_llm_orchestration_keep_agents.md` — don't re-argue LLM Orchestrator or agent consolidation; user has decided and budgeted time.
- `project_graph_native_state.md` — WorkGraph is graphflow; graph IS state; reject any `project.current_stage = X` writes in code review.
- `project_feishu_api_pain_raised.md` — Feishu API is heavy+dirty; user considered rebuilding. Any full-pivot requires /plan-ceo-review; Phase 11 Feishu-mirror is the middle-ground.

### Unresolved Concerns (flagged, not blocking competition build)

- Competitive landscape (design-doc RC#1) — no differentiation scenarios defined.
- Privacy / data residency (design-doc RC#2) — no tests, not a competition blocker but a commercial blocker.
- Per-phase velocity baseline (design-doc RC#4) — PLAN.md has no effort estimates; 6-8 week budget is aspirational.
- LLM Orchestrator predictability risk — user explicitly chose LLM flexibility over deterministic routing.

### Required PLAN.md Edits Before Implementation

Every phase (1, 2, 2.5, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13) has received Acceptance Criteria additions per 2C1, 2C2, 2C3, 2C4, 2C5, 3A, 3B, 4A, 4B, 1E, 1H as applicable. Phase 2.5 added as new. Phase 11 scope expanded per 1H (Feishu-mirror panes). Phase 12 scope reframed per 2C2 + 1A (Inngest). Project entity drops `current_stage` per 1E. See test plan artifact for full per-phase rationale.

**Status:** 2026-04-17 — all 19 phase-level edits applied directly to PLAN.md above. Ready for implementation.

### Design Review Decisions (2026-04-17, appended)

Scope: Phase 11 Feishu-Mirror Web Console only (per user time-box: IA + 2-3 key screens, defer polish).

- **D-1 (Pass 1A / Information Architecture):** Stage-driven canvas + persistent graph sidebar + slide-out agent-log drawer. No tabbed pane-switcher. Canvas auto-follows workflow stage.
- **D-2 (Pass 2A / Empty State):** Landing view has brand lockup + one-line headline ("Coordination as a graph, not a document.") + one supporting sentence + primary `Run canonical demo ▶` button.
- **D-3 (Pass 2B / Thinking State):** Named agent badge + streaming partial output via Anthropic streaming API + graph-sidebar node pulse + live agent-log tail. No generic spinners.
- **D-4 (Pass 2C / Manual Review State):** Amber checkpoint-card with Approve/Retry/Edit actions + full attempt history in auto-opened agent log. Framed as feature, not error. Never red.
- **D-5 (Pass 4A / Visual Identity):** General Sans + JetBrains Mono, warm off-white surface `#FAFAF7`, ink text `#1A1A1A`, single accent terracotta `#C0471E`, 4px filled-dot motif, 6px radius, weights 400 + 600 only. NOT Inter, NOT purple/violet/indigo.
- **D-6 (Pass 7A / Graph Sidebar Viz):** Compact vertical river (subway-map aesthetic, 280px), NOT force-directed react-flow. Stages as rows, entities as dots, fine charcoal edges.

### Design Scores

| Pass | Before | After |
|------|--------|-------|
| 1 — Information Architecture | 2/10 | 9/10 |
| 2 — Interaction States | 1/10 | 9/10 |
| 4 — AI Slop Risk | 2/10 | 9/10 |
| 7 — Unresolved Decisions | — | 0 open, 6 resolved |
| **Overall** | **3/10** | **8/10** |

### Design Decisions Deferred to Post-Competition

- Responsive / mobile / tablet viewports — demo is desktop-only.
- Accessibility: keyboard nav, ARIA landmarks, screen-reader support, full focus-ring system. Baseline focus-visible outlines still required now; full a11y pass post-competition.
- DESIGN.md creation via `/design-consultation` — recommended post-competition to formalize the tokens from D-5 into a proper design system.
- Pass 3 (User Journey / Emotional Arc) — partially covered via demo narrative built into D-1/D-3/D-4; formal storyboard deferred.
- Pass 5 (Design System Alignment) — no DESIGN.md exists yet; tokens from D-5 become the seed.
- Pass 6 (Responsive & Accessibility) — see above.