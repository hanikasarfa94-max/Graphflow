# GraphFlow Product Design Specification

This document describes the design direction for the `graphflow_design_prototype`.
It is a product and interaction specification, not a production migration plan.
When moving ideas into the real app, `docs/north-star.md` and `DESIGN.md` remain
canonical.

This document is a reference direction, not a committed roadmap. The first
production slices should be small and reversible. In particular, do not use this
prototype to justify a nav expansion, shell rewrite, or broad palette migration.

For a file-by-file implementation path against the current Next.js frontend, see
`frontend-modification-plan.md`.

## 0. Product thesis

GraphFlow is not a messaging app, a task manager, a dashboard, or a knowledge
base. It is an AI-native operating surface for governed organizational state.

The user-facing entry should feel like a calm AI workbench connected to shared
graph state:

```text
personal thought / messy signal
  -> AI interpretation
  -> routed question / draft / proposal
  -> membrane review when needed
  -> accepted-for-scope organizational state
  -> proof, lineage, and downstream action
```

The core object is not a message, task, document, or decision in isolation. The
core object is a governed transition:

```text
source_state -> target_state
```

Examples:

```text
private_ai_turn -> personal_draft
private_ai_turn -> route_suggestion
discussion -> routed_question
discussion -> decision_candidate
decision_candidate -> accepted_for_scope_decision
draft_memory -> review_pending_memory
review_pending_memory -> canonical_world_memory
personal_task_draft -> plan_task_candidate
plan_task_candidate -> plan_task_canonical
capability_claim -> validated_capability
risk_signal -> accepted_risk
```

The same state can be projected through several surfaces: AI workbench, project
stream, active transitions, membrane review, world memory, org graph, work graph,
and universal proof page. These are projections of one system, not separate
products.

## 1. Design principles

### 1.1 AI workbench first, dashboard later

The first screen should not be a kanban board or metrics dashboard. It should be
the place where a user starts by asking, thinking, continuing, or turning a messy
signal into a governed transition.

Kanban-style views may exist later inside Work Graph or audit/detail routes, but
they should not define the product's first impression.

The workbench must stay group-scoped by default. It is not "my private copilot
homepage"; it is the user's local interface to a selected project, room, or group
graph. Private thinking is a mode inside that relationship, not the product's
center of gravity.

### 1.2 Conversation is the entry; graph state is the product

The center of the experience is a conversational workbench. Around it, a small
number of lightweight context hints expose the current organizational state:

- what needs the user's judgement
- what is moving between people
- what is waiting at Membrane
- what changed since the user left
- what memory, risks, or collaborators are relevant before sending

These hints should help the user ask a better question, not become a dashboard.
If the page needs more than one compact hint group on first paint, it is probably
drifting back toward a dashboard.

### 1.3 Pre-send context matters

The most AI-native moment is before the user sends. As the user drafts a question
or selects a page object, GraphFlow should surface relevant memory, risks,
people, and possible transition actions.

Example:

```text
Draft: "Is the 8 levels + 3 bosses goal too aggressive?"

Pre-send context:
- Relevant memory: Launch scope says 8 levels + 3 bosses.
- Risk: Switch performance budget is constrained.
- Suggested collaborator: Aiko has validated performance evidence.
- Possible transition: unknown feasibility -> expert-judged constraint.
```

### 1.4 Private reasoning before organizational reality

Personal AI conversation is useful, but private by default. It becomes
organizational reality only through explicit submission and, where needed,
Membrane review.

```text
private_ai_turn
  -> personal_draft
  -> proposal_candidate
  -> project_stream / membrane_review
  -> accepted_for_scope object
```

### 1.5 Routing is not notification

Routing is not "send this message to someone." Routing is context
transformation: the system frames a question, carries compressed evidence,
chooses a target with a reason, asks for a specific judgement, and reconnects
the reply to the graph.

Users may trigger routing manually, but the product should present it as a Flow
Packet / transition, not a chat phrase.

### 1.6 Traceability everywhere

Every important object exposes a visible trust contract:

```text
What is it?
Where did it come from?
What scope accepts it?
Who has authority?
What state does it change?
What evidence supports it?
What can happen next?
What lineage did it produce?
```

Use "accepted-for-scope" or "scoped canonicality" in v1. Do not claim formal
common knowledge in the UI.

## 2. Visual system

The prototype may explore interaction structure, but production visual language
must be translated into the real app's `DESIGN.md` system.

### 2.1 Production visual direction

Production GraphFlow should feel like:

```text
blueprint instrument + calm AI workbench + graph-native proof system
```

Use the real WorkGraph design tokens:

- background: `--wg-paper`
- surface: `--wg-surface`
- sunk surface: `--wg-surface-sunk`
- border: `--wg-line`
- primary/action/crystallization: `--wg-accent`
- attention/review: `--wg-amber`
- accepted/supported: `--wg-ok`
- danger/conflict: `--wg-danger`

Do not copy prototype-only hex colors directly into production. No inline hex
literals and no inline `style={{}}` blocks in production components.

### 2.2 Feel

The interface should not feel like consumer chat, enterprise admin, or AI-purple
copilot chrome. It should feel precise, quiet, and observant.

The main visual grammar is not "card dashboard"; it is:

- signal
- state
- boundary
- evidence
- scope
- transition
- proof

### 2.3 Core components

Production components should map to existing UI primitives where possible.

Core product primitives:

- `AIWorkbenchSurface`
- `AskGraphFlowComposer`
- `EntryHintCard`
- `PreSendContextRail`
- `FlowPacketCard`
- `MembraneGateCard`
- `EvidenceStack`
- `EvidenceChip`
- `ScopeBadge`
- `StateRibbon`
- `TrustContractPanel`
- `ObjectProofPage`
- `GraphSliceCanvas`
- `FloatingAssistantPatch`

## 3. Navigation model

Avoid nav explosion. The prototype may show many conceptual projections, but the
main product should feel like one AI workbench connected to graph state.

Recommended primary navigation:

```text
Home / Workbench
Project Stream
Transitions
Review
World Memory
Org Graph
Work Graph
Docs
Settings
```

Rules:

- `Home / Workbench` is the AI-first entry surface.
- `My AI Studio` should not be a separate primary nav item in v1 if Home already
  contains private AI work. It can become a mode or section inside Workbench.
- `Node Detail` should not be a nav item. It is reached from citations, evidence,
  graph nodes, and transition rows.
- `Graph` should not stay generic. Split intent into `Org Graph`, `Work Graph`,
  and audit/proof graph projections.
- Kanban/table views belong behind Work Graph or detail/audit routes, not the
  first screen.

## 4. Page designs

## 4.1 Home / AI Workbench

### Purpose

The first work interface. It answers:

```text
What can I ask GraphFlow now?
What changed while I was away?
What needs my judgement?
What is the next useful transition?
```

It is not a dashboard and not a kanban board.

### Layout

Use a three-zone layout only when the right rail has real contextual substance.
For early production slices, a simpler two-zone or centered layout is acceptable:

```text
left nav | central AI workbench | optional compact context rail
```

The center is the main object. The rail and hints support the conversation. Do
not let rail cards or metrics compete with the composer.

### A. Lightweight entry hint group

Place one small group above or beside the central workbench. These are not
metrics cards; they are entry hints derived from graph-state transitions.

Possible hint types inside the group:

- `Needs your judgement`
- `Routes in motion`
- `Waiting at Membrane`
- `Since you left`

Do not show all four as separate first-paint modules unless real dogfood proves
the page still feels calm. The default should be one combined group with one or
two examples. Avoid charts, tables, trend graphs, and operational KPI widgets.

### B. Central greeting and prompt starters

When there is no active conversation, show:

- a calm GraphFlow greeting
- current project or workspace context
- one line of recap
- 3 to 5 prompt starters
- a prominent composer

Example prompt starters:

```text
Summarize what changed since I left
What needs my judgement today?
Ask the right teammate about this risk
Turn this into a review candidate
Find the evidence chain behind this decision
```

### C. Optional quick memory and suggested transitions

Below or near the greeting, optionally show one quiet support block:

- `Quick memory recall`: relevant accepted memory and recent changes, or
- `Suggested next transitions`: not generic actions, but state changes.

Do not ship both as separate modules in the first slice unless the page still
feels sparse.

Example:

```text
unknown performance feasibility -> ask Aiko
draft memory -> submit to Membrane
discussion -> scope decision candidate
risk signal -> route to owner
```

### D. Ask GraphFlow composer

The composer is the main interaction:

- wide, stable, visually central
- accepts natural language
- supports object references and attachments
- can show mode/scope only when useful
- includes quick chips as prompts, not a fixed command menu

The composer should be able to generate:

- direct AI answer
- private draft
- project stream turn
- route suggestion
- memory candidate
- decision candidate
- task transition candidate

### E. Pre-send context rail

The right rail should be pre-send aware. Before the message is sent, it should
react to draft text or selected objects.

Possible modules:

- `Current scope`: project, room, or private scope.
- `Relevant memory`: canonical or accepted-for-scope items.
- `Risks / constraints`: important blockers related to the draft.
- `Suggested collaborators`: people with routing evidence.
- `Possible transition`: what state change this turn might produce.

This is where GraphFlow should feel different from a generic chat app.

This rail should not ship as a purely decorative shell. If the backend preview
does not provide real memory / risk / collaborator / transition fields, keep the
rail minimal or defer it. A fancy scope label that flickers on every keystroke is
worse than no rail.

### Main transitions

```text
Ask GraphFlow -> answer in Workbench
Ask GraphFlow with project context -> Project Stream turn or route proposal
Needs your judgement -> Review / Transitions / source stream
Route in motion -> Transition detail
Waiting at Membrane -> Review
Memory hint -> World Memory / Proof Page
Suggested collaborator -> route proposal
```

## 4.2 Project Stream

### Purpose

The main project collaboration surface. It is not Slack with AI added. It is a
timeline where conversation, AI interpretation, routing, membrane candidates, and
crystallizations coexist.

### Content

- Project header with current scope.
- Human turns.
- Project assistant turns.
- Routed question cards.
- Decision crystallization cards.
- Memory proposal cards.
- Task transition cards.
- Composer.
- Compact right context rail for active transitions, related memory, suggested
  people, and current scope.

### Design notes

Stream items should show how "talk" becomes organizational state:

```text
raw message -> AI interpretation -> candidate transition -> accepted object
```

Agent replies should put judgement in the body and evidence below. Citations are
evidence, not the answer itself.

### Main transitions

```text
Routed question card -> Transition detail
Decision card -> Proof Page
Memory proposal -> Review or World Memory
Task transition -> Work Graph
Evidence chip -> Proof Page or source location
```

## 4.3 Private AI mode

### Purpose

Private reasoning before organizational reality. This can be a mode inside Home /
Workbench rather than a separate top-level page.

### Content

- private conversation
- saved drafts
- referenced graph objects
- generated candidates
- "send to project" / "submit for review" / "route to teammate" actions

Default actions under AI output:

```text
Save draft
Send to Project Stream
Generate candidate
How would the team think about this?
```

Advanced candidate types:

```text
reply draft
decision candidate
memory candidate
personal task draft
route suggestion
```

### Main transitions

```text
AI answer -> private draft
AI answer -> Project Stream post
AI answer -> Flow Packet candidate
Route suggestion -> Transitions
Candidate -> Review
Personal task draft -> Work Graph
Referenced object -> Proof Page
```

## 4.4 Transitions

### Purpose

The active state-change surface. It is not a todo list.

### Content

- filters: status, authority, scope, project, kind
- buckets: needs me, waiting on others, awaiting membrane, recently completed
- transition rows
- selected packet detail rail
- expandable evidence and lifecycle panel

### Required row contract

```text
source_state -> target_state
title
requester
current_authority
evidence_count
visibility_scope
status
next_action
```

### Main transitions

```text
Flow Packet row -> transition detail / Proof Page
Awaiting Membrane -> Review
Evidence ref -> Proof Page
Requester/project -> Project Stream
Completed transition -> downstream object detail
```

## 4.5 Review / Membrane Bench

### Purpose

Trust boundary for shared state. This is not an inbox and not ordinary approval
software. It is the legalizing layer for organizational cognitive updates.

### Content

- pending candidates
- high-impact candidates
- duplicate / stale / conflict warnings
- authority required
- evidence refs
- source -> target transition
- update effects
- review actions
- rationale notes

### Actions

```text
Accept
Reject / dismiss
Request clarification
Counter / revise
Archive / supersede
```

### Main transitions

```text
Accept memory -> World Memory / Proof Page
Accept decision -> Proof Page
Accept task transition -> Work Graph / Transitions
Request clarification -> routed question / Transition
Reject -> audit trail
Open source discussion -> Project Stream
Open evidence -> Proof Page
```

## 4.6 World Memory

### Purpose

The team's accepted world model. It answers: what does the team currently accept
as true in this scope?

### Content

- status filters: canonical, draft, review pending, contested, superseded,
  archived
- memory object list
- scope, status, accepted by, evidence refs, last updated, citation count
- memory detail panel
- lineage graph
- floating assistant patch action

### Design notes

World Memory should not feel like a file browser. Primary grammar is epistemic
status and evidence, not folder location.

### Floating assistant edit flow

When a user selects text or an object in World Memory, a floating assistant can
help produce a patch. The assistant should not silently mutate canonical memory.

```text
selected memory text
  -> assistant suggests patch
  -> preview diff
  -> user proposes
  -> Membrane review if semantic
  -> domain service mutates on accept
  -> lineage output recorded
```

Patch candidate fields:

```text
old_text
new_text
reason
evidence_refs
supersedes
scope
membrane_policy
update_effects
```

Type-1 prose polish may save as a rendering override. Semantic change, reversal,
new fact, or structural change must pass through Membrane.

### Main transitions

```text
Memory object -> Proof Page
Cited decision -> Proof Page
Source ref -> Project Stream or source evidence
Lineage -> older/newer memory node
Review pending -> Review
Assistant patch -> Membrane candidate
```

## 4.7 Org Graph

### Purpose

Routing evidence and responsibility topology. It answers: who can judge what, and
why does the system believe that?

### Content

- members
- capability claims
- authority scopes
- declared / role / observed / validated / trusted abilities
- evidence refs from route replies, tasks, and decisions
- routing history
- recommended route candidates

### Design notes

Avoid HR scoring aesthetics. This is not a performance dashboard. It is
route-grounding evidence and responsibility topology.

### Main transitions

```text
Person node -> member detail
Capability evidence -> Proof Page
Routing history -> Transitions
Linked task/decision -> Proof Page
Project scope -> Project Stream
```

## 4.8 Work Graph

### Purpose

Governed execution state. It answers: what are we moving from unfinished into
accepted, done, or blocked?

### Content

- task transition objects
- personal tasks
- plan tasks
- blocked tasks
- recently completed tasks
- task detail panel
- dependency and impact graph

### Design notes

Do not present tasks as ordinary checkboxes. A task is a governed state
transition. Every task row should expose state transition, owner, evidence,
blockers, due date, completion criteria, linked decisions / memory / risks, and
next action.

### Main transitions

```text
Task transition -> detail panel / Proof Page
Linked decision -> Proof Page
Blocker/risk -> source evidence / risk detail
Promote to plan -> Review or authority flow
Owner -> Org Graph
```

## 4.9 Universal Proof Page

### Purpose

The proof page for any graph object. It answers: why should I trust this?

This is the highest-ROI page to extract from the prototype into production before
any large visual redesign.

### Content

- object type
- title
- current status
- accepted scope
- source state -> target state
- visibility
- evidence refs
- authority / accepted by
- review method
- mutation service / how changed
- lineage
- downstream affected objects
- timeline
- available actions
- right trust contract rail

### Main transitions

```text
Evidence ref -> source discussion / Project Stream
Accepted by -> Org Graph
Downstream object -> Work Graph or World Memory
Lineage node -> earlier/later Proof Page
Visibility scope -> scope explanation
```

## 5. Graph visualization strategy

Ideal graph screenshots are easy to draw and hard to implement. Do not begin with
a full-project force-directed "universe graph" as the primary surface.

Use three implementable graph types.

### 5.1 Proof Graph

A small graph centered on one object. This is the most practical v1 graph.

```text
source message -> route -> expert reply -> candidate
                                      -> membrane
                                      -> canonical object
                                      -> downstream objects
```

Implementation:

- fixed lanes, not free force layout
- default 1-hop lineage path
- expandable evidence groups
- stable node positions for demo and comprehension
- React Flow is suitable

### 5.2 Transition Graph

A flow-state graph for active transitions.

```text
unknown -> asked -> replied -> accepted
draft -> review_pending -> canonical
personal_task -> plan_candidate -> plan_task
```

Implementation:

- lanes by `source_state` / `target_state`
- active and recent transitions only
- no full historical graph by default
- rows and graph share the same selected packet

### 5.3 World / Org / Work layered graph

A three-band graph for cross-domain relationships:

```text
World Graph: memory / decision / risk / constraint
Org Graph:   member / capability / responsibility / authority
Work Graph:  task / route / review / handoff / outcome
```

Implementation:

- horizontal bands
- cross-band edges only for selected nodes
- hide unrelated edges until expansion
- no force layout as default
- use collapsed counts for hidden neighbors

### 5.4 GraphSlice contract

The backend should return graph slices, not the full project graph.

```ts
export interface GraphSlice {
  center: ObjectRef;
  nodes: GraphNode[];
  edges: GraphEdge[];
  lanes?: Array<'source' | 'candidate' | 'membrane' | 'canonical' | 'downstream'>;
  bands?: Array<'world' | 'org' | 'work'>;
  hiddenCounts?: Record<string, number>;
}
```

## 6. API contract notes

The prototype uses static mock data. A real integration should use the existing
backend contracts where possible:

- `GET /api/projects/{project_id}/flows`
- flow packet `transition_contract`
- flow packet `epistemic_event`
- participants sidecar
- evidence refs
- review / membrane suggestion surfaces
- project streams
- KB / decision / task canonical row families

Prototype names below are conceptual. Do not create parallel API families when
existing endpoints already express the same thing.

### 6.1 Object kind and status separation

Do not collapse event kind and epistemic status into one enum.

```ts
export type EpistemicEventKind =
  | 'question'
  | 'claim'
  | 'proposal'
  | 'decision'
  | 'memory'
  | 'task_transition'
  | 'capability_claim'
  | 'handoff';

export type EpistemicStatus =
  | 'private'
  | 'draft'
  | 'hypothesis'
  | 'proposed'
  | 'review_pending'
  | 'accepted_for_scope'
  | 'canonical'
  | 'validated'
  | 'superseded'
  | 'archived'
  | 'rejected';
```

### 6.2 EvidenceRef

```ts
export interface EvidenceRef {
  id: string;
  kind: string;
  title: string;
  href?: string;
  excerpt?: string;
  createdAt?: string;
  confidence?: number;
}
```

### 6.3 TrustContract

`TrustContract` is a user-facing vocabulary that can be built from the existing
`transition_contract`, `epistemic_event`, and evidence refs.

```ts
export interface TrustContract {
  objectId: string;
  objectKind: string;
  eventKind: EpistemicEventKind;
  status: EpistemicStatus;
  visibilityScope: string;
  acceptedScope?: {
    scopeType: 'private' | 'room' | 'project' | 'org';
    scopeId: string;
    acceptedByUserIds: string[];
    acceptedAt?: string;
  };
  authorityRequired: string[];
  sourceState?: string;
  targetState?: string;
  evidenceRefs: EvidenceRef[];
  reviewMethod?: string;
  mutationService?: string;
  lineageOutput: EvidenceRef[];
  supersedes: string[];
  updateEffects: string[];
}
```

### 6.4 Flow Packet

```ts
export interface FlowPacket {
  id: string;
  title: string;
  recipeId: string;
  status: 'active' | 'awaiting_authority' | 'completed' | 'cancelled';
  bucket?: 'needs_me' | 'waiting_on_others' | 'awaiting_membrane';
  transitionContract: TrustContract;
  evidenceRefs: EvidenceRef[];
  nextActions: Array<{
    kind: string;
    label: string;
    href?: string;
    requiresFraming?: boolean;
  }>;
  createdAt: string;
  updatedAt: string;
}
```

### 6.5 Workbench context

The AI-first Home needs a lightweight aggregation endpoint or adapter. It should
not require a new dashboard model; it can compose existing flows, streams, memory,
and routing data.

```ts
export interface WorkbenchContext {
  viewerId: string;
  currentScope: {
    type: 'project' | 'room' | 'private';
    id: string;
    label: string;
  };
  entryHints: Array<{
    kind: 'needs_judgement' | 'routes_in_motion' | 'waiting_at_membrane' | 'since_you_left';
    count: number;
    examples: EvidenceRef[];
  }>;
  recentMemoryUpdates: EvidenceRef[];
  suggestedCollaborators: Array<{
    userId: string;
    displayName: string;
    reason: string;
    evidenceRefs: EvidenceRef[];
  }>;
}
```

### 6.6 Floating assistant patch

```ts
export interface AssistantPatchCandidate {
  id: string;
  targetObjectId: string;
  targetObjectKind: string;
  oldText?: string;
  newText: string;
  reason: string;
  evidenceRefs: EvidenceRef[];
  supersedes: string[];
  scope: string;
  membranePolicy: 'none' | 'auto_merge' | 'request_review' | 'request_clarification' | 'reject';
  updateEffects: string[];
}
```

## 7. Integration recommendations

1. Keep the existing route/layout system. Integrate ideas from this prototype as
   a design layer, not a parallel application shell.
2. Start by prototyping the AI-first Home / Workbench with static data.
3. Do not launch a full nav redesign until the Workbench interaction feels right.
4. Do not copy the prototype palette into production; translate to `DESIGN.md`
   tokens.
5. Treat `TrustContract` as a user-facing vocabulary over existing
   `transition_contract` and `epistemic_event`.
6. Build the Universal Proof Page before broad visual migration.
7. Keep graph visualizations as bounded graph slices, not a full force-directed
   project universe.
8. Route suggestions should stay structured Flow Packets, not ordinary chat text.
9. Project Stream should render structured cards from graph objects rather than
   parsing message text.
10. Floating AI edits must become patch candidates; semantic edits never silently
    mutate shared state.
11. Every citation chip should resolve to a source object or Proof Page.
12. Prompt rules do not count as product invariants unless enforced by services,
    state machines, or tests.

## 8. One-line agent brief

Design GraphFlow's home page as an AI-first entry surface, not a dashboard.
The center of the page is a conversational workbench with greeting, prompt
starters, pre-send context, and a prominent Ask GraphFlow composer. Around it,
show only lightweight graph-state entry hints: what needs judgement, what is
moving between people, what is waiting at Membrane, and what changed since the
user left. Avoid kanban, BI charts, dense metrics, and nav expansion. The page
should make users feel that they are speaking to shared governed graph state, not
opening another task management suite.
