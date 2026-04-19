> ⚠️ **ARCHIVED 2026-04-18 — SUPERSEDED BY [`docs/north-star.md`](north-star.md).**
>
> This spec reflects the MVP-era "delivery engine" framing. Specific instructions
> here — "Conflict Center" (§19.6 area / line 804), stage-driven workflow,
> pane-based web surface, role-based routing — are NOT current product direction.
> The agent contracts (ClarificationAgent, ConflictExplanationAgent, etc.) and
> backend schemas remain correct for reference.
>
> For all current product / build guidance, read `docs/north-star.md` (operational)
> and `docs/vision.md` (depth). Treat this file as historical record.

---

# WorkGraph AI — Development Specification
Version: 1.0  
Status: Build-ready MVP spec  
Owner: Product / Engineering  
Primary audience: Opus, Codex, engineers, technical collaborators

---

## 1. Document Purpose

This document is the master technical and product specification for **WorkGraph AI**.

It defines:

- the product problem
- the MVP scope
- the system architecture
- the domain model
- the workflow state machine
- the agent contracts
- the Feishu integration boundary
- the implementation priorities
- the acceptance criteria for the first shippable version

This file is the **source of truth** for system behavior.

It is not intended to be the only execution document. In the repository, it should be used together with:

- `AGENTS.md` for repo instructions
- `PLAN.md` for milestone sequencing
- `docs/engineering-backlog.md` for task breakdown
- `docs/prompt-contracts.md` for LLM I/O schemas
- `docs/demo-script.md` for demo execution

---

## 2. Product Definition

### 2.1 One-line Definition

**WorkGraph AI** is an AI-driven delivery engine that coordinates the full workflow from **requirement intake to delivery**, using shared workflow state, agent orchestration, conflict detection, and human approval at critical decision points.

### 2.2 Core Thesis

Modern teams already use AI, but they still collaborate inefficiently because AI remains a **private tool** for each role.

Current failure pattern:

1. PM uses AI privately
2. Engineer uses AI privately
3. Designer uses AI privately
4. QA uses AI privately
5. the team still needs meetings and manual alignment to merge all partial understandings

This means AI amplifies individual cognition but does not yet solve **organizational coordination**.

WorkGraph AI is built to change that.

### 2.3 Product Principle

The system is based on one core shift:

- **chat is no longer the source of truth**
- **documents are no longer the primary workflow backbone**
- **shared workflow state becomes the coordination center**

In this model:

- chat is an intent input layer
- docs are output and audit artifacts
- the WorkGraph is the operational truth
- AI coordinates flow
- humans approve judgment-heavy tradeoffs

---

## 3. Product Goal

### 3.1 Primary Goal

Build a working MVP that demonstrates AI-driven orchestration across:

- Requirement
- Planning
- Coding support
- Testing support
- Review
- Delivery summary

### 3.2 What the MVP Must Prove

The MVP must prove that:

1. AI can convert raw collaboration input into shared workflow state
2. AI can generate delivery structure, not just summaries
3. AI can identify conflicts before meetings are required
4. AI can propose resolution options
5. humans only need to intervene at key judgment points

### 3.3 Product Slogan

**Pipeline is the skeleton. Agents are the muscles. Humans are the brain.**

---

## 4. Scope

## 4.1 In Scope for MVP

The MVP includes:

1. Requirement intake from Feishu message
2. Requirement parsing into structured workflow objects
3. WorkGraph creation
4. Task generation
5. Dependency and risk generation
6. Base sync for tasks / risks / conflicts
7. Conflict detection
8. Human decision loop for critical conflicts
9. Delivery summary generation
10. Lightweight web console for project status and conflict resolution

## 4.2 Out of Scope for MVP

The MVP does not include:

1. full code repository automation
2. real CI/CD orchestration
3. actual test runner execution
4. enterprise-grade access control
5. multi-team workspace
6. generalized workflow-builder UI
7. replacement of Jira / Feishu Projects / TAPD
8. full autonomous delivery with no human oversight

---

## 5. Primary Scenario

The MVP targets one high-value scenario:

### Product Delivery Scenario

A team receives a requirement such as:

> “We need to launch an event registration page next week. It needs invitation code support, phone validation, admin export, and conversion tracking.”

The system should:

1. parse the requirement
2. identify missing key information
3. ask a small number of critical clarification questions
4. generate deliverables, tasks, risks, and dependencies
5. sync current state into Feishu Base and Docs
6. detect conflicts if execution feedback changes the plan
7. propose resolution options
8. request human decision when tradeoffs are involved
9. update the full workflow state after the decision
10. generate a delivery summary

---

## 6. Users and Roles

## 6.1 Human Roles

### Explorer
The person who introduces the requirement or problem.  
Usually business, PM, operations, or stakeholder.

### Specialist
A domain contributor.  
Usually engineer, designer, QA, ops, or analyst.

### Approver
The person who makes critical tradeoff decisions.  
Usually PM, tech lead, team lead, or responsible owner.

### Governor
The person or configuration layer that defines workflow rules, automation boundaries, and escalation logic.

In the MVP, the Governor role may be represented by configuration rather than a dedicated UI role.

## 6.2 AI Roles

### Orchestrator Agent
The central workflow coordinator.

Responsibilities:
- determine workflow stage
- decide which agent to invoke next
- maintain graph state
- trigger sync and escalation
- enforce stage transitions

### Requirement Agent
Parses raw requirement input and extracts structured delivery objects.

### Clarification Agent
Generates at most a small number of blocking clarification questions.

### Planning Agent
Generates deliverables, tasks, dependencies, and milestones.

### QA Agent
Generates test points, acceptance criteria, and validation blockers.

### Conflict Explanation Agent
Explains conflicts and proposes resolution options.

### Delivery Agent
Generates final delivery summary and deferred scope summary.

---

## 7. Product Principles

### 7.1 State Over Messages
Messages are inputs, not the truth layer.

### 7.2 Graph Over Documents
Documents summarize approved state; they do not replace structured workflow state.

### 7.3 AI Coordinates, Humans Decide
AI handles routing, synthesis, and conflict preparation. Humans handle judgment and responsibility.

### 7.4 Minimal Ontology
The system uses only the workflow objects necessary to coordinate delivery.

### 7.5 Predictability Over Magic
Core behavior should rely on explicit schemas, state machines, and rule checks, not vague autonomous behavior.

---

## 8. High-Level Architecture

The system architecture is:

### Collaboration Surface
Primarily Feishu-native

- Feishu messages for intake, clarification, escalation, and notification
- Feishu Docs for summaries and delivery records
- Feishu Base for state display
- optional Feishu Tasks for formal task sync

### Core Engine
Independent WorkGraph Engine

- parser
- graph store
- state machine
- orchestration engine
- conflict engine
- decision application
- audit logging

### Optional Console
A lightweight external web app

- project overview
- conflict center
- decision actions
- workflow run visibility

---

## 9. System Layers

## 9.1 Ingestion Layer

Responsibilities:
- receive external events
- verify and normalize them
- persist raw event logs
- deduplicate retries

Inputs:
- Feishu message events
- direct API intake requests
- manual test fixtures

Outputs:
- normalized intake events

## 9.2 Parsing Layer

Responsibilities:
- interpret natural language
- convert raw text into structured workflow objects
- identify missing information
- estimate parsing confidence

Outputs:
- requirement summary
- goals
- deliverables
- constraints
- risks
- open questions

## 9.3 WorkGraph Core Layer

Responsibilities:
- persist project state
- store entities and relations
- maintain versions
- support graph updates after clarification or decisions

## 9.4 Orchestration Layer

Responsibilities:
- determine current stage
- invoke agents
- route outputs into graph updates
- decide when to sync back to Feishu
- decide when to escalate

## 9.5 Conflict Layer

Responsibilities:
- detect workflow conflicts
- explain conflict impact
- generate resolution options
- determine whether human approval is required

## 9.6 Sync Layer

Responsibilities:
- write state back to Feishu Base
- create and update Docs
- send clarification prompts
- send escalation notifications

## 9.7 Observability Layer

Responsibilities:
- event log
- workflow log
- agent log
- sync log
- decision audit log

---

## 10. Domain Model

The WorkGraph is built on a minimal set of domain entities.

## 10.1 Project

Represents one coordinated delivery workflow.

Fields:
- `id`
- `name`
- `status`
- `current_stage`
- `owner_user_id`
- `source_type`
- `source_ref`
- `created_at`
- `updated_at`

## 10.2 Requirement

Represents the incoming request and its evolving versions.

Fields:
- `id`
- `project_id`
- `title`
- `raw_text`
- `summary`
- `status`
- `priority`
- `source_message_id`
- `version`
- `created_at`
- `updated_at`

## 10.3 Goal

Represents what the workflow is trying to achieve.

Fields:
- `id`
- `project_id`
- `title`
- `description`
- `success_criteria_json`
- `status`

## 10.4 Deliverable

Represents a concrete output.

Fields:
- `id`
- `project_id`
- `goal_id`
- `title`
- `type`
- `status`

## 10.5 Task

Represents the minimum executable unit in the workflow.

Fields:
- `id`
- `project_id`
- `deliverable_id`
- `title`
- `description`
- `type`
- `owner_user_id`
- `owner_role`
- `status`
- `priority`
- `due_date`
- `acceptance_criteria_json`
- `source_agent_run_id`
- `created_at`
- `updated_at`

## 10.6 Dependency

Represents directional dependency between tasks.

Fields:
- `id`
- `project_id`
- `from_task_id`
- `to_task_id`
- `type`
- `blocking_level`

## 10.7 Constraint

Represents a workflow constraint.

Examples:
- deadline
- technical restriction
- permission boundary
- fixed scope
- resource limit

Fields:
- `id`
- `project_id`
- `type`
- `content`
- `severity`

## 10.8 Risk

Represents a known project risk.

Fields:
- `id`
- `project_id`
- `title`
- `content`
- `severity`
- `likelihood`
- `status`
- `mitigation`

## 10.9 Conflict

Represents a detected contradiction or workflow collision.

Examples:
- deadline vs scope
- blocked dependency
- missing owner
- unresolved requirement ambiguity
- downstream task progressing while upstream remains blocked

Fields:
- `id`
- `project_id`
- `type`
- `summary`
- `severity`
- `related_object_refs_json`
- `suggestions_json`
- `requires_human_decision`
- `status`
- `created_at`
- `updated_at`

## 10.10 Decision

Represents an approved judgment or tradeoff.

Fields:
- `id`
- `project_id`
- `title`
- `content`
- `decision_type`
- `made_by`
- `rationale`
- `impact_scope_json`
- `status`
- `created_at`

## 10.11 Evidence

Represents proof of completion or supporting delivery artifacts.

Fields:
- `id`
- `project_id`
- `type`
- `title`
- `uri`
- `summary`
- `status`

---

## 11. Relationship Model

The system needs only a minimal relationship graph.

Supported relations:

- `depends_on`
- `blocks`
- `implements`
- `verifies`
- `derived_from`
- `supersedes`
- `assigned_to`

Relationship rules:

1. A Requirement may produce one or more Goals
2. A Goal may produce one or more Deliverables
3. A Deliverable decomposes into Tasks
4. Tasks may depend on other Tasks
5. Risks may attach to Requirement, Goal, Deliverable, or Task
6. Conflicts may reference Tasks, Constraints, Risks, or Decisions
7. Evidence verifies Deliverables or Tasks
8. Decisions can supersede previous plans or scope assumptions

---

## 12. State Machines

## 12.1 Requirement State Machine

```text
draft -> clarifying -> confirmed -> planned -> in_progress -> verifying -> delivered -> closed
Descriptions:

draft: raw requirement received, not yet processed
clarifying: system has identified missing blocking information
confirmed: requirement is sufficiently clarified
planned: tasks and dependencies have been created
in_progress: execution is underway
verifying: validation and delivery readiness are being checked
delivered: delivery summary is generated
closed: workflow is complete and archived
12.2 Task State Machine
todo -> assigned -> doing -> blocked -> review_pending -> done
                                  \-> canceled

Descriptions:

todo: task exists but not yet assigned or started
assigned: responsibility is defined
doing: execution in progress
blocked: task cannot move due to missing dependency or unresolved conflict
review_pending: task output exists and needs review or validation
done: accepted as complete
canceled: intentionally removed from scope
12.3 Risk State Machine
identified -> assessed -> mitigating -> resolved
                           \-> accepted
                           \-> escalated
12.4 Conflict State Machine
detected -> analyzing -> suggested -> waiting_decision -> resolved
                                                   \-> deferred
13. Stage Model

The workflow is managed in stages.

Stage 1 — Intake

The system receives requirement input.

Stage 2 — Clarification

The system asks targeted, blocking clarification questions.

Stage 3 — Planning

The system generates delivery structure.

Stage 4 — Execution

Tasks are underway, state updates continue, sync is active.

Stage 5 — Conflict Handling

The system detects and explains execution conflicts.

Stage 6 — Validation

The system checks readiness for delivery.

Stage 7 — Delivery

The system produces final delivery artifacts.

The current_stage field on Project must always reflect one of these stages.

14. Core Workflow
14.1 Requirement Intake Flow
receive Feishu message or API request
create event_log
normalize into intake payload
create Project and Requirement records
call Requirement Agent
store parsed output
if blocking ambiguity exists, transition to clarifying
otherwise transition to confirmed
14.2 Clarification Flow
generate max 3 high-value questions
send them to Feishu
receive replies
merge replies into Requirement version N+1
update graph state
if still insufficient, ask another round
if sufficient, transition to confirmed

Rules:

never ask endless questions
never ask cosmetic questions
prioritize questions that unblock planning
14.3 Planning Flow
invoke Planning Agent
generate Deliverables
generate Tasks
generate Dependencies
generate Risks
persist graph
transition Project to planned
sync initial state to Base and Docs
14.4 Execution Update Flow
receive feedback or status update
map update to relevant Tasks / Risks / Constraints
update graph
run conflict detection
sync changed state back to Feishu
14.5 Conflict Flow
detect conflict via rule engine
enrich explanation with LLM if needed
generate 2–3 options
determine whether human approval is required
if yes, send escalation
if no, apply low-risk automated update
update graph and sync
14.6 Decision Flow
Approver selects a proposed option or enters a custom decision
system creates Decision record
system updates affected Tasks / Risks / Deliverables / Conflicts
system resyncs Base and Docs
Project returns to in_progress or advances if conflict is terminally resolved
14.7 Delivery Flow
invoke QA Agent
invoke Delivery Agent
confirm completed and deferred scope
attach evidence links
generate delivery summary Doc
transition Requirement to delivered
15. Conflict Model

The MVP must support explicit conflict detection.

15.1 Conflict Types
Deadline vs Scope Conflict

The approved or implied scope exceeds the available delivery window.

Dependency Blocking Conflict

A task cannot progress because an upstream dependency is incomplete or undefined.

Missing Owner Conflict

A required task exists without a clear owner or owner role.

Blocked Downstream Conflict

A downstream task is marked active while an upstream blocker remains unresolved.

Clarification Gap Conflict

Planning or validation is proceeding while a critical requirement ambiguity remains unresolved.

15.2 Conflict Severity
low
medium
high

Severity rules should prefer explicit logic over LLM guessing.

15.3 Conflict Resolution Behavior

For each conflict, the system must produce:

summary
impacted scope
severity
2–3 distinct options
recommended option
whether human approval is required
15.4 Human Escalation Triggers

Human approval is required when:

scope must change
deadline must change
risk is high
a critical responsibility changes
a release decision is implied
model confidence is low
conflict is policy-sensitive
16. Feishu Integration Strategy
16.1 Why Feishu Is the Collaboration Surface

Feishu already provides the core collaboration objects needed for MVP:

Messages
Docs
Base
Tasks
event subscription

Therefore, the MVP should use Feishu as the visible collaboration layer rather than rebuilding all collaboration interfaces from scratch.

16.2 Feishu Usage Mapping
Messages

Used for:

requirement input
clarification questions
escalation notices
completion notifications
Docs

Used for:

requirement summary
planning summary
delivery summary
optional review notes
Base

Used for:

task table
risk table
conflict table
decision table
Tasks

Optional in MVP, used for:

task ownership
due dates
formal follow-up objects
16.3 Integration Boundary

Feishu is the collaboration surface.
WorkGraph Engine is the logic layer.

Feishu should not contain core orchestration logic.

17. Web Console Scope

The MVP should include a lightweight external web console.

This is not a full product UI. It is a debug and demo surface.

17.1 Required Pages
Project Overview

Shows:

current stage
summary
goals
recent conflicts
recent decisions
Conflict Center

Shows:

detected conflicts
options
decision actions
Project Snapshot

Shows:

tasks
risks
dependencies
delivery status
17.2 Optional Pages
Agent Run Log

For debugging and demos.

Audit Timeline

For replay and explanation.

18. API Design
18.1 Public API
POST /api/intake/message

Creates a project from an incoming message.

Request:

{
  "source": "feishu",
  "message_id": "string",
  "chat_id": "string",
  "text": "string"
}

Response:

{
  "project_id": "string",
  "requirement_id": "string",
  "status": "clarifying"
}
POST /api/projects/{project_id}/clarify-reply

Submits answers to clarification questions.

POST /api/projects/{project_id}/plan

Triggers planning explicitly.

GET /api/projects/{project_id}

Returns project summary.

GET /api/projects/{project_id}/snapshot

Returns full workflow snapshot.

GET /api/projects/{project_id}/conflicts

Returns conflict list.

POST /api/conflicts/{conflict_id}/decision

Applies human decision.

Request:

{
  "decision_type": "option|custom",
  "selected_option_index": 0,
  "custom_decision_text": null,
  "made_by": "string"
}
POST /api/projects/{project_id}/delivery-summary

Generates delivery summary.

18.2 Internal Service Interfaces

These internal capabilities must exist, whether as service methods or jobs:

parse_requirement()
generate_clarification_questions()
build_initial_graph()
merge_clarification_answers()
generate_plan()
detect_conflicts()
generate_conflict_options()
apply_decision()
sync_project_to_base()
sync_project_to_docs()
generate_delivery_summary()
19. Agent Contracts

All agent outputs must be schema-constrained JSON.

No core agent may return free-form prose as the primary contract.

19.1 Shared Rules

All agents must:

output valid JSON only
never invent owners, dates, or approved decisions
use unknown if information is missing
preserve approved decisions
avoid scope expansion unless explicitly requested
separate facts from uncertainties
19.2 Requirement Agent

Input:

raw requirement text
context snapshot

Output:

summary
goals
deliverables
constraints
risks
open questions
confidence
19.3 Clarification Agent

Input:

parsed requirement
open questions
current constraints

Output:

max 3 clarification questions
target role for each
blocking level
19.4 Planning Agent

Input:

clarified requirement
constraints
decisions

Output:

deliverables
tasks
dependencies
milestones
risks
19.5 QA Agent

Input:

task list
deliverables
known scope

Output:

test points
blocking issues
acceptance criteria
19.6 Conflict Explanation Agent

Input:

detected conflict
graph snapshot
related objects

Output:

summary
impact scope
options
recommendation
requires_human_decision
19.7 Delivery Agent

Input:

project snapshot
completed tasks
deferred tasks
decisions
evidence links

Output:

delivery summary
completed scope
deferred scope
key decisions
remaining risks
20. Data Persistence
20.1 Recommended Storage

Use:

PostgreSQL for primary structured state
Redis for async tasks and caching
file/object storage for exported artifacts if needed

Do not use a graph database for MVP unless absolutely necessary.

20.2 Minimum Required Tables
projects
requirements
goals
deliverables
tasks
task_dependencies
constraints
risks
conflicts
decisions
evidences
events
agent_runs
feishu_bindings
20.3 Versioning

The system must support Requirement versioning.
Clarification rounds should produce updated versions, not destructive overwrites.

21. Event Model
21.1 External Events
message.received
clarification.answered
task.updated
decision.submitted
delivery.requested
21.2 Internal Domain Events
requirement.parsed
clarification.generated
clarification.merged
plan.generated
conflict.detected
conflict.escalated
decision.applied
delivery.generated
21.3 Event Rules

Every event must be:

persisted
idempotent
replayable
traceable to a project
22. Reliability and Error Handling
22.1 Ingestion Failure

Cases:

duplicate message
invalid payload
empty text

Handling:

reject invalid payload
deduplicate repeated events
record failure reason
do not create duplicate projects
22.2 LLM Failure

Cases:

timeout
malformed JSON
obviously invalid content

Handling:

retry once
run fallback parser or recovery prompt
if still invalid, create manual review flag
22.3 Sync Failure

Cases:

Feishu API failure
permission issue
object not found

Handling:

mark sync failure
queue retry
surface in logs and console
do not silently discard state
22.4 State Integrity Failure

Cases:

dependency loop
impossible state transition
decision applied to closed project

Handling:

reject invalid mutation
log integrity violation
surface to console
require manual correction
23. Governance Rules
23.1 What AI May Do Automatically

AI may:

parse requirements
generate task suggestions
generate docs drafts
generate risk suggestions
detect conflicts
send clarification prompts
send escalation notifications
generate delivery summaries
23.2 What AI May Not Approve Automatically

AI may not:

approve final scope
approve major deadline changes
approve high-risk release tradeoffs
assign irreversible responsibility changes without human confirmation
finalize delivery without human acknowledgment
23.3 Audit Requirements

The system must record:

who triggered an action
which agent ran
what the input was
what the output was
whether a human approved something
what Feishu objects were updated
24. Observability
24.1 Logs

Required logs:

request log
event log
workflow log
agent log
sync log
decision log
24.2 Metrics

Minimum metrics:

intake success rate
parser success rate
average clarification rounds
planning latency
sync success rate
conflict detection count
decision resolution time
delivery completion count
24.3 Traceability

Each project must have a workflow trace ID so that every stage and event can be replayed for debugging or demo explanation.

25. Security and Secrets

The MVP does not need enterprise security, but it must handle secrets safely.

Requirements:

never hardcode Feishu or model credentials
validate webhook signatures where applicable
keep audit trails for critical mutations
prevent silent overwrite of approved decisions
26. Suggested Tech Stack
26.1 Backend
Python
FastAPI
SQLAlchemy
Pydantic
26.2 Async / Workers
Celery or RQ
Redis
26.3 Database
PostgreSQL
26.4 Frontend
Next.js
TypeScript
Tailwind
26.5 Why This Stack

This stack is conventional, stable, and fast enough for MVP implementation.
It supports structured workflow services and LLM orchestration without introducing unnecessary complexity.

27. Repository Structure
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
  infra/
    docker/
    scripts/
  docs/
    dev.md
    engineering-backlog.md
    prompt-contracts.md
    demo-script.md
28. Implementation Priorities
28.1 P0 — Must Exist
intake endpoint
Feishu message intake path
requirement parser
graph initialization
planning agent
task/risk/dependency persistence
Base sync
conflict detection
decision application
delivery summary generation
28.2 P1 — Strongly Preferred
clarification loop
Docs sync
conflict center in web console
audit visibility
retry queue for sync failures
28.3 P2 — Optional for Competition
task sync to Feishu Tasks
agent run debug page
advanced prioritization logic
richer dependency visualization
29. Definition of Done for MVP

The MVP is considered done when the following are all true:

a Feishu message can create a project
the system can parse the message into structured workflow objects
the system can ask at least one targeted clarification question when needed
the system can generate tasks, risks, and dependencies
the system can sync those objects into Feishu Base
the system can detect at least 3 conflict types
the system can present 2–3 resolution options for a critical conflict
a human can approve one option
the graph state updates correctly after that decision
the system can generate a final delivery summary
30. Demo Success Criteria

The competition demo succeeds if it clearly shows:

AI creates shared state, not just text summaries
AI drives flow across multiple delivery stages
conflict detection happens before a human meeting is required
humans intervene only for real tradeoffs
final delivery output reflects approved decisions and current project state
31. MVP Example Scenario
Input

A Feishu message says:

“We need to launch an event registration page next week. It needs invitation code validation, phone number validation, admin export, and conversion tracking.”

System Behavior
create project
parse requirement
ask clarification:
are invitation codes single-use or reusable?
should exported data include phone numbers?
is admin management required in this version?
generate plan
create tasks
detect conflict when engineering says:
“we cannot finish advanced invitation code logic and admin management by next week”
produce options:
drop admin management
delay launch
split into phase one and phase two
Approver selects phase split
update graph and Base
generate delivery summary

This is the canonical demo path and the primary test scenario for MVP.

32. Future Extensions

After MVP, the next likely extensions are:

code repository integration
test result ingestion
richer workflow analytics
reusable team memory
cross-project dependency tracking
more advanced governance policies

These extensions must not distort the MVP architecture.

33. Final Positioning Statement

WorkGraph AI is not a general chatbot, and it is not merely a coding assistant.
It is a workflow coordination engine that turns fragmented requirement delivery into shared, AI-mediated execution state.

Its purpose is to reduce the hidden cost of delivery coordination by making AI responsible for:

maintaining shared context
structuring workflow state
exposing risks and conflicts early
preparing human decisions instead of replacing them

That is the core of the system and the non-negotiable standard for all implementation decisions.