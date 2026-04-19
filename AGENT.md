> ⚠️ **ARCHIVED 2026-04-18 — SUPERSEDED BY [`docs/north-star.md`](docs/north-star.md).**
>
> This document reflects the MVP-era "delivery engine" framing (Phases 1–13). Specific
> guidance here — panel-based web surface, "Conflict Center", stage-driven flow,
> "do not build custom UI platform" — contradicts current product direction.
>
> For all current product / build guidance, read `docs/north-star.md` (operational)
> and `docs/vision.md` (depth). Treat this file as historical record of how the MVP
> was built. Do not read as current spec.

---

# AGENTS.md

Repository operating instructions for coding agents working on **WorkGraph AI**.

This file is the execution guide for agents such as Codex or Opus.  
It is not the full system spec. The full architecture and product logic live in `docs/dev.md`.

---

## 1. Read Order

Before making any code changes, read files in this order:

1. `docs/dev.md` — source of truth for system behavior and architecture
2. `PLAN.md` — current milestone and build sequence
3. `docs/engineering-backlog.md` — task breakdown and priorities
4. `docs/prompt-contracts.md` — agent I/O schema and JSON contracts
5. `docs/demo-script.md` — canonical demo flow and expected scenario

If these files conflict, follow this precedence:

1. `docs/dev.md`
2. `PLAN.md`
3. `docs/prompt-contracts.md`
4. `docs/engineering-backlog.md`
5. `docs/demo-script.md`

Do not invent product behavior that is not grounded in these files.

---

## 2. Project Mission

WorkGraph AI is an **AI-driven delivery engine** for the workflow:

**Requirement → Planning → Coding support → Testing support → Review → Delivery**

The product is **not** a generic chatbot.  
The product is **not** a generic project management clone.  
The product is **not** a fully autonomous agent swarm.

The system exists to do three things well:

1. convert raw collaboration input into structured workflow state
2. detect delivery conflicts early
3. escalate real tradeoff decisions to humans

Every implementation decision should reinforce that mission.

---

## 3. Core Product Rules

Always preserve these rules:

1. **State over messages**  
   Messages are inputs, not the source of truth.

2. **Graph over documents**  
   Docs are summaries and artifacts, not the primary workflow state.

3. **AI coordinates, humans decide**  
   AI may parse, plan, sync, and suggest.  
   Humans approve critical tradeoffs.

4. **Structured output over free-form text**  
   Core agent outputs must be JSON-schema-compatible.

5. **Minimal ontology**  
   Do not add unnecessary entities, abstractions, or meta-frameworks.

6. **Predictability over cleverness**  
   Prefer explicit logic, schemas, and validation over vague autonomous behavior.

---

## 4. Working Style

When implementing features:

1. Work on **one milestone or one bounded task at a time**
2. Keep changes small and reviewable
3. Prefer completing an end-to-end vertical slice over scattering partial code everywhere
4. Do not silently expand scope
5. If a requirement is ambiguous, implement the smallest version consistent with `docs/dev.md`
6. Leave clear TODOs only when blocked by missing requirements or credentials

Do not rewrite unrelated parts of the codebase unless necessary.

---

## 5. Non-Negotiable Constraints

Do not do any of the following unless explicitly required by `PLAN.md` or a direct user instruction:

- do not introduce a graph database for MVP
- do not introduce microservices unless clearly necessary
- do not add full RBAC systems
- do not build a large custom UI platform
- do not replace Feishu with a generic collaboration layer
- do not turn core workflow logic into LLM-only reasoning
- do not bypass approval boundaries for high-risk decisions
- do not convert structured state into prompt-only hidden state

The MVP uses:

- Feishu as the collaboration surface
- WorkGraph Engine as the core logic layer
- PostgreSQL as the primary state store
- rule logic + LLM for conflict handling

---

## 6. Repository Expectations

Expected structure:

```text
workgraph-ai/
  apps/
    api/
    worker/
    web/
  packages/
    domain/
    schemas/
    agents/
    orchestrator/
    feishu_adapter/
    observability/
  docs/
    dev.md
    engineering-backlog.md
    prompt-contracts.md
    demo-script.md
  AGENTS.md
  PLAN.md
If the repository differs from this structure, adapt carefully rather than forcing a rewrite.

7. Code Quality Rules
7.1 General
prefer explicit naming
prefer small functions
avoid deeply nested logic
avoid hidden mutable state
keep domain logic out of UI components
keep orchestration logic out of adapters
keep Feishu-specific logic out of core domain objects
7.2 Backend
validate all external input
use typed schemas for requests and agent outputs
isolate side effects
keep domain entities and state transitions testable without Feishu
7.3 Frontend
keep the web console lightweight
prioritize readability over visual polish
do not build a full design system for MVP
pages should map directly to workflow needs:
project overview
conflict center
project snapshot
7.4 Prompts
all core prompts must be versioned or traceable
all core prompts must target JSON output
never rely on prose parsing when a schema can be used
prompts must not fabricate owners, dates, or approved decisions
8. Domain Boundaries

Preserve the following separation:

packages/domain

Contains:

entities
enums
repositories
state transition rules

Must not contain:

Feishu SDK calls
direct LLM calls
web framework code
packages/agents

Contains:

prompt runners
structured agent wrappers
output validation
recovery logic

Must not contain:

UI rendering
domain persistence logic
packages/orchestrator

Contains:

workflow stage logic
agent invocation order
escalation routing
sync triggering

Must not contain:

low-level HTTP handlers
Feishu API implementation details
packages/feishu_adapter

Contains:

message client
docs client
Base client
task client if implemented

Must not contain:

core workflow rules
stage transition rules
9. Workflow for Any Task

When you start a task, follow this sequence:

read the relevant sections of docs/dev.md
identify the exact milestone from PLAN.md
identify affected modules
implement the minimum necessary change
add or update tests
run validation
update docs if behavior changed
report:
files changed
what was implemented
what remains open
any assumptions made

If a task changes system behavior, update the relevant docs.

10. Definition of Done

A task is not done unless all of the following are true:

code compiles or runs
core happy path works
failure path is handled reasonably
schema validation exists where needed
tests exist or were updated
behavior matches docs/dev.md
no unrelated breakage was introduced
docs are updated if the implementation changes expected behavior

For MVP milestones, “done” must mean usable in the canonical demo scenario.

11. Testing Standards
Required
unit tests for pure logic
validation tests for schema-driven functions
integration tests for workflow-critical paths
Focus areas
requirement parsing
state transitions
conflict detection
decision application
Feishu sync mapping
delivery summary generation
Minimum principle

Test the workflow, not just the functions.

The canonical scenario from docs/demo-script.md must always stay green.

12. Error Handling Rules
External input

Reject invalid or empty payloads clearly.

LLM output

If JSON is invalid:

retry once
attempt structured recovery
fail loudly with a recoverable error
Sync failures

Do not silently swallow Feishu sync errors.
Log them, mark sync state, and queue retry if supported.

State integrity failures

Reject impossible transitions.
Do not “auto-heal” domain state invisibly.

13. Logging and Observability

Every critical workflow step should be traceable.

Log at least:

intake event received
parsing started / succeeded / failed
graph initialized
planning generated
conflict detected
decision applied
Feishu sync attempted / succeeded / failed
delivery summary generated

Agent runs should be auditable:

agent name
input reference
output reference
latency
status

Do not log secrets.

14. Feishu Integration Rules

Feishu is the collaboration surface, not the business logic core.

Use Feishu for:

message intake
clarification prompts
escalation messages
summary docs
Base state display

Do not bury domain truth in Feishu-only objects.

The internal WorkGraph state must remain reconstructable without Feishu message history.

15. MVP Priorities

If priorities are unclear, build in this order:

intake
requirement parsing
graph initialization
planning
Base sync
conflict detection
human decision loop
delivery summary
lightweight web console

Do not optimize secondary features before this path works end-to-end.

16. Canonical Demo Requirement

The primary demo scenario is:

“We need to launch an event registration page next week. It needs invitation code validation, phone number validation, admin export, and conversion tracking.”

Your implementation should support this scenario reliably.

If a design choice makes this scenario weaker, simpler, or less legible, reconsider it.

17. Preferred Implementation Bias

When there are multiple possible approaches, prefer the one that is:

simpler
more explicit
easier to test
easier to demo
closer to the spec
less dependent on hidden agent behavior

For MVP, a clear rule engine is better than an impressive but opaque autonomous system.

18. Documentation Update Rules

Update docs when you change any of the following:

domain entities
state transitions
conflict types
API contracts
agent schemas
demo flow assumptions
milestone sequence

At minimum, update:

docs/dev.md if product behavior changed
docs/prompt-contracts.md if an agent schema changed
PLAN.md if milestone status changed
19. What to Report After Each Task

When finishing a task, report in this format:

Completed
short list of what was implemented
Files Changed
exact file paths
Validation
tests run
manual checks performed
Assumptions
any assumptions made due to ambiguity
Open Issues
anything still blocked or unclear

Keep reports short and factual.

20. Do Not Drift from the Product

If you find yourself building any of the following, stop and reassess:

a generic AI copilot shell
a generic chat platform
a full PM SaaS
an over-modeled knowledge graph
a multi-agent sandbox with no workflow backbone
an elaborate UI without working orchestration
a codegen-first system that ignores planning and conflict handling

WorkGraph AI is a delivery coordination engine.
That is the anchor.

21. Final Instruction

Always bias toward a working, testable, demoable vertical slice.

A smaller implementation that clearly proves:

shared workflow state
conflict detection
human approval at tradeoff points

is better than a larger but vague system.

If uncertain, choose the implementation that best supports the canonical demo and the MVP definition in docs/dev.md.