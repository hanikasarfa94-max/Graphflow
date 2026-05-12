# GraphFlow Frontend Modification Plan

This plan translates the AI-first design direction in `design.md` into concrete
frontend work based on the current `apps/web` codebase.

It intentionally does not propose a wholesale UI rewrite. The real frontend
already contains useful pieces: personal streams, pre-commit rehearsal, active
flows, project module rail, review routes, KB pages, and a node detail route.
The goal is to rearrange and strengthen those pieces so the product feels like an
AI-native workbench over shared governed graph state.

This is a reference plan, not the active roadmap. Treat each phase as a candidate
slice that must compete with demo cleanup, Membrane correctness, task flow, and
other backend trust work.

Hard constraints before any UX slice:

- Target the current production shell. Do not revive the dormant v-Next shell and
  do not introduce a third shell path.
- Preserve the group-subject positioning. A workbench is group/project/room
  scoped by default, not an individual copilot homepage.
- Keep callable rituals as power-user shortcuts inside the composer. They are not
  the primary UX, but they should not be removed or renamed during the redesign.
- Do not add parallel API families for concepts already represented by existing
  state, flows, KB, routing, or review endpoints.
- Do not let the first Home slice become a six-module dashboard.

## 0.1 Safe experimentation model

The UI redesign can land experimentally if it is protected by reversible
boundaries. The goal is to learn from real product use without breaking the demo
path or erasing the current shell.

### Guardrails

1. **Feature flag first**

   Ship new UX surfaces behind a single flag:

   ```text
   NEXT_PUBLIC_GRAPHFLOW_UX_EXPERIMENT=true
   ```

   or a server-side user/project allowlist. Default off in production until the
   user explicitly enables dogfood.

2. **Shadow route before replacement**

   Do not replace `/` or `/projects/[id]` on the first pass. Add experimental
   routes:

   ```text
   /workbench
   /projects/[id]/workbench
   /projects/[id]/transitions
   ```

   Keep current routes untouched. Once the new surface proves better, make the
   old route redirect or swap the default behind the flag.

3. **Read-only before mutation**

   New visual surfaces should first read existing data and deep-link to existing
   mutation surfaces. Mutation buttons can come later. This prevents a visual
   experiment from accidentally changing Membrane, routing, task, or KB behavior.

4. **Adapter layer, not API fork**

   New frontend features can define view models, but they should adapt from
   existing clients/endpoints first:

   ```text
   HomeData -> WorkbenchViewModel
   FlowPacket -> TransitionViewModel
   ProjectState/KB fetch -> ProofViewModel
   ```

   Add backend endpoints only after the view layer proves the shape and exposes
   real duplication.

5. **No shell fork**

   Use the current production shell and `ProjectModuleRail`. Do not revive v-Next
   and do not introduce another global shell. Experimental pages can have a local
   layout, but global navigation/auth/topbar behavior stays inherited.

6. **Design guard on every new directory**

   Every new experimental feature directory must be covered by the design-system
   static guard from day one. No new inline `style={{}}`; no new hex literals.

7. **Bilingual copy gate**

   New UI text must land in both `en` and `zh`. Experimental UI often fails by
   shipping good English and rough Chinese; that would hurt GraphFlow's demo
   story.

8. **Demo path must remain stable**

   The current demo path must continue to work:

   ```text
   /projects/[id]
   /projects/[id]/team
   /projects/[id]/detail/im
   /projects/[id]/kb
   /projects/[id]/detail/graph
   /projects/[id]/renders/...
   ```

   Experimental UX may link into these routes; it must not rename or remove them.

9. **One product question per slice**

   Each experiment should answer one question only:

   - Does AI-first Home feel better than dashboard Home?
   - Does Proof Page make trust legible?
   - Does Transitions page make flow feel like circulation?
   - Does pre-send context help the user ask better?

   If a slice answers more than one question, it is too large.

10. **Rollback is a first-class acceptance criterion**

   Every slice report should include:

   ```text
   How to disable it
   Which routes/components are touched
   Which current demo path was regression-tested
   Which tests prove old behavior still works
   ```

### Recommended experiment order

If the user wants to actively explore the new UI direction, use this order:

```text
E1. Shadow Workbench route, read-only, current shell
E2. Proof Page visual upgrade on existing /nodes route
E3. Transitions full route from existing /flows packets
E4. Optional: switch Home default behind flag if E1 feels right
E5. Pre-send context rail only after backend preview data is real
E6. Floating memory assistant only after Membrane audit/semantic review is stable
```

This allows visual learning without destructive iteration.

## 1. Current frontend reality

### 1.1 Routes that already exist

Relevant production routes:

```text
/                                  logged-in home
/projects/[id]                     personal project stream
/projects/[id]/team                team room stream
/projects/[id]/detail/im           review / membrane surface
/projects/[id]/detail/tasks        task audit table
/projects/[id]/detail/graph        graph audit view
/projects/[id]/kb                  world memory tree
/projects/[id]/kb/[itemId]         KB detail
/projects/[id]/nodes/[nodeId]      current node detail / citation landing
/projects/[id]/org                 org page
/projects/[id]/skills              skill/handoff page
/projects/[id]/status              status panels
```

Important implication: the product does not need new conceptual routes before
the first UX pass. It needs better hierarchy and better object vocabulary inside
the routes that already exist.

### 1.2 Existing assets to reuse

Useful components / services already in the frontend:

```text
components/home/data.ts             server-side home aggregation
components/stream/PersonalStream    personal AI stream
components/stream/Composer          composer with preview hook
components/stream/RehearsalPreview  pre-send classification card
components/stream/StreamContextPanel scope toggles for agent context
components/flows/ActiveFlowsButton  entry to flows from legacy toolbar
components/rooms/FlowsPanelBody     bucketed flow projection drawer
features/flows/*                    beginning of flows feature extraction
components/kb/*                     world memory tree/detail/actions
app/projects/[id]/nodes/[nodeId]    current proof-ish page
components/ui/*                     Button/Card/Heading/Text/etc.
lib/flows.ts                        typed FlowPacket client
```

The important product insight is that the "AI-first Workbench" is not a brand
new feature. It is a new composition of these existing pieces.

### 1.3 Current mismatches

The current UI still leaks older product shapes:

- `/` logged-in home is still hero + pulse + needs card + mini graph + projects +
  DMs. It is useful, but it reads as a light dashboard, not an AI workbench.
- `/projects/[id]` is already the personal AI stream, but the page chrome does
  not fully explain "personal interface to shared governed state."
- `StreamContextPanel` is a context selector, but not yet a true pre-send context
  rail that reacts to the draft.
- `RehearsalPreview` already previews answer / clarify / route_proposal, but it
  is a small inline card, not a broader pre-send context system.
- `ActiveFlowsButton` and `FlowsPanelBody` make transitions available, but still
  as a popover/drawer, not as a primary state-transition surface.
- `/projects/[id]/nodes/[nodeId]` exists, but it resolves from `/state` and kind
  switches; it is not yet a unified TrustContract / Proof Page.
- `World Memory` can archive and view KB, but does not yet have a floating
  assistant patch workflow.
- The design-system guard is currently narrow. Many current components still use
  inline styles and some hex literals. New work must not expand that debt.
- Shell state is explicit: the redesign targets the current legacy/production
  shell, because v-Next is not the active surface.
- Slash/callable rituals exist. The redesign should absorb them as composer
  shortcuts and suggestions, not delete them as if they never shipped.

## 2. Target UX structure

The frontend should converge toward four daily surfaces:

```text
Home / Workbench       first AI entry surface
Project Stream         project-scoped conversation and state transition stream
Transitions            active/recent governed state changes
Review                 Membrane boundary for shared state
```

Supporting surfaces:

```text
World Memory           accepted world model
Org Graph              responsibility and capability evidence
Work Graph             governed execution state
Proof Page             universal object trust page, reached by citations
Docs                   rendered artifacts
Settings               admin / scope / profile
```

Do not promote every supporting surface to equal visual weight. Daily work should
start in the Workbench or Stream and flow out through links, chips, and cards.

## 3. Recommended phased plan

## Phase UX-A: Home becomes AI-first Workbench

### Goal

Replace the logged-in `/` dashboard feeling with a central AI workbench.

Important: this is a constrained slice. First paint should be greeting +
composer + one compact entry-hint group. Quick memory, suggested transitions, and
right rail are optional follow-ons, not mandatory modules in UX-A.

### Route

```text
apps/web/src/app/page.tsx
```

### New feature home

Create:

```text
apps/web/src/features/workbench/
  components/
    WorkbenchHome.tsx
    WorkbenchGreeting.tsx
    WorkbenchComposer.tsx
    EntryHintCard.tsx
    EntryHints.tsx
    PreSendContextRail.tsx
    QuickMemoryRecall.tsx
    SuggestedTransitionList.tsx
  types.ts
```

Use `components/home/data.ts` as the first data source. Do not invent a new
backend endpoint for UX-A unless the data shape becomes painful.

### What changes

Current:

```text
HomeHero + pulse card
Needs card + mini graph
Approvals
Projects
DMs
```

Target:

```text
central greeting
Ask GraphFlow composer
one compact entry hint group, with at most 1-2 examples from:
  - needs your judgement
  - routes in motion
  - waiting at Membrane
  - since you left
optional quick memory OR suggested transitions, not both in the first slice
optional context rail only when it has real data
projects/DMs demoted below the fold or behind "Browse"
```

### Data mapping

Reuse existing fields:

```text
HomeData.pending                 -> Needs your judgement
Routing inbox signals            -> Routes in motion / Needs judgement
HomeData.is_admin_anywhere       -> Review entry availability
HomeData.active                  -> Since you left / Continue thread
HomeData.top_project             -> Current scope suggestion
HomeData.projects                -> Browse projects fallback
HomeData.dms                     -> secondary communication, not first screen
```

Potential extra fetch later:

```text
GET /api/projects/{id}/flows?bucket=needs_me
GET /api/projects/{id}/flows?bucket=awaiting_membrane
```

But avoid cross-project N+1 in the first slice. The first Workbench can be
project-biased toward `top_project`.

### Interaction

The Home composer can initially do one of two conservative things:

1. If a top project exists, submit to `/projects/{topProjectId}` personal stream.
2. If no top project exists, ask the user to pick a project.

Do not create a parallel personal-AI backend in UX-A.

The default scope must be explicit: the composer is acting against a selected
project/room/group context. If no scope is available, ask the user to choose one
before sending.

### Design constraints

- Use `components/ui` primitives and CSS modules/classes.
- No new inline `style={{}}`.
- No hex literals.
- Keep `ProjectsSection` and `DMsSection` available but visually demoted.

### Tests

- Server render smoke for logged-in Home.
- i18n keys for new workbench copy.
- Design guard extended to `features/workbench`.

## Phase UX-B: Project stream gets a real pre-send context rail

### Goal

Make `/projects/[id]` feel like "personal interface to shared governed state",
not just a chat page.

This phase is high-cost and should not ship until the preview/backend fields are
real. Without real memory/risk/collaborator/transition data, the rail becomes
decorative chrome and undercuts the AI-native claim.

### Route

```text
apps/web/src/app/projects/[id]/page.tsx
components/stream/PersonalStream.tsx
components/stream/Composer.tsx
components/stream/RehearsalPreview.tsx
components/stream/StreamContextPanel.tsx
```

### New feature home

Create:

```text
apps/web/src/features/project-workbench/
  components/
    ProjectWorkbenchShell.tsx
    ComposerWithContext.tsx
    PreSendContextRail.tsx
    DraftContextSummary.tsx
    SuggestedRouteTarget.tsx
    PossibleTransitionCard.tsx
  api.ts
  types.ts
```

### What changes

Current toolbar actions:

```text
StreamContextPanel
ActiveFlowsButton
```

Target right rail:

```text
Current scope
Relevant memory
Risks / constraints
Suggested collaborators
Possible transition:
  source_state -> target_state
```

This rail should react to draft text. The existing `previewPersonalMessage` /
`RehearsalPreview` path is the first integration point.

### Backend shape needed

The preview endpoint currently returns answer / clarify / route proposal. Extend
it later to include optional context fields:

```ts
type DraftContextPreview = {
  relevant_memory_refs: EvidenceRef[];
  risk_refs: EvidenceRef[];
  suggested_collaborators: Array<{
    user_id: string;
    display_name: string;
    target_reason: string;
    evidence_refs: EvidenceRef[];
  }>;
  possible_transition?: {
    source_state: string;
    target_state: string;
    update_effects: string[];
  };
}
```

Frontend can render the rail conditionally. If the backend does not return these
fields yet, do not ship the full rail. Keep the existing `StreamContextPanel` and
`RehearsalPreview` as the honest v1 surface.

### Important constraint

Do not make the rail feel like a static settings panel. It should be "what the
system knows before I send this".

### Tests

- Composer still sends with existing body path.
- Preview state does not block sending.
- Context rail renders empty state without backend additions.
- Chinese and English copy both present.

## Phase UX-C: Active Flows becomes Transitions surface, not only a popover

### Goal

Preserve the useful popover, but add a real route for active/recent transitions.

### New route

Recommended:

```text
/projects/[id]/transitions
```

Do not remove `ActiveFlowsButton`. It remains a lightweight entry point.

### New feature home

Continue extracting from:

```text
components/rooms/FlowsPanelBody.tsx
features/flows/components/FlowPacketRow.tsx
```

Target:

```text
apps/web/src/features/flows/
  api.ts                 move listFlows/postFlowAction from lib/flows.ts later
  components/
    FlowBucketColumn.tsx
    FlowPacketRow.tsx
    FlowPacketDetailRail.tsx
    FlowEvidenceStack.tsx
    FlowActionBar.tsx
    FlowFilters.tsx
```

### What changes

Current:

```text
compact bucket popover
row chips
Open / Accept / More
Evidence toggle
```

Target route:

```text
left: buckets / filters
center: transition rows
right: selected transition contract
```

Required row display:

```text
source_state -> target_state
title
authority
status
scope
evidence count
next action
```

### Immediate cleanup inside current code

- Replace hardcoded `"1 actor" / "X actors"` in `FlowPacketRow` with i18n.
- Move `FlowRowActions` and `EvidenceBlock` out of `components/rooms` into
  `features/flows` to remove the back-import.
- Remove fallback hex from `bucketHeaderStyle`:

```text
borderBottom: "1px solid var(--wg-line-faint, #f0f0f0)"
```

or define `--wg-line-faint` globally.

### Tests

- Existing flows tests.
- Route rendering test for `/projects/[id]/transitions`.
- Action refresh still works from both popover and route.

## Phase UX-D: Universal Proof Page v1

### Goal

Turn `/projects/[id]/nodes/[nodeId]` from a kind-specific resolver into a
TrustContract page.

### Current state

`app/projects/[id]/nodes/[nodeId]/page.tsx` already exists. It fetches
`/api/projects/{id}/state`, resolves tasks/decisions/risks/etc. locally, and
redirects KB ids to `/kb/{itemId}`.

This is proof-like but not universal.

### Target

First target: view-layer over the existing resolver and `/state` payload.

```text
app/projects/[id]/nodes/[nodeId]/page.tsx
```

Do not add a new backend resource in the first Proof Page slice. A new resolver
endpoint is allowed only after the view-layer proves the TrustContract shape and
the duplication cost is clear.

Possible later endpoint:

```text
GET /api/projects/{project_id}/nodes/{object_id}
```

Return:

```ts
type ProofNodeResponse = {
  object: {
    id: string;
    kind: string;
    title: string;
    body?: string;
    status: string;
  };
  trust_contract: TrustContract;
  evidence_refs: EvidenceRef[];
  lineage: EvidenceRef[];
  downstream: EvidenceRef[];
  timeline: Array<{
    at: string;
    actor_id?: string;
    action: string;
    refs: EvidenceRef[];
  }>;
};
```

### Frontend components

```text
apps/web/src/features/proof/
  components/
    ProofPage.tsx
    TrustContractRail.tsx
    EvidenceStack.tsx
    LineagePath.tsx
    ProofTimeline.tsx
    ScopeSummary.tsx
  api.ts
  types.ts
```

### Migration

- Keep old local resolver as fallback while endpoint matures.
- Evidence chips can gradually point to proof page.
- KB detail can stay canonical for reading/editing; proof page is for trust.
- In the first slice, prefer local mapping from existing `ProjectState`,
  `FlowPacket`, and KB fetches over a new API family.

### Tests

- Unknown object -> notFound.
- KB id handled.
- Decision id shows accepted scope / authority / lineage.
- Route signal id shows source -> target transition.

## Phase UX-E: World Memory floating assistant patch

### Goal

Let users select or edit memory content with AI help while preserving Membrane as
the boundary.

Defer this phase until the Membrane audit/semantic-review path is stable enough
to absorb another candidate kind. Floating assistant patches are conceptually
right, but they should not race M2 audit or other Membrane hardening work.

### Current state

Relevant files:

```text
components/kb/KbTreeBrowser.tsx
components/kb/KbItemDetail.tsx
components/kb/KbItemActions.tsx
features/kb/api.ts
```

The KB surface can view/archive items, and group writes already pass Membrane.

### New components

```text
apps/web/src/features/kb/components/
  FloatingMemoryAssistant.tsx
  MemoryPatchPreview.tsx
  MemoryPatchDiff.tsx
  SubmitPatchCandidateButton.tsx
```

### Interaction

```text
select text / click "Improve with GraphFlow"
  -> assistant suggests patch
  -> preview old/new diff
  -> user submits
  -> creates memory_patch candidate
  -> Membrane review if semantic
  -> owner accepts
  -> KB row mutates / supersedes / archives
```

### Backend needed

Potential new endpoint:

```text
POST /api/projects/{project_id}/kb/{item_id}/patch-candidates
```

Payload:

```ts
{
  selected_text?: string;
  instruction: string;
  new_text?: string;
  evidence_refs?: EvidenceRef[];
}
```

Response:

```ts
{
  candidate_id: string;
  membrane_action: "auto_merge" | "request_review" | "request_clarification" | "reject";
  review_href?: string;
}
```

### Constraint

Semantic edits must not silently mutate canonical memory.

### Tests

- Patch candidate submit renders review state.
- Archive still works.
- No direct canonical mutation from assistant patch.

## Phase UX-F: Graph visualization v1

### Goal

Implement graph views that are achievable, stable, and useful.

### Do not start with

```text
full-project force-directed universe graph
```

It looks good in sketches but is unreliable for comprehension and demos.

### Start with Proof Graph

Inside Proof Page:

```text
source -> candidate -> membrane -> canonical -> downstream
```

Use fixed lanes. Stable layout. Expand on click.

### Then Transition Graph

Inside Transitions page:

```text
unknown -> asked -> replied -> accepted
draft -> review_pending -> canonical
```

Rows and graph share selected packet state.

### Then layered World/Org/Work graph

Inside audit/detail:

```text
World band
Org band
Work band
```

Only selected-node cross-band edges are shown by default.

### Recommended implementation

- React Flow for proof and transition graph.
- GraphSlice endpoint returns bounded slice, not full project graph.
- Avoid force simulation for primary UX.

## Phase UX-G: Design debt containment

### Goal

Make the redesign sustainable.

### Current issue

Many existing files still use inline styles and hex literals. A static guard
exists but is scoped only to:

```text
components/rooms
components/kb
components/flows
features/flows
```

with many allowlisted legacy violators.

### Policy for new redesign work

Every new feature directory must be added to the guard from day one:

```text
features/workbench
features/project-workbench
features/proof
features/kb/components for new files
```

No new file should use:

```text
style={{
#[0-9a-fA-F]
```

### Practical path

Do not clean the whole frontend at once. Instead:

1. New surfaces are clean.
2. Touched legacy files move styles into CSS modules or design primitives.
3. Allowlist shrinks surface by surface.

## 4. Recommended implementation order

Best order if this is a pure UX exploration track:

```text
1. UX-A Home / Workbench static composition
2. UX-B Project stream pre-send context rail
3. UX-C Transitions route from existing /flows
4. UX-D Universal Proof Page v1
5. UX-E World Memory floating assistant patch
6. UX-F Proof Graph / Transition Graph
7. UX-G broader design-debt cleanup
```

Recommended order for the actual product while trust/backend work is still
active:

```text
1. UX-D Proof Page v1 as a view-layer over existing state, no new API
2. UX-A Home / Workbench constrained to greeting + composer + one hint group
3. UX-C flow cleanup / Transitions route, if Active Flows starts to feel cramped
4. UX-B only after backend preview context is real
5. UX-E only after Membrane audit/semantic review is stable
```

Proof Page gives the fastest reviewer-facing payoff. Workbench gives the biggest
AI-native first-impression payoff.

## 5. One-slice command candidates

### Candidate 1: Home Workbench slice

```text
Implement UX-A: convert logged-in / into an AI-first Workbench using the existing
home data aggregator. Do not add new backend endpoints. Do not change logged-out
public/login behavior. Create apps/web/src/features/workbench with clean
components and add it to the design-system guard. Center the page on a
group-scoped Ask GraphFlow composer, a greeting, and ONE compact entry-hint group
with at most 1-2 examples. Do not ship quick memory, suggested transitions, and a
right rail as separate first-paint modules in this slice. Demote Projects/DMs
below the fold. Use DESIGN.md tokens and UI primitives; no inline style literals
or hex literals. Keep callable rituals as composer shortcuts. Add bilingual i18n
and targeted tests.
```

### Candidate 1-safe: Shadow Workbench experiment

```text
Implement E1: a safe shadow Workbench experiment, not a replacement.

Read docs/north-star.md, DESIGN.md, graphflow_design_prototype/design.md, and
graphflow_design_prototype/frontend-modification-plan.md first.

Goal:
Create an experimental AI-first Workbench route at /workbench using the current
production shell and existing home data. Do not replace / and do not change
/projects/[id]. The page should test the new UX idea safely:
greeting + group/project-scoped Ask GraphFlow composer + one compact entry-hint
group + optional "continue in project" links. No full dashboard, no kanban, no
charts.

Requirements:
- Feature flag or clearly isolated shadow route. Current / remains untouched.
- Read-only first: composer may deep-link into the selected project personal
  stream or prefill a draft if existing plumbing supports it, but do not create a
  new mutation path.
- Reuse components/home/data.ts for data. Do not add backend endpoints.
- Put new code under apps/web/src/features/workbench.
- Add features/workbench to the design-system static guard.
- Use DESIGN.md tokens and UI primitives. No inline style literals; no hex
  literals.
- Bilingual i18n.
- Keep callable rituals as composer hint chips / power-user shortcuts; do not
  remove them.
- Report exactly how to disable/remove the experiment and which existing demo
  routes were regression-checked.

Tests:
- Logged-in / still renders the old home.
- /workbench renders with mocked or real HomeData.
- Design guard covers features/workbench.
- i18n keys exist for en and zh.
```

### Candidate 2: Project pre-send context slice

```text
Implement UX-B: add a pre-send context rail to /projects/[id] personal stream.
Do this only after the backend preview returns real context fields. Reuse the
existing Composer preview/RehearsalPreview path. Render current scope, active
transition hints, relevant memory, suggested collaborators, and possible
transition only from real preview data. Do not ship placeholder-only chrome. Do
not change message send semantics. Put new code under features/project-workbench
and keep it design-guard clean. Add i18n and tests.
```

### Candidate 3: Proof Page slice

```text
Implement UX-D: turn /projects/[id]/nodes/[nodeId] into a Universal Proof Page.
Do not add a new backend resource in the first slice. Build a TrustContract view
layer over the existing /state resolver and KB fallback, returning object-like
view models inside the page. Build features/proof components using DESIGN.md
tokens and no inline styles. Do not add new top-level nav. Update only safe
evidence/citation links. Add frontend render tests and a clear report of which
kinds are fully supported, partially supported, or still aspirational. Propose a
backend resolver endpoint only if the view-layer exposes unavoidable duplication.
```

### Candidate 4: Floating memory assistant slice

```text
Implement UX-E as a guarded prototype: add a FloatingMemoryAssistant to KB detail
that can preview a patch candidate but cannot directly mutate canonical KB. Submit
semantic changes as Membrane candidates. Keep archive and existing KB actions
unchanged. Use features/kb components, no inline style or hex literals, bilingual
i18n, and tests proving no direct canonical mutation path. Do not start this
until Membrane audit / semantic review work is stable enough for a new candidate
kind.
```

## 6. Reviewer-facing framing

After these slices, the frontend story becomes coherent:

```text
Home: talk to shared graph state.
Project Stream: conversation becomes routed/candidate/canonical state.
Transitions: see state changes moving between people and Membrane.
Review: govern what enters shared state.
World Memory: accepted world model, editable only through governed patches.
Proof Page: every object can explain why it should be trusted.
Graph: bounded slices, not decorative network art.
```

This is the AI-native UX shift: not a dashboard, not a suite, not a task board,
but an interface where users speak into governed organizational cognition.
