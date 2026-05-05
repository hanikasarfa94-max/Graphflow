# GraphFlow Flow Packets and Recipes

**Status:** proposal, pre-production spec  
**Date:** 2026-05-05  
**Owner:** product / architecture  
**Why now:** GraphFlow already has routing, pre-answer, scrimmage, Membrane, KB, tasks, decisions, handoff, meeting metabolism, and ritual shortcuts. The missing product layer is a visible, reusable workflow object that lets tasks flow between humans while agents metabolize every edge.

---

## 1. Product Thesis

GraphFlow is not a virtual team that replaces the real team.

GraphFlow is the workflow fabric between real teammates:

```text
human -> their sub-agent -> graph-aware edge -> another sub-agent -> human
```

The graph is still the state. The stream is still the primary surface. Humans still make judgment calls. The new layer is a projection that makes work circulation observable.

**Core sentence:**

> A Flow Packet is a traceable unit of work moving across human nodes, with AI metabolizing each edge and Membrane governing every write into shared context.

This is the GraphFlow-native version of what gstack demonstrates for one AI-assisted builder: named workflows, explicit gates, evidence, and ritualized completion.

Relationship to the 5-layer model:

Flow Packets are not a sixth architectural layer. They are a projection over the Graph layer, surfaced through Projection-Attention. A packet may pass through Cell, Membrane, Graph, LLM, and Projection-Attention, but it does not compete with them. It is the user-facing trace of work moving through those layers.

---

## 2. Inspiration From gstack

gstack's useful lesson is not "add many fake coworkers." Its useful lesson is that AI work becomes dependable when it is packaged as named rituals with clear inputs, gates, artifacts, and finish lines.

Observed gstack patterns worth borrowing:

- Named rituals: planning, review, QA, ship, retro, investigate.
- Process order: think -> plan -> build -> review -> test -> ship -> reflect.
- Evidence gates: QA produces before/after evidence; review records findings and fix status.
- Cross-step memory: one skill writes artifacts that downstream skills read.
- Learnings: reusable patterns and pitfalls compound over time.
- Safety rails: destructive actions and risky changes are gated before execution.

What GraphFlow should not copy:

- Do not expose a roster of specialist-agent contacts.
- Do not make slash commands the main product surface.
- Do not simulate a fake team around one human.
- Do not let agent rituals write canonical team memory without Membrane.

GraphFlow adaptation:

```text
gstack:    tasks flow between agent roles for one human builder
GraphFlow: tasks flow between real humans, with each edge agent-boosted
```

Sources checked:

- gstack README: https://github.com/garrytan/gstack
- gstack ETHOS: https://github.com/garrytan/gstack/blob/main/ETHOS.md
- gstack QA skill: https://github.com/garrytan/gstack/blob/main/qa/SKILL.md
- gstack review skill: https://github.com/garrytan/gstack/blob/main/review/SKILL.md

---

## 3. Current GraphFlow Primitives To Reuse

Do not rebuild these. Flow Packets should project over them first.

| Primitive | Current file | Use in Flow Packet |
|---|---|---|
| Personal edge loop | `apps/api/src/workgraph_api/services/personal.py` | source turn, agent answer, route proposal, tool calls |
| Routed signal | `apps/api/src/workgraph_api/services/routing.py` | human-to-human packet backbone |
| Pre-answer | `apps/api/src/workgraph_api/services/pre_answer.py` | target-agent draft before interrupting target human |
| Scrimmage | `apps/api/src/workgraph_api/services/scrimmage.py` | agent-to-agent debate before human escalation |
| Membrane | `apps/api/src/workgraph_api/services/membrane.py` | write boundary for KB/task/decision/graph promotions |
| Decision vote | `apps/api/src/workgraph_api/services/decision_votes.py` | smallest-relevant-vote after crystallization |
| Handoff | `apps/api/src/workgraph_api/services/handoff.py` | succession packet and role-routine transfer |
| Meeting ingest | `apps/api/src/workgraph_api/services/meeting_ingest.py` | meeting transcript -> proposed packets |
| Skill atlas | `apps/api/src/workgraph_api/services/skill_atlas.py` | target selection and profile learning |
| Render service | `apps/api/src/workgraph_api/services/render.py` | packet evidence -> postmortem/handoff citations |
| Ritual shortcuts | `apps/web/src/lib/rituals.ts` | v0 command entry points |

Graphify confirms this is already a dense system: `graphify-out/GRAPH_REPORT.md` reports thousands of nodes and edges, with routing, personal services, Membrane, render, and handoff as separate communities. This spec should connect those communities as a product-visible flow.

---

## 4. Definitions

### Flow Packet

A Flow Packet is a projection over existing rows that represents one unit of work moving through the graph.

Examples:

- Maya asks Raj for a design call.
- Sofia's playtest report is promoted into KB.
- A meeting action item becomes a task.
- A handoff is prepared for James.
- A risky decision needs legal approval.

### Flow Recipe

A Flow Recipe is a reusable workflow template that defines:

- trigger
- participant roles
- agent passes
- required human gates
- allowed graph mutations
- evidence requirements
- completion condition

### Evidence Packet

An Evidence Packet is the proof bundle attached to a Flow Packet:

- citations
- source messages
- diffs
- screenshots or artifacts when applicable
- agent runs
- review decisions
- accepted/countered/delegated/gated history

### Flow Stage

A Flow Stage is a derived display label. It must not become a new source of truth.

Allowed examples:

- `drafting`
- `pre_answered`
- `routed`
- `awaiting_target`
- `countered`
- `awaiting_membrane`
- `awaiting_vote`
- `crystallized`
- `published`
- `rejected`
- `expired`

The canonical state still lives in graph rows.

---

## 5. Non-Goals

This spec does not introduce:

- a new specialist-agent picker
- a separate workflow-stage table as source of truth
- a replacement for Membrane
- a project-management board as primary surface
- agent autonomy to mutate shared memory without human or policy gates
- cross-project graph edges
- voice/video/meeting features

The default UX remains stream-centered. Flow views are projections, badges, drawers, workbench panels, and detail/audit routes.

---

## 6. Flow Packet Projection Model

Start as a read model. Add a table only when projection becomes too slow or audit requirements demand immutable snapshots.

```ts
type FlowPacket = {
  id: string;
  project_id: string;
  recipe_id: FlowRecipeId;
  stage: FlowStage;
  status: "active" | "blocked" | "completed" | "rejected" | "expired";

  source_user_id?: string;
  current_target_user_ids: string[];
  target_user_ids: string[];
  authority_user_ids: string[];

  title: string;
  summary: string;
  intent: string;

  source_refs: FlowRef[];
  graph_refs: FlowRef[];
  evidence: EvidencePacket;

  routed_signal_id?: string;
  im_suggestion_id?: string;
  membrane_candidate?: {
    kind: string;
    action?: string;
    conflict_with: string[];
    warnings: string[];
  };
  decision_id?: string;
  kb_item_id?: string;
  task_id?: string;
  handoff_id?: string;
  scrimmage_id?: string;
  meeting_transcript_id?: string;

  timeline: FlowEvent[];
  next_actions: FlowAction[];

  created_at: string;
  updated_at: string;
};
```

Supporting shapes:

```ts
type FlowRef = {
  kind: "message" | "decision" | "kb" | "task" | "risk" | "handoff" | "meeting" | "agent_run";
  id: string;
  label: string;
  href?: string;
};

type EvidencePacket = {
  citations: FlowRef[];
  source_messages: FlowRef[];
  artifacts: FlowRef[];
  agent_runs: FlowRef[];
  human_gates: {
    user_id: string;
    action:
      | "accept"
      | "counter"
      | "dismiss"
      | "delegate_up"
      | "escalate_to_gate"
      | "approve"
      | "reject";
    at: string;
    note?: string;
  }[];
  uncertainty: string[];
};

type FlowEvent = {
  at: string;
  actor: "human" | "edge_agent" | "parent_agent" | "membrane" | "system";
  actor_user_id?: string;
  kind: string;
  summary: string;
  refs: FlowRef[];
};

type FlowAction = {
  id: string;
  label: string;
  kind:
    | "accept"
    | "counter"
    | "delegate_up"
    | "escalate_to_gate"
    | "dismiss"
    | "open"
    | "publish"
    | "request_review";
  actor_user_id?: string;
  requires_membrane: boolean;
};
```

Participation fields:

- `target_user_ids` is participation history: every human this packet has asked, notified, or involved.
- `current_target_user_ids` is derived from stage and next action: the humans who currently need to respond.
- `authority_user_ids` is the gate set: owners, scoped approvers, legal/finance/HR, or quorum members.

Example: a packet routes to Raj, Raj cannot answer and delegates up to Maya, then Maya gates the decision. `target_user_ids = [Raj, Maya]`; `current_target_user_ids = [Maya]`; `authority_user_ids = [Maya]`. The array does not imply everyone listed is currently blocking the packet.

Projection rules:

- `RoutedSignalRow` becomes the packet spine for person-to-person flows.
- `IMSuggestionRow` becomes a packet gate when the flow awaits owner review.
- `KbItemRow(status='draft')` becomes a packet awaiting Membrane review.
- `DecisionRow(apply_outcome='pending_*')` becomes a packet awaiting approval or vote.
- `ScrimmageRow` attaches as evidence and may generate a pending decision packet.
- `HandoffRow(status='draft')` becomes a packet awaiting owner finalization.
- `MeetingTranscriptRow.extracted_signals` yields proposed packets until accepted.

---

## 7. Required Invariants

### 7.1 Human Judgment Stays At Nodes

Agents may draft, compress, debate, cite, and recommend. They do not silently make final team judgments.

Allowed automatic actions:

- summarize context
- rank likely targets
- run pre-answer
- run scrimmage
- detect duplicates
- attach citations
- create personal drafts
- create pending candidates

Blocked without gate:

- publish team KB
- crystallize team decision
- promote personal task into plan
- change voting scope
- close risk as resolved
- finalize handoff

### 7.2 Membrane Is The Single Boundary

Every write into shared context must pass through Membrane or an explicitly documented domain gate that is Membrane-equivalent.

Flow Recipes must declare:

```text
canonical write? yes/no
candidate kind
review action mapping
owner or quorum gate
audit refs
```

### 7.3 Personal Stream Is Protected

Inbound work packets must not hijack the user's personal thinking stream.

Allowed surfaces:

- sidebar badge
- right drawer
- top pending strip
- optional workbench panel
- DM mirror log

The personal stream can mention important replies after the source is affected, but target-side inbound work should remain outside the main conversation until opened.

### 7.4 Options Are Replies, Not Re-Routes

Target-side actions are:

- accept
- counter
- delegate_up
- custom reply

No "route this to someone else" from an inbound option card. The target is answering the source, not becoming a router.

`delegate_up` is the target-side exception for authority escalation. It means: "I cannot answer this; push it to the appropriate authority with my stance attached." The target does not choose an arbitrary next recipient. Backend derives the authority from role, scope, or project owner rules.

### 7.5 Source-Side Reply Surface Is Symmetric

When the source receives a reply, the source must be able to:

- accept as final
- counter back
- escalate_to_gate
- send custom follow-up

This is already called out as a frontend bug in `docs/north-star.md`; Flow Packets should treat it as a hard requirement.

`escalate_to_gate` is source-side. It means: "I am not satisfied resolving this as a bilateral reply; ask the authority pool or quorum to decide." It may create a Membrane candidate, decision vote, or approval gate depending on recipe.

### 7.6 Evidence Before Completion

A packet cannot be marked completed unless it has one of:

- human acceptance
- Membrane publish/merge
- vote crystallization
- explicit dismissal
- expiration policy

Agent text alone is not completion.

---

## 8. First Production Recipes

### 8.1 Ask With Context

Purpose: ask another teammate without forcing the source to manually prepare context or the target to reread history.

Trigger:

- Edge route proposal
- `/route`
- user selects "Ask [target]"

Flow:

```text
source human turn
-> source edge frames intent
-> optional target pre-answer
-> optional scrimmage
-> parent router dispatches RoutedSignalRow
-> target drawer card
-> target replies
-> source reply card
-> accept/counter/escalate_to_gate
-> optional decision/task/KB candidate
```

Required evidence:

- source message
- framing summary
- cited graph/KB background
- target options
- target reply
- source final action

Completion:

- source accepts final reply
- source uses `escalate_to_gate`
- packet expires
- reply crystallizes into another recipe

### 8.2 Promote To Team Memory

Purpose: turn useful conversation or external content into KB without letting raw agent output become shared memory.

Trigger:

- Save to wiki
- `/save`
- Edge `propose_wiki_entry`
- external Membrane ingest

Flow:

```text
source message or artifact
-> edge drafts title/content/classification
-> KbItemRow draft
-> Membrane review
-> owner accept/counter/dismiss/escalate_to_gate
-> KbItemRow published or archived
```

Required evidence:

- source message/artifact
- generated draft
- Membrane review action
- diff summary
- owner action

Completion:

- KB published
- draft dismissed/archived
- clarification unanswered past expiration

### 8.3 Crystallize Decision

Purpose: convert a judgment-shaped discussion into DecisionRow with scope and lineage.

Trigger:

- IMAssist decision suggestion
- `/crystallize`
- scrimmage convergence
- meeting metabolized decision

Flow:

```text
decision-shaped evidence
-> edge/IMAssist proposal
-> Membrane review for decision_crystallize
-> scope selection by smallest relevant group
-> owner or quorum gate
-> DecisionRow
-> Dissent slot opens
```

Required evidence:

- source message(s)
- proposal text
- scope basis
- voter set or owner authority
- accepted/countered history

Completion:

- DecisionRow crystallized
- rejected
- sent to meeting/sync gate

### 8.4 Review Flow

Purpose: bring gstack's evidence discipline into human teamwork.

Trigger:

- "review this"
- `/review` future ritual
- task owner requests review
- PR/web artifact/external URL linked in stream

Modes:

```ts
type ReviewMode = "code" | "design" | "compliance" | "launch";
```

Mode-specific evidence:

| Mode | Required evidence |
|---|---|
| `code` | diff refs, test results, risk findings, fix status |
| `design` | visual artifact refs, screenshot or mock reference, design-dimension findings |
| `compliance` | policy/source refs, approver sign-off trail, unresolved exceptions |
| `launch` | checklist refs, environment/build refs, go/no-go owner sign-off |

Flow:

```text
requester asks for review
-> backend derives review mode from artifact/context
-> requester edge creates review packet
-> reviewer edge prepares checklist and context
-> reviewer human accepts/counters/finds issues
-> evidence packet attaches artifacts
-> fixes become tasks or decision candidates
-> requester accepts review result
```

Required evidence:

- artifact under review
- checklist used
- findings
- before/after proof when fixes are made
- reviewer human sign-off

Completion:

- accepted as reviewed
- issues converted to tasks
- sent to gate

Note: this should borrow gstack's QA/review proof habit, not its coding-only scope. It should work for design, game build, compliance, launch checklist, and partnership materials. Do not ship an untyped `review_qa` recipe; one generic review would collapse into weak "please look at this" behavior. Use one `review` recipe with explicit mode-specific rails.

### 8.5 Handoff Flow

Purpose: transfer graph position and routines when a teammate leaves, changes role, or hands off a task.

Trigger:

- `/handoff`
- profile card handoff button
- owner prepares handoff

Flow:

```text
owner selects from/to
-> HandoffService derives routines and evidence
-> draft handoff packet
-> owner review
-> successor receives context card
-> finalized handoff joins graph/render layer
```

Required evidence:

- decisions resolved by predecessor
- inbound/outbound routings
- role skills
- profile routines
- owner approval

Completion:

- handoff finalized
- dismissed
- successor asks clarification, opening Ask With Context packet

### 8.6 Meeting Metabolism Flow

Purpose: prevent meetings from becoming unstructured memory dumps.

Trigger:

- transcript upload
- re-metabolize

Flow:

```text
transcript uploaded
-> meeting agent extracts proposed decisions/tasks/risks/stances
-> each extracted signal becomes proposed packet
-> human accepts individual signals
-> accepted signals route through canonical services
```

Required evidence:

- transcript
- extracted signal
- participant context
- accept action
- resulting graph row

Completion:

- all extracted signals accepted/dismissed
- transcript marked failed/expired

---

## 9. Task Visibility Model

Flow Packets are related to tasks, but they are not tasks.

```text
Task = durable work commitment or draft to-do
Flow Packet = circulation/gating path that may create, promote, review, update, or close a task
```

The existing `TaskRow` already has the right visibility split:

- `scope='personal'`: private self-set task, visible only to `owner_user_id`.
- `scope='plan'`: canonical team plan task, visible as project graph state.
- `source_message_id`: optional lineage back to the stream turn that created it.
- `owner_user_id`: owner for personal tasks; not the same as active assignee for plan tasks.

### 9.1 Personal Tasks

Personal tasks are private drafts.

Who can see:

- owner user
- owner's sub-agent, inside the owner's licensed project context
- project owner only after the owner promotes or explicitly shares the task

Where they appear:

- personal task workbench panel
- active-task context for the owner
- personal stream replies when the owner asks about their work

Rules:

- Creating a personal task does not require Membrane.
- Personal tasks do not enter team context.
- Personal tasks do not show in team status, graph detail, team room, or another member's retrieval slice.
- Promotion to team plan creates a Flow Packet and calls Membrane with `CandidateKind='task_promote'`.

### 9.2 Plan Tasks

Plan tasks are shared graph state.

Who can see:

- full project members
- task-scoped members only for assigned or explicitly related tasks
- observers as read-only, if their license slice includes the task

Where they appear:

- project status
- `/detail/tasks`
- relevant graph/node detail
- handoff and postmortem renders when cited
- personal active-task context for the assignee

Rules:

- Plan tasks are not created silently from agent prose.
- Plan tasks can originate from planning, meeting signal acceptance, or personal-task promotion.
- Any user-visible promotion path goes through Membrane or an equivalent domain gate.
- Status self-reports and owner scoring are task lifecycle events, not Flow Packet completion by themselves.

### 9.3 Flow Packets That Touch Tasks

Task-related Flow Packets are visible by participation, not by task visibility alone.

Examples:

- Personal task promotion: visible to task owner and Membrane reviewers until merged; visible to team only after plan promotion.
- Review packet on a plan task: visible to requester, reviewer, assignee, project owners, and task-scoped viewers included by license.
- Meeting action item: visible to transcript uploader and reviewers until accepted; after acceptance, the resulting plan task follows plan visibility.
- Handoff task transfer: visible to owner, predecessor, successor, and project owner until finalized.

The UI should answer two different questions:

- Task view: "What work exists, and who owns it?"
- Flow view: "Where is the work currently blocked, and who needs to act?"

This separation prevents Flow Packets from becoming a task manager while still making task motion visible.

---

## 10. UI Surfaces

### 10.1 Active Flows Drawer

Right-side drawer, accessible from sidebar badge.

Sections:

- Needs me
- Waiting on others
- Awaiting Membrane
- Recently completed

Each row shows:

- recipe icon/label
- title
- current stage
- who has the next action
- age/SLA
- evidence count
- primary action

### 10.2 Flow Detail

Route:

```text
/projects/[projectId]/flows/[flowId]
```

Purpose: audit and explanation, not daily primary UI.

Sections:

- packet summary
- current next action
- timeline
- evidence packet
- graph refs
- Membrane/vote status
- raw rows for debugging in dev/admin mode

### 10.3 Inline Cards

Show Flow Packet cards only when structurally important:

- route proposal ready
- target replied
- Membrane waiting
- decision crystallized
- review complete
- handoff finalized

Do not turn every packet event into a card. The stream would become a workflow log, which violates the personal-stream principle.

### 10.4 Workbench Panel

Optional panel kind:

```text
Flow
```

Use it as a shortcut to active packets. It must deep-link to detail routes and drawers. It must not become the only place flow state exists.

### 10.5 Composer Rituals

Keep slash rituals as accelerators.

Current v0 rituals:

- `/save`
- `/route`
- `/risk`
- `/why`
- `/handoff`
- `/crystallize`

Proposed additions:

- `/review`

Do not add `/qa`, `/counter`, `/escalate`, or `/packet` until projection can show the packets they create or continue. Rituals are accelerators, not the product surface.

Important: selecting a ritual should create or continue a Flow Packet only when the backend derives a workflow-shaped signal from the existing domain event. Otherwise it remains an ordinary stream turn.

---

## 11. Backend API Sketch

Initial projection endpoints:

```http
GET /api/projects/{project_id}/flows
GET /api/projects/{project_id}/flows/{flow_id}
POST /api/projects/{project_id}/flows/{flow_id}/actions
```

List query params:

```text
status=active|blocked|completed|rejected|expired
bucket=needs_me|waiting_on_others|awaiting_membrane|recent
recipe=ask_with_context|promote_to_memory|crystallize_decision|review|handoff|meeting_metabolism
mode=code|design|compliance|launch
```

Action body:

```json
{
  "action": "accept",
  "note": "optional human explanation",
  "payload": {}
}
```

Implementation principle:

- The flow endpoint should dispatch to existing domain services.
- It should not bypass `RoutingService`, `MembraneService`, `DecisionVoteService`, `HandoffService`, or `MeetingIngestService`.
- Keep the HTTP router thin: validation, membership, service call, error mapping, status.
- Put cross-recipe dispatch in `FlowActionService`, with a small explicit dispatch table.
- `FlowActionService` may choose the domain service, but it must not own domain mutation logic.

---

## 12. Data Strategy

### Phase 1: Pure Projection

No new table.

Derive packets from:

- `RoutedSignalRow`
- `IMSuggestionRow`
- `KbItemRow`
- `DecisionRow`
- `TaskRow`
- `ScrimmageRow`
- `HandoffRow`
- `MeetingTranscriptRow`
- `AgentRunLogRow`
- `MessageRow`

Pros:

- fastest
- no migration risk
- proves product surface before committing schema

Cons:

- flow ids need deterministic synthetic ids
- timeline assembly may be expensive
- historical snapshots may shift if source rows change

Synthetic id examples:

```text
route:{routed_signal_id}
kb:{kb_item_id}
decision:{decision_id}
handoff:{handoff_id}
meeting:{meeting_transcript_id}:{signal_kind}:{signal_idx}
```

### Phase 2: FlowPacketRow Snapshot

Add only after projection proves useful.

Projection-only is sufficient for the demo and internal dogfooding. It is not sufficient for compliance-adjacent customers, because historical projections can shift when source rows are edited, archived, or backfilled. Before selling into any environment where audit reconstruction matters, add snapshot rows or immutable packet events.

Possible columns:

```text
id
project_id
recipe_id
status
stage
source_user_id
target_user_ids_json
current_target_user_ids_json
authority_user_ids_json
title
summary
root_ref_kind
root_ref_id
refs_json
evidence_json
next_actions_json
created_at
updated_at
completed_at
trace_id
```

Keep source rows authoritative. Snapshot rows cache projection and audit display.

---

## 13. Recipe Derivation Contract

Do not require the Edge agent to emit `flow.recipe_id`.

The backend derives Flow Packet recipe and mode from existing domain signals. This keeps the current Edge output contract smaller and avoids coupling the LLM to Flow Packet internals.

Derivation examples:

| Existing signal | Derived recipe |
|---|---|
| `kind='route_proposal'` | `ask_with_context` |
| `tool_call.name='routing_suggest'` plus user confirmation | `ask_with_context` |
| `tool_call.name='propose_wiki_entry'` | `promote_to_memory` |
| `IMSuggestion.kind='decision'` | `crystallize_decision` |
| `MembraneCandidate.kind='decision_crystallize'` | `crystallize_decision` |
| `MembraneCandidate.kind='task_promote'` | task-related `promote_to_plan` packet under task visibility rules |
| `ScrimmageRow.outcome='converged'` | `crystallize_decision` candidate |
| `HandoffRow.status='draft'` | `handoff` |
| `MeetingTranscriptRow.extracted_signals[*]` | `meeting_metabolism` child packet |
| review artifact + reviewer target | `review` with derived mode |

Review mode derivation:

| Evidence/artifact | Mode |
|---|---|
| git diff, PR, commit, test run | `code` |
| image, Figma, UI URL, screenshot, visual route | `design` |
| policy, legal, privacy, platform rule, budget approval | `compliance` |
| release checklist, build, store submission, go/no-go | `launch` |

The Edge agent may continue to emit its existing structured outputs: answers, clarifications, tool calls, route proposals, and cited claims. Flow projection reads those outputs after persistence.

Backend validation rules:

- Agents may not invent user ids; backend filters against project membership.
- Agents may not mark a flow completed.
- Agents may not declare a shared-memory write safe without Membrane review.
- All claims in flow summaries should carry citations where possible.

Deferred optional envelope:

If later needed, the Edge agent may emit lightweight hints, not recipe ids:

```json
{
  "workflow_hint": {
    "intent": "Get Raj's design judgment on permadeath",
    "evidence_refs": [
      {"kind": "kb", "id": "...", "label": "Wave A playtest"}
    ]
  }
}
```

The backend still derives the recipe.

---

## 14. Learning Loop

Every completed Flow Packet should update profile and routing hints.

Signals to record:

- route accepted/countered/delegated/gated
- target response latency
- target confidence
- source satisfaction
- evidence quality
- whether the packet produced downstream citations
- whether a decision outcome was later supported/refuted

Profile updates should be batched by a scheduled job, not written synchronously on every packet action. Immediate updates would make every reply path heavier and may burn LLM cost at exactly the wrong moment.

This is where GraphFlow can go beyond gstack. gstack learns project preferences for an agent-assisted builder. GraphFlow learns actual production relationships among humans.

---

## 15. Risk Register

| Risk | Why it matters | Mitigation |
|---|---|---|
| Flow UI becomes a task manager | Violates stream-first thesis | Keep drawer/detail as projection; no kanban as primary |
| Agents appear to replace people | Bad positioning | Always frame agents as edge metabolism around human judgment |
| Membrane bypass | Destroys trust | Tests for every recipe's canonical writes |
| Too many packets | Creates notification fatigue | Bucket by "needs me"; summarize waiting flows |
| Slash commands become product | Looks like gstack clone | Use rituals as accelerators, not the main model |
| Flow stage becomes source of truth | Reintroduces `current_stage` smell | Derive from graph rows or cache only |
| Evidence feels bureaucratic | Slows lightweight work | Require evidence only at completion/gate points |
| Privacy leak in pre-answer/scrimmage | Target agent might see too much | Keep license-sliced context per speaker |

---

## 16. Testing Requirements

Backend invariants:

- Ask With Context cannot route to non-members.
- Pre-answer is visible to sender only.
- Target reply cannot be submitted by non-target user.
- Source-side accept/counter/escalate_to_gate works symmetrically.
- Target-side `delegate_up` and source-side `escalate_to_gate` are distinct actions.
- Promote To Team Memory cannot publish group KB without Membrane outcome.
- Crystallize Decision respects `scope_stream_id`.
- Review completion requires mode-specific evidence plus human sign-off or explicit dismissal.
- Handoff finalize remains owner-only.
- Meeting extracted signals are proposals until accepted.
- Flow projection does not mutate source rows.
- Personal tasks are owner-only until promotion.
- Promoting a personal task calls Membrane `task_promote`.

Frontend tests:

- Active Flows drawer groups `needs_me` vs `waiting_on_others`.
- Inbound cards render outside personal stream.
- Flow detail timeline deep-links to source rows.
- Membrane pending packet opens the existing review surface.
- Completing a packet updates badges without duplicating stream cards.

Observability:

- every packet projection includes trace ids when available
- agent runs referenced in evidence
- action failures return domain error codes, not generic 500s

---

## 17. Implementation Plan

### Slice A: Projection Read Model

- Add backend flow projection service.
- Derive route packets from `RoutedSignalRow`.
- Derive KB review packets from draft `KbItemRow` + `IMSuggestionRow`.
- Derive handoff packets from `HandoffRow`.
- Add `GET /api/projects/{id}/flows`.
- Add tests for projection shape.

### Slice B: Active Flows Drawer

- Add `Flow` drawer or workbench panel.
- Show grouped active packets.
- Deep-link existing surfaces.
- No mutation yet except "open".

### Slice C: Action Router

- Add `POST /flows/{id}/actions`.
- Implement only route reply/source accept symmetry first.
- Implement `FlowActionService` with an explicit dispatch table.
- Delegate to existing `RoutingService` and personal reply handling.
- Keep the HTTP router thin.

### Slice D: Evidence Packet

- Attach citations, source messages, agent run refs.
- Render evidence on flow detail.
- Add "completion requires evidence/gate" assertions.

### Slice E: Recipe Expansion

- Add Review recipe with `code | design | compliance | launch` modes.
- Add Meeting Metabolism recipe.
- Expand rituals menu only after backend projection can show resulting packets.

### Slice F: Snapshot Table, If Needed

- Add `FlowPacketRow` only if list/detail projections become slow or unstable.
- Keep source rows authoritative.

---

## 18. Demo Impact

This gives the demo a sharper story:

```text
gstack proves one person can ship through agent rituals.
GraphFlow proves a real team can coordinate through AI-metabolized edges.
```

The visible product moment:

1. Maya asks a question.
2. GraphFlow creates an Ask With Context packet.
3. Raj's agent pre-answers before Raj is interrupted.
4. Raj sees a rich option card.
5. Maya receives a framed reply.
6. Accepting it creates a Decision packet.
7. Membrane/vote gates it.
8. The graph shows the full lineage.

That is the new AI-native workflow: not tasks assigned to agents, but tasks flowing between humans with agents on every edge.

---

## 19. Open Questions

1. Detail route timing: drawer ships in v1; detail route ships in v1.5 once projection exists.
2. SLA timing: no SLA day one. Add only after stuck packets are visible in dogfood.
3. Snapshot timing: projection-only for first demo; snapshot before compliance-adjacent customers.
4. Profile update timing: batched scheduled job, not immediate per packet.
5. Review evidence depth: mode-specific evidence is the carrier; tune after first code/design/compliance/launch examples.
