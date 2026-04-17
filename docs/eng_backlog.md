# Engineering Backlog — WorkGraph AI
Version: 1.0  
Status: MVP delivery backlog  
Owner: Product / Engineering  
Primary audience: engineering team, coding agents, technical PM

---

## 1. Purpose

This file is the implementation backlog for **WorkGraph AI**.

It translates the product and architecture spec in `docs/dev.md` into buildable engineering work.

This backlog is organized by:
- epics
- milestones
- task priorities
- dependencies
- acceptance criteria

This file is execution-facing.
If it conflicts with `docs/dev.md`, follow `docs/dev.md`.

---

## 2. Priority System

### P0
Required for MVP and canonical demo.

### P1
Strongly preferred for MVP quality and demo clarity.

### P2
Useful but optional. Build only after P0 and P1 are stable.

---

## 3. Status System

Use one of:
- `todo`
- `in_progress`
- `blocked`
- `done`

---

## 4. MVP Target

The backlog should deliver one working end-to-end path:

1. requirement comes in from Feishu
2. requirement is parsed into structured workflow state
3. clarification happens if needed
4. planning generates tasks, risks, and dependencies
5. state is synced into Feishu Base and Docs
6. conflict is detected
7. human makes a decision
8. delivery summary is generated

That is the canonical MVP.

---

# 5. Epic A — Project Foundation

## A-1 Repository skeleton
Priority: P0  
Status: todo

### Description
Create the initial repository structure and app boundaries.

### Tasks
- create `apps/api`
- create `apps/worker`
- create `apps/web`
- create `packages/domain`
- create `packages/schemas`
- create `packages/agents`
- create `packages/orchestrator`
- create `packages/feishu_adapter`
- create `packages/observability`
- create `docs/`

### Acceptance Criteria
- all package folders exist
- repository structure matches `docs/dev.md`
- shared packages can be imported by apps

### Dependencies
- none

---

## A-2 Environment bootstrap
Priority: P0  
Status: todo

### Description
Set up environment variables and application boot configuration.

### Tasks
- create `.env.example`
- add DB connection config
- add Redis config
- add LLM provider config
- add Feishu credentials config
- fail fast on missing required env vars

### Acceptance Criteria
- each app starts with valid env file
- missing env vars produce explicit startup error

### Dependencies
- A-1

---

## A-3 Developer tooling
Priority: P1  
Status: todo

### Description
Set up linting, formatting, test runner, and pre-commit basics.

### Tasks
- configure formatter
- configure linter
- configure unit test runner
- add basic CI or local validation script
- add `make` or script shortcuts if desired

### Acceptance Criteria
- one command runs tests
- one command formats code
- one command starts local development

### Dependencies
- A-1

---

# 6. Epic B — Domain Model and Persistence

## B-1 Domain entities
Priority: P0  
Status: todo

### Description
Implement core domain entities and enums.

### Tasks
- define `Project`
- define `Requirement`
- define `Goal`
- define `Deliverable`
- define `Task`
- define `Dependency`
- define `Constraint`
- define `Risk`
- define `Conflict`
- define `Decision`
- define `Evidence`
- define all state enums

### Acceptance Criteria
- entities align with `docs/dev.md`
- state enums exist for requirement, task, risk, conflict, project stage

### Dependencies
- A-1

---

## B-2 Database schema
Priority: P0  
Status: todo

### Description
Create the relational schema required for MVP.

### Tasks
- create migrations
- create `projects` table
- create `requirements` table
- create `goals` table
- create `deliverables` table
- create `tasks` table
- create `task_dependencies` table
- create `constraints` table
- create `risks` table
- create `conflicts` table
- create `decisions` table
- create `evidences` table
- create `events` table
- create `agent_runs` table
- create `feishu_bindings` table

### Acceptance Criteria
- migrations run cleanly
- schema supports one full canonical project lifecycle
- core indices exist for `project_id`, `status`, `created_at`

### Dependencies
- B-1
- A-2

---

## B-3 Repository layer
Priority: P0  
Status: todo

### Description
Create repository interfaces and implementations for core entities.

### Tasks
- implement project repository
- implement requirement repository
- implement task repository
- implement conflict repository
- implement decision repository
- implement event repository
- implement binding repository

### Acceptance Criteria
- CRUD operations exist for core entities
- repositories are testable without external services

### Dependencies
- B-2

---

# 7. Epic C — Ingestion

## C-1 Intake API
Priority: P0  
Status: todo

### Description
Add an API endpoint that creates a project from a raw message.

### Tasks
- implement `POST /api/intake/message`
- validate request schema
- create raw event record
- create project
- create requirement
- return project ID and stage

### Acceptance Criteria
- valid request creates one project
- invalid request fails with explicit error
- duplicate request can be safely handled by dedup logic

### Dependencies
- B-2
- B-3

---

## C-2 Feishu event ingestion
Priority: P0  
Status: todo

### Description
Support requirement intake directly from Feishu.

### Tasks
- implement Feishu event receiver
- verify request signature or token as needed
- normalize message payload
- deduplicate repeated delivery
- convert to same internal flow as Intake API

### Acceptance Criteria
- Feishu message creates the same domain result as API intake
- duplicate event does not create duplicate project
- raw Feishu payload is stored in event log

### Dependencies
- C-1
- A-2

---

## C-3 Event normalization
Priority: P1  
Status: todo

### Description
Create a normalized event contract for all external intake sources.

### Tasks
- define normalized intake event schema
- implement mappers for API input and Feishu input
- include trace ID / event ID generation

### Acceptance Criteria
- downstream parser uses normalized event rather than source-specific raw payload
- every event is replayable

### Dependencies
- C-1
- C-2

---

# 8. Epic D — Requirement Parsing

## D-1 Requirement Agent wrapper
Priority: P0  
Status: todo

### Description
Implement the agent runner for requirement parsing.

### Tasks
- create prompt wrapper
- define structured output schema
- validate JSON output
- add retry on malformed JSON
- add fallback failure contract

### Acceptance Criteria
- agent always returns valid typed result or recoverable failure
- malformed JSON is retried once before failing

### Dependencies
- A-2
- B-1

---

## D-2 Requirement parsing service
Priority: P0  
Status: todo

### Description
Parse raw requirement text into structured objects.

### Tasks
- extract summary
- extract goals
- extract deliverables
- extract constraints
- extract risks
- extract open questions
- attach confidence score
- persist parsing result

### Acceptance Criteria
- canonical demo requirement parses correctly
- missing information appears as `unknown` or `open_questions`
- no fabricated owners or approved scope

### Dependencies
- D-1
- B-3
- C-1

---

## D-3 Parser test fixtures
Priority: P1  
Status: todo

### Description
Build a repeatable parser test suite.

### Tasks
- add canonical scenario fixture
- add vague requirement fixture
- add noisy requirement fixture
- add malformed output recovery test

### Acceptance Criteria
- parser regression tests can be run repeatedly
- canonical fixture stays green

### Dependencies
- D-2

---

# 9. Epic E — Clarification Loop

## E-1 Clarification Agent wrapper
Priority: P0  
Status: todo

### Description
Implement the agent that generates the smallest useful set of clarification questions.

### Tasks
- define output schema
- enforce max 3 questions
- include blocking level and target role
- validate structured output

### Acceptance Criteria
- agent never produces more than 3 questions
- questions are operational, not cosmetic

### Dependencies
- D-1

---

## E-2 Clarification question generation
Priority: P0  
Status: todo

### Description
Generate targeted clarification questions after parsing.

### Tasks
- analyze open questions
- rank by blocking severity
- skip clarification if planning can proceed
- store generated questions

### Acceptance Criteria
- under-specified requirements produce useful clarification prompts
- sufficiently specified requirements skip clarification

### Dependencies
- E-1
- D-2

---

## E-3 Clarification reply endpoint
Priority: P0  
Status: todo

### Description
Support user answers to clarification questions.

### Tasks
- implement `POST /api/projects/{project_id}/clarify-reply`
- validate reply schema
- create new requirement version
- merge answer into requirement state
- update project stage

### Acceptance Criteria
- clarification answers create a new requirement version
- clarified project can advance to `confirmed`

### Dependencies
- E-2
- B-3

---

# 10. Epic F — WorkGraph Initialization

## F-1 Graph builder
Priority: P0  
Status: todo

### Description
Construct initial graph state from parsed and clarified requirement.

### Tasks
- create goals from parser output
- create deliverables
- create constraints
- create risks
- link requirement to graph objects
- persist stage transition

### Acceptance Criteria
- graph can be reconstructed from DB
- project has a coherent snapshot after parsing + clarification

### Dependencies
- D-2
- E-3

---

## F-2 Graph snapshot service
Priority: P1  
Status: todo

### Description
Expose a stable project snapshot for UI, sync, and orchestration.

### Tasks
- build aggregation query/service
- include project
- include requirement summary
- include goals
- include tasks
- include risks
- include conflicts
- include recent decisions

### Acceptance Criteria
- one service returns a coherent project snapshot
- snapshot can power both API responses and UI pages

### Dependencies
- F-1
- B-3

---

# 11. Epic G — Planning Engine

## G-1 Planning Agent wrapper
Priority: P0  
Status: todo

### Description
Implement the planning agent runner.

### Tasks
- define planning schema
- validate task output
- validate dependency output
- add retry / failure behavior

### Acceptance Criteria
- planning output is always schema-valid or recoverably failed

### Dependencies
- D-1

---

## G-2 Planning generation
Priority: P0  
Status: todo

### Description
Generate deliverables, tasks, dependencies, milestones, and risks.

### Tasks
- create deliverables from clarified requirement
- create tasks
- create dependencies
- create planning risks
- create milestones if modeled
- persist all planning objects
- advance project stage to `planned`

### Acceptance Criteria
- canonical scenario produces a workable task list
- tasks are concrete and executable
- dependencies are explicit
- tasks have acceptance criteria

### Dependencies
- G-1
- F-1

---

## G-3 Planning integrity checks
Priority: P1  
Status: todo

### Description
Run lightweight validity checks on the generated plan.

### Tasks
- detect missing owners or owner roles
- detect empty acceptance criteria
- detect orphan tasks
- detect circular dependencies

### Acceptance Criteria
- obviously broken plans are flagged before sync

### Dependencies
- G-2

---

# 12. Epic H — Orchestration

## H-1 Stage transition engine
Priority: P0  
Status: todo

### Description
Implement the project workflow stage transition logic.

### Tasks
- define allowed transitions
- enforce transition validation
- update project `current_stage`
- reject impossible transitions

### Acceptance Criteria
- stage transitions follow `docs/dev.md`
- invalid transitions fail loudly

### Dependencies
- B-1
- F-1
- G-2

---

## H-2 Orchestrator service
Priority: P0  
Status: todo

### Description
Create the orchestration layer that invokes the right action at the right stage.

### Tasks
- determine current project state
- decide when to parse
- decide when to clarify
- decide when to plan
- decide when to detect conflicts
- decide when to sync
- decide when to escalate

### Acceptance Criteria
- workflow can advance end-to-end using the orchestrator
- orchestration logic is separate from adapters and routes

### Dependencies
- H-1
- D-2
- E-2
- G-2

---

# 13. Epic I — Feishu Sync

## I-1 Base adapter
Priority: P0  
Status: todo

### Description
Build the Feishu Base adapter layer.

### Tasks
- create Base client wrapper
- create record upsert helpers
- store Base record bindings
- support task table sync
- support risk table sync
- support conflict table sync

### Acceptance Criteria
- Base records are upserted, not duplicated
- state is readable in Base tables

### Dependencies
- A-2
- B-3

---

## I-2 Base sync service
Priority: P0  
Status: todo

### Description
Sync current project state into Base.

### Tasks
- map tasks to table fields
- map risks to table fields
- map conflicts to table fields
- sync by project snapshot
- persist sync status
- add retry support or retry-ready failure handling

### Acceptance Criteria
- Base reflects latest project state
- repeated sync is idempotent
- sync errors are visible

### Dependencies
- I-1
- F-2
- G-2

---

## I-3 Docs adapter
Priority: P0  
Status: todo

### Description
Build the Feishu Docs adapter layer.

### Tasks
- create Docs client wrapper
- create doc create/update helpers
- store doc bindings
- support block update patterns

### Acceptance Criteria
- docs can be created and updated from backend code

### Dependencies
- A-2
- B-3

---

## I-4 Docs sync service
Priority: P0  
Status: todo

### Description
Generate and update project summary docs.

### Tasks
- create requirement summary doc
- create planning summary doc
- create delivery summary doc
- update docs after approved decision

### Acceptance Criteria
- each project has readable docs
- docs align with approved graph state

### Dependencies
- I-3
- F-2
- G-2

---

## I-5 Feishu message notification service
Priority: P1  
Status: todo

### Description
Send messages back into Feishu for clarification, escalation, and completion.

### Tasks
- send clarification prompt
- send conflict escalation message
- send delivery completion message

### Acceptance Criteria
- critical events are visible to users inside Feishu

### Dependencies
- C-2
- E-2
- K-3

---

# 14. Epic J — Conflict Detection

## J-1 Rule engine
Priority: P0  
Status: todo

### Description
Implement deterministic conflict detection for the MVP.

### Tasks
- detect deadline-vs-scope conflict
- detect dependency-blocking conflict
- detect missing-owner conflict
- detect blocked-downstream conflict
- emit conflict records

### Acceptance Criteria
- at least 3 conflict types are detected without relying fully on the LLM
- conflict rules are testable

### Dependencies
- G-2
- H-1

---

## J-2 Conflict Explanation Agent wrapper
Priority: P0  
Status: todo

### Description
Implement the agent that explains conflicts and proposes options.

### Tasks
- define explanation schema
- generate summary
- generate impact scope
- generate 2–3 options
- generate recommended option
- determine whether human decision is required

### Acceptance Criteria
- each major conflict has a concise explanation and options
- options are genuinely distinct tradeoffs

### Dependencies
- D-1

---

## J-3 Conflict service
Priority: P0  
Status: todo

### Description
Combine rule findings and agent explanation into stored conflict state.

### Tasks
- run rules on project snapshot changes
- enrich rule result with explanation agent
- persist conflict objects
- trigger escalation if needed

### Acceptance Criteria
- conflict appears as first-class object in the graph
- conflict severity and options are visible
- project snapshot includes active conflicts

### Dependencies
- J-1
- J-2
- F-2

---

# 15. Epic K — Human Decision Loop

## K-1 Conflict query endpoint
Priority: P0  
Status: todo

### Description
Allow UI and external callers to fetch conflict state.

### Tasks
- implement `GET /api/projects/{project_id}/conflicts`
- include summary
- include severity
- include options
- include status

### Acceptance Criteria
- active conflicts can be fetched cleanly for one project

### Dependencies
- J-3

---

## K-2 Decision submission endpoint
Priority: P0  
Status: todo

### Description
Allow an approver to select a suggested option or provide custom resolution text.

### Tasks
- implement `POST /api/conflicts/{conflict_id}/decision`
- validate payload
- support option selection
- support custom text
- record approver identity

### Acceptance Criteria
- endpoint accepts one decision and persists it
- invalid decisions are rejected clearly

### Dependencies
- K-1

---

## K-3 Decision application service
Priority: P0  
Status: todo

### Description
Apply a human decision to the project graph.

### Tasks
- create Decision record
- update task state or scope
- update conflict status
- update risks if affected
- update project stage if needed
- trigger resync to Feishu

### Acceptance Criteria
- approved decision changes graph state consistently
- downstream state reflects the chosen option
- decision is auditable

### Dependencies
- K-2
- F-2
- I-2
- I-4

---

# 16. Epic L — Delivery Summary

## L-1 QA Agent wrapper
Priority: P1  
Status: todo

### Description
Implement agent contract for delivery verification support.

### Tasks
- define test point schema
- define acceptance criteria schema
- define blocking issues schema

### Acceptance Criteria
- QA output is structured and usable in delivery generation

### Dependencies
- D-1

---

## L-2 Delivery Agent wrapper
Priority: P0  
Status: todo

### Description
Implement structured delivery summary generation.

### Tasks
- define delivery summary schema
- generate completed scope
- generate deferred scope
- include key decisions
- include remaining risks
- include evidence references

### Acceptance Criteria
- output is valid JSON
- summary is grounded in graph state
- no scope is invented

### Dependencies
- D-1

---

## L-3 Delivery summary service
Priority: P0  
Status: todo

### Description
Produce final delivery artifact for the project.

### Tasks
- gather completed tasks
- gather deferred tasks
- gather approved decisions
- gather evidence
- call Delivery Agent
- write delivery summary to Docs
- advance stage to `delivered`

### Acceptance Criteria
- delivery doc exists
- completed and deferred scope are explicit
- final output is suitable for demo

### Dependencies
- L-2
- K-3
- I-4

---

# 17. Epic M — Web Console

## M-1 Project overview page
Priority: P1  
Status: todo

### Description
Show project stage and high-level delivery state.

### Tasks
- build project overview route
- show summary
- show current stage
- show goals
- show recent conflicts
- show recent decisions

### Acceptance Criteria
- one page provides a useful summary of project state

### Dependencies
- F-2
- K-1

---

## M-2 Conflict center page
Priority: P1  
Status: todo

### Description
Allow approvers to inspect and resolve conflicts.

### Tasks
- build conflict list
- build conflict detail panel
- add resolution action buttons
- wire to decision endpoint

### Acceptance Criteria
- one conflict can be resolved through the UI

### Dependencies
- K-2
- K-3

---

## M-3 Project snapshot page
Priority: P1  
Status: todo

### Description
Display the workflow graph in a readable list/table form.

### Tasks
- show tasks
- show risks
- show conflicts
- show deliverables
- show dependencies in readable format

### Acceptance Criteria
- project state is inspectable without opening DB or logs

### Dependencies
- F-2

---

## M-4 Agent run log page
Priority: P2  
Status: todo

### Description
Display agent run history for debug and demo support.

### Tasks
- list agent runs
- show agent name
- show status
- show latency
- show output summary

### Acceptance Criteria
- enough to inspect whether parser/planner/conflict agent ran successfully

### Dependencies
- O-2

---

# 18. Epic N — Observability and Reliability

## N-1 Event logging
Priority: P0  
Status: todo

### Description
Persist incoming and internal events for replay and audit.

### Tasks
- log external intake events
- log internal domain events
- add trace ID
- store timestamps and source

### Acceptance Criteria
- each project lifecycle can be reconstructed from events

### Dependencies
- C-1
- C-2

---

## N-2 Agent run logging
Priority: P0  
Status: todo

### Description
Persist all agent runs with input/output references and status.

### Tasks
- create `agent_runs` persistence
- store agent name
- store input refs or input snapshots
- store output refs or output snapshots
- store latency and status

### Acceptance Criteria
- parser / planner / conflict explainer / delivery agent runs are auditable

### Dependencies
- B-2
- D-1

---

## N-3 Sync failure handling
Priority: P1  
Status: todo

### Description
Make Feishu sync failures visible and recoverable.

### Tasks
- mark sync failure state
- log sync errors
- support retry queue or retryable status
- expose sync issue in logs or UI

### Acceptance Criteria
- sync failure is never silent
- failed sync can be retried

### Dependencies
- I-2
- I-4

---

## N-4 LLM output recovery
Priority: P1  
Status: todo

### Description
Handle malformed LLM outputs robustly.

### Tasks
- add retry once behavior
- add JSON recovery pass
- add failure contract return
- prevent malformed output from corrupting state

### Acceptance Criteria
- malformed JSON does not crash the workflow
- recoverable failure is surfaced

### Dependencies
- D-1
- G-1
- J-2
- L-2

---

## N-5 State integrity checks
Priority: P1  
Status: todo

### Description
Reject impossible workflow mutations.

### Tasks
- validate stage transitions
- validate decision application
- validate dependency graph structure
- validate final delivery generation inputs

### Acceptance Criteria
- impossible state change is rejected explicitly

### Dependencies
- H-1
- K-3

---

# 19. Epic O — Demo Readiness

## O-1 Canonical demo fixture
Priority: P0  
Status: todo

### Description
Create stable seeded data for the demo scenario.

### Tasks
- seed canonical requirement
- seed clarification answers
- seed one engineering feedback event
- seed one critical conflict
- seed one approved decision outcome

### Acceptance Criteria
- demo can be replayed from stable fixture data

### Dependencies
- L-3

---

## O-2 Demo logging and visibility
Priority: P1  
Status: todo

### Description
Make it easy to explain what the system did during the demo.

### Tasks
- show current stage clearly
- show recent agent activity
- show conflict and decision history
- show doc/Base sync outputs

### Acceptance Criteria
- presenter can explain the system without relying on hidden logs

### Dependencies
- N-2
- M-1
- M-2

---

## O-3 Demo fallback paths
Priority: P1  
Status: todo

### Description
Prepare fallback routes for unstable live integrations.

### Tasks
- add fallback local intake
- add fallback pre-seeded snapshot
- add fallback pre-generated docs
- add fallback manual conflict injection

### Acceptance Criteria
- one live integration failure does not break the demo

### Dependencies
- O-1

---

# 20. Cross-Cutting Tickets

## X-1 Schema package
Priority: P0  
Status: todo

### Description
Centralize request, response, agent, and event schemas.

### Tasks
- API request schemas
- API response schemas
- agent I/O schemas
- event schemas
- DB serialization helpers if needed

### Acceptance Criteria
- all external and agent boundaries are schema-validated

### Dependencies
- A-1

---

## X-2 Test utilities
Priority: P1  
Status: todo

### Description
Add fixtures and helper functions for integration tests.

### Tasks
- canonical requirement fixture
- clarified requirement fixture
- project seed helper
- conflict seed helper
- fake Feishu clients or mocks

### Acceptance Criteria
- integration tests can be written without duplicating boilerplate

### Dependencies
- A-3
- X-1

---

## X-3 Configurable workflow settings
Priority: P2  
Status: todo

### Description
Make basic workflow constants configurable.

### Tasks
- max clarification rounds
- max clarification questions
- conflict severity thresholds
- auto-escalation thresholds

### Acceptance Criteria
- core thresholds can be adjusted without rewriting logic

### Dependencies
- H-2
- J-3

---

# 21. Testing Backlog

## T-1 Unit tests for parser output validation
Priority: P0  
Status: todo

## T-2 Unit tests for state transitions
Priority: P0  
Status: todo

## T-3 Unit tests for conflict rules
Priority: P0  
Status: todo

## T-4 Integration test for intake → parse → graph init
Priority: P0  
Status: todo

## T-5 Integration test for clarify → plan
Priority: P0  
Status: todo

## T-6 Integration test for plan → Base sync
Priority: P1  
Status: todo

## T-7 Integration test for conflict → decision → graph update
Priority: P0  
Status: todo

## T-8 Integration test for delivery summary generation
Priority: P0  
Status: todo

## T-9 Demo regression test for canonical scenario
Priority: P1  
Status: todo

---

# 22. Suggested Build Order

Build in this order unless blocked:

1. A-1, A-2, B-1, B-2
2. C-1, C-2, D-1, D-2
3. E-1, E-2, E-3
4. F-1, F-2, H-1
5. G-1, G-2, G-3
6. I-1, I-2, I-3, I-4
7. J-1, J-2, J-3
8. K-1, K-2, K-3
9. L-2, L-3
10. M-1, M-2, M-3
11. N-1, N-2, N-3, N-4, N-5
12. O-1, O-2, O-3

This order matches the MVP vertical slice.

---

# 23. Blocking Risks

## R-1 Scope Drift
Risk:
Building a generic AI platform instead of a delivery engine.

Mitigation:
Always validate against canonical MVP flow.

## R-2 LLM Output Instability
Risk:
Schema break or inconsistent planning output.

Mitigation:
Strict schema validation, retry once, recoverable failure contract.

## R-3 Feishu Integration Instability
Risk:
Sync or event subscription issues break demo.

Mitigation:
Fallback intake path, seeded fixtures, pre-generated docs.

## R-4 Over-Modeling
Risk:
Too many entities or relationships slow development.

Mitigation:
Stick to minimal ontology from `docs/dev.md`.

---

# 24. Definition of Backlog Completion

This backlog is complete for MVP when all P0 items required by the canonical demo are marked `done`, and the following are true:

1. one canonical requirement can pass end-to-end through the system
2. at least one critical conflict can be detected and resolved
3. Base and Docs show state clearly
4. delivery summary is generated from graph state
5. demo fallback paths exist

That is the finish line for the first usable version.

---

# 25. Reporting Format

When updating backlog progress, use:

## Completed
- ticket IDs and short descriptions

## In Progress
- ticket IDs and current focus

## Blocked
- ticket IDs and reason

## Next
- exact next tickets

## Risks
- any execution or demo risks

Keep updates short and factual.