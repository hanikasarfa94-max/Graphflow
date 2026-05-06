# GraphFlow North Star: Three Graphs and the Membrane

**Status:** draft concept, 2026-05-06. This is a product-shaping note,
not yet a replacement for `docs/north-star.md`.

GraphFlow is an AI-native cooperation platform. Its core is not a chat
room, not a task table, and not a wiki. Its core is a living organization
graph where AI routes signals between humans, carries the right context,
and protects shared memory from pollution.

The product can be understood as three nested graphs:

```text
World Graph -> where we are, what we know, where we are going, why
Org Graph   -> who is here, what they can do, what they are responsible for
Work Graph  -> what is moving, who is waiting, what needs to be done
```

The Membrane protects the reliability of all three. The Router Agent is
the active nerve that moves signals through them. The Edge Agent is the
user-facing interface: every human talks to their own agent, while the
system handles context, routing, review, and crystallization behind the
surface.

## The One True Thing

GraphFlow turns group work into routed, reviewed, graph-backed signals.

Humans do not maintain the graph directly. Humans speak, decide, ask,
answer, accept, reject, counter, and finish work. The system metabolizes
those turns into graph state.

The promise:

```text
Every useful signal gets the right context,
reaches the right human,
passes the right boundary,
and leaves traceable graph state behind.
```

## The Three Graphs

### World Graph

The World Graph is the shared reality of the organization: what the
group knows, what it believes, where it is going, and why. Earlier
drafts called this the "BG Graph" (background graph); we renamed it
because **World** is the term that travels best across English and
Chinese product copy and avoids the implication that this layer is
merely backdrop. It is the shared reality the team operates inside.

It includes:

- KB items and source documents
- decisions and why-chains
- risks, constraints, milestones, events
- rendered documents such as postmortems and handoffs
- lineage from messages, meetings, external signals, and prior decisions

The World Graph answers:

- What do we know?
- Why did we decide this?
- What is canonical, draft, stale, or superseded?
- What background must the LLM carry before answering or routing?

For retrieval, vector search or BM25 can find candidates, but the result
must not be treated as flat text. Once a node is retrieved, the system
should also provide its graph relations: where it came from, what it
cites, what cites it, what it conflicts with, and what it influences.

### Org Graph

The Org Graph is the capability and responsibility map of the group.
It is not an HR directory. It is the operational understanding of who
can think through what, who owns which boundary, and whose judgment has
been validated by prior work.

It includes:

- members and roles
- declared abilities
- observed abilities
- validated and trusted skills
- authority and gatekeeper maps
- handoff routines
- routing history and response profile

The Org Graph answers:

- Who should see this signal?
- Who has the relevant skill, authority, or context?
- Is a person self-declared, observed, validated, or trusted in this area?
- Where is the team weak or over-dependent on one person?

Skill is therefore not a tag. It is a projection over evidence.

```text
declared skill  = what a member says they can do
role skill      = what the seat is responsible for
observed skill  = what the graph has seen them do
validated skill = observed work accepted or reused by others
trusted skill   = repeated validated work with durable graph evidence
```

### Work Graph

The Work Graph is the circulation layer of action: tasks, routing,
commitments, reviews, handoffs, and flows.

It includes:

- personal task drafts
- promoted plan tasks
- routed signals and replies
- Flow Packets
- Membrane review queues
- commitments and active work context
- task dependencies and status transitions

The Work Graph answers:

- What is moving right now?
- Who is waiting on whom?
- What needs review before it becomes group state?
- What work is personal, proposed, canonical, blocked, done, or archived?

The Work Graph is where GraphFlow differs most visibly from old tools:
tasks flow between humans, with agents on every edge.

## Nesting and Feedback

The three graphs are separate lenses, not separate products. They feed
each other continuously.

```text
World -> Org
The group knows Aiko has been involved in Switch performance decisions.
That World context strengthens her capability profile for performance
calls.

Org -> Work
The router chooses Aiko because her observed/trusted skill graph says she
is the right person for a performance feasibility question.

Work -> World
When Aiko replies and Maya accepts, the result can become a decision,
task update, risk update, or KB note with lineage.

Work -> Org
Accepted replies, completed tasks, and cited decisions become evidence
that sharpens the member's observed and trusted capabilities.
```

This feedback loop is the product:

```text
work happens
-> graph records evidence
-> profile and background sharpen
-> future routing improves
-> better routing creates better work
```

## Membrane

The Membrane is the reliability boundary around shared context. It
controls signal-in and signal-out for the three graphs.

It is not just approval UI. It is the protocol that decides whether a
messy signal can become organizational fact.

Membrane protects:

- World reliability: KB notes, decisions, risks, events, and rendered
  facts should not pollute shared memory without review.
- Org reliability: skill and authority claims should not become trusted
  simply because someone typed them.
- Work reliability: personal tasks and proposals should not silently
  become group plan commitments.

Membrane actions stay small:

```text
auto_merge
request_review
request_clarification
reject
```

But the review method can be rich:

- deterministic checks for exact duplicates, numeric conflicts, stale
  state, missing owner, missing scope, or budget overflow
- LLM review for semantic conflict, ambiguity, supersession, and hidden
  assumptions
- graph expansion so the reviewer sees the candidate's likely impact
- routing to human owners when the system cannot decide safely

The invariant:

```text
LLM recommends.
Membrane enforces.
Domain services mutate.
Every accepted mutation leaves lineage.
```

## Router Agent

The Router Agent is the active nerve of the organization. It moves
signals across people and graphs.

It should decide:

- whether the user can be answered directly from World context
- whether a tool call is needed
- whether a human route is needed
- who the right target is, using Org Graph evidence and World context
- what background and tradeoffs the target needs
- what happens when the reply returns

Routing is not notification. Routing is context transformation.

The same signal should look different to source and target:

- Source sees: why this person, what the system will ask, what evidence
  will travel with it.
- Target sees: what decision or judgment is being asked of them, with
  compressed background and options.
- Source receives the reply reframed in their working context.

## Edge Agent

The Edge Agent is the user's interface to the organization graph. It is
not a separate product surface from the group. It is how the user works
with the group through AI.

It should:

- answer from World Graph when possible
- call tools when more graph state is needed
- propose routes when another human's judgment is required
- stage tasks and KB candidates without bypassing Membrane
- be conversational enough to think with the user
- carry citations and evidence so trust is inspectable

The Edge Agent should feel like a collaborator, but its outputs are not
organizational facts until the right graph boundary accepts them.

## Shared Trust Ladder

Every graph needs trust levels. The exact enum can differ by row, but
the product meaning should be shared.

```text
raw/private
-> draft
-> proposed
-> reviewed
-> canonical
-> cited/reused
-> outcome-validated
-> superseded/archived
```

Applied to World:

```text
private note
-> group KB draft
-> Membrane review
-> canonical KB
-> cited by answer/decision
-> validated or superseded by later outcome
```

Applied to Org:

```text
self-declared skill
-> observed work signal
-> accepted contribution
-> repeated cited contribution
-> trusted capability
-> handoff routine / role memory
```

Applied to Work:

```text
personal task
-> promote request
-> Membrane review
-> plan task
-> completed / blocked / cancelled
-> evidence for World and Org graphs
```

Applied to decisions:

```text
discussion
-> suggestion
-> scoped vote / owner acceptance
-> crystallized DecisionRow
-> cited by work and render outputs
-> supported/refuted by outcome
-> superseded by later decision
```

## Product Claims That Must Be True In Code

For competition review, these claims are load-bearing:

- The LLM's context is scoped and retrieval-backed, not arbitrary prompt
  stuffing.
- Retrieved World nodes carry provenance and graph relations.
- Routing suggestions are grounded in evidence, not only role names.
- Membrane blocks or routes uncertain group-context writes before they
  become canonical.
- Personal work can be promoted into group work only through Membrane.
- Accepted work updates future context, routing, and capability
  projections.
- The user interface may be chat-like, but the backend state is graph
  state with lineage.

If a feature is only a prompt rule and not enforced by a service or test,
it is not yet a product invariant.

## Naming

Working names:

- **World Graph**: shared reality, the group's known world and why-chain.
  Renamed from "BG Graph" in the earlier draft.
- **Org Graph**: organization graph, members, roles, capabilities,
  authority, and responsibility.
- **Work Graph**: action graph, tasks, flows, commitments, and routed work.
- **Membrane**: reliability boundary for graph mutation and context flow.
- **Router Agent**: active nerve that moves signals through people and
  graph state.
- **Edge Agent**: user-facing agent interface.

These names should stay plain. They are strong because they describe the
system instead of branding around it.

## Next Specification Work

The next specs should make this doctrine testable:

1. World Graph context contract: what a retrieved node must carry into LLM
   pretext.
2. Org Graph capability contract: how declared, observed, validated, and
   trusted skills are derived.
3. Work Graph promotion contract: how personal tasks become group plan
   tasks through Membrane.
4. Membrane Agent contract across World, Org, and Work: what deterministic
   checks and LLM checks run per candidate kind.
5. Router grounding contract: no discovery route without evidence refs.

This is the bar: GraphFlow should not merely show collaboration. It
should make organizational context governable, routable, and reliable.
## Transition Contracts

GraphFlow does not only store nodes. It governs transitions between
states.

A useful signal may move through several transitions:

```text
private thought
-> routed question
-> expert reply
-> proposed decision
-> Membrane review
-> canonical decision
-> task graph
-> completed work
-> validated memory
```

Each transition declares: source state, target state, required
evidence, authority, review method, mutation service, lineage output,
and an honest implementation status.

Implementation status legend (apply per row):

- **real** — every field is derivable from current code today and the
  test suite proves it.
- **partial** — most fields are derivable but at least one is best-
  effort or not exercised end-to-end. Specific gaps named in the row.
- **aspirational** — concept is in this doc but the corresponding
  flow packet / mutation surface is not yet projected from code.

| Flow | source_state | target_state | required_evidence | authority | review_method | mutation_service | lineage_output | status |
|---|---|---|---|---|---|---|---|---|
| **routed signal (`ask_with_context`)** | `question_unanswered` | `expert_reply_received` → `reply_accepted` | `routing_basis` (from R2) + framing + options + grounding evidence (skills / decisions / tasks the target is close to) | current `target_user_id` (target judges) + project owners (audit) | `routing_reply` | `RoutingService` | `RoutedSignalRow.reply_json` once replied + `routed-reply` message + source-side `edge-reply-frame`; `accept` flips `status='accepted'` | **real** — backend grounding gate + projection; tests cover grounded-vs-rejected dispatch and replied/accepted timeline. |
| **task promote (`promote_task_to_plan`)** | `personal_task_draft` | `plan_task_candidate` (Membrane staged) → `plan_task_canonical` (owner accept flips `TaskRow.scope='plan'`) | `TaskRow` ref + Membrane deterministic warnings + agent semantic-review verdict (M3) + related tasks + recent decisions | project owners gate the IMSuggestion(membrane_review) accept | `membrane_review` (deterministic) + `agent_semantic_review` (M3) | `TaskProgressService` (`POST /api/tasks/{id}/promote`) → `MembraneService.review` → on accept `IMService._apply_proposal` calls `PlanRepository.promote_personal_to_plan` | `IMSuggestionRow.proposal.detail.task_id` (membrane decision audit) + post-accept `TaskRow.scope='plan'` (the canonical lineage) | **real** — F.1 projection + M3 semantic review + accept path tested. |
| **KB promote (`promote_to_memory`)** | `personal_kb_draft` or `kb_pending_review` | `canonical_world_memory` | `KbItemRow.id` + Membrane deterministic dup-title check + agent semantic review (M1) + numeric-claim guard | project owners (membrane_review accept) | `membrane_review` + `agent_semantic_review` | `KbItemService.create` / `.promote_to_group` / `.archive` → `MembraneService.review` → on accept `KbItemRepository.update(status='published')` | post-accept `KbItemRow.status='published'` + retained inbox suggestion ref | **real** — M1 + M1.1 + M1.2 archive primitive + M2 audit endpoint, all tested. |
| **decision crystallize** | `discussion` or `suggestion` | `canonical_decision` | source message + rationale + supersedes ref (when claimed) + recent topical decisions + related KB | varies by path: vote scope (smallest-relevant), gated proposal owner, conflict resolver, scrimmage convergence | `vote` *or* `owner_acceptance` *or* `agent_semantic_review` (M4 — blocks on contradiction without supersede) | `DecisionRepository.create` via `IMService._apply_proposal`, `ConflictService.resolve`, `GatedProposalService.approve`, etc. | `DecisionRow` row + `apply_outcome` + `scope_stream_id` + linked `IMSuggestionRow` | **partial** — M4 semantic gate is real and tested, but no `decision_crystallize` flow packet projects today; the lineage is in DB rows, not in `flow_projection`. Plan: a future slice projects decision packets for the same Active-Flows surface. |
| **handoff** | `handoff_drafted` | `handoff_finalized` | `HandoffRow` brief + linked routine refs | project owners (finalize gate) | `owner_acceptance` | `HandoffService.finalize` | `HandoffRow.finalized_at` + finalized routine refs | **real** — projection + tests cover draft and finalized states. |

Where a transition is **partial** or **aspirational**, the
implementation report (R6 / T6) names the missing pieces; the doc
must not paper over the gap with prose.

Why this matters: a "task" in GraphFlow is **not** a todo item. It is
a governed state transition. Same shape applies to KB promotes,
decisions, routes, and handoffs — every load-bearing change to graph
state crosses one of these contracts. The Membrane is the boundary
that enforces them.
- lineage output