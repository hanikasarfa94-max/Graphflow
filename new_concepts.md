# Graph Flow: Product Philosophy and System Doctrine

## 1. One-Line Positioning

**Graph Flow is an AI-native coordination system for high-mobility teams. It turns personal streams, routed judgments, technical boundaries, task commitments, and decision traces into a living organizational graph.**

Shorter:

**Graph Flow helps AI-augmented individuals coordinate without falling back into pre-AI meetings, document trees, and manual status reporting.**

---

## 2. The Core Problem

AI has made individuals dramatically more capable. A product manager can prototype interactions, summarize user research, generate demos, inspect API contracts, and draft implementation plans. A designer can explore dozens of variations. An engineer can ask an AI coding agent to investigate, modify, and explain code. A researcher can compress large bodies of material into working arguments.

But organizations still coordinate as if individuals were slow, memory-poor, and document-bound.

The dominant tools still assume that collaboration happens through:

* meetings,
* shared documents,
* group chats,
* ticket boards,
* status dashboards,
* and manual handoffs.

This creates a structural contradiction:

> **AI increases individual mobility, while existing coordination systems force people back into low-mobility rituals.**

The result is a familiar failure mode: AI makes each person faster, but the team still pays the same cost in alignment meetings, requirement reviews, context reconstruction, and decision recovery. In software delivery specifically, DORA’s 2024 report found that AI adoption can improve individual productivity, flow, and satisfaction, while also creating tradeoffs in delivery stability and throughput if engineering fundamentals are weak. ([Dora][1])

Graph Flow starts from this observation:

> **The bottleneck of AI-native work is no longer individual generation. It is organizational coordination.**

---

## 3. The Cavalry Problem

When AI makes individuals more mobile, they should not be managed with infantry-era formations.

A cavalry unit does not stop every few meters to hold a formation meeting. It requires a different doctrine: shared intent, decentralized execution, fast signaling, constrained autonomy, and clear rules for when to regroup.

This is close to the military concept of **mission command**: decentralized execution under a shared commander’s intent, enabling subordinate initiative, flexibility, and responsiveness. ([doctrine.af.mil][2])

Graph Flow translates this principle into knowledge work:

| Pre-AI coordination                 | AI-native coordination                                               |
| ----------------------------------- | -------------------------------------------------------------------- |
| Shared documents as the main memory | Structured turns and graph nodes as memory                           |
| Meetings as default alignment       | Routing as default alignment                                         |
| Group chat as shared context        | Personal streams with controlled context exchange                    |
| Task boards as manual status        | Task graph as commitment projection                                  |
| Knowledge base as file storage      | Knowledge as callable evidence                                       |
| Managers allocate work manually     | Membrane + routing + task commitments balance autonomy and resources |

Graph Flow does **not** claim that meetings are obsolete. It claims something narrower and stronger:

> **Meetings should no longer be the default coordination primitive.**

Meetings remain valuable for trust, conflict, strategic ambiguity, emotional alignment, and high-stakes collective commitment. But many meetings today are merely overloaded containers for information lookup, feasibility checks, status alignment, responsibility assignment, and small decisions. Graph Flow decomposes those functions into routable, traceable, AI-assisted protocols.

---

## 4. Core Thesis: From Documents to Turns

Pre-AI collaboration was document-centered because documents were the best available way to freeze human thought into a shareable object.

In the post-AI environment, this assumption breaks.

The basic unit of coordination should no longer be the document. It should be the **turn**.

A turn may be:

* a user message,
* an AI rehearsal,
* a routed judgment request,
* a technical feasibility reply,
* a decision acceptance,
* a task promotion,
* a risk confirmation,
* a knowledge citation,
* a code review signal,
* a rendered report.

A document becomes a **rendered artifact** of accumulated turns. It is no longer the primary input unit.

Graph Flow therefore treats collaboration as a stream of structured turns that can be routed, filtered, confirmed, crystallized, traced, and rendered.

> **Documents are outputs. Turns are inputs. The graph is the state.**

---

## 5. The Operating Principle

Graph Flow is built on five primitives:

```text
Intent
Context
Routing
Judgment
Crystallization
```

### Intent

The team needs a shared direction: project goals, scope boundaries, milestone constraints, technical principles, and what must not be broken.

### Context

Not all accessible information should enter an AI’s working context. Context must be selected, filtered, minimized, and scoped.

### Routing

Questions should not be broadcast by default. A signal should be routed to the person, sub-agent, or context holder most qualified to judge it.

### Judgment

The human role is not reduced to passive approval. Humans carry domain judgment, responsibility, preference, risk appetite, and value conflict resolution.

### Crystallization

A judgment that matters should not sink into chat. It should become a durable graph node with source, participants, rationale, downstream effects, and traceability.

---

# 6. System Architecture at the Product Level

Graph Flow consists of seven interlocking systems.

```text
Personal Stream
Membrane
Routing
Memory Graph
Task Commitment System
Skill / Authority Graph
Rendering and Audit Layer
```

Each system should remain distinct. If they collapse into one generic “AI workspace,” the product loses its conceptual sharpness.

---

## 6.1 Personal Stream: The Primary Interface

The personal stream is the main workspace.

A user does not enter a project and see a public channel or document tree. They see a private conversation with their project-aware sub-agent.

This is where the user:

* thinks,
* drafts,
* asks,
* rehearses,
* tests wording,
* explores ideas,
* creates personal plans,
* receives routing suggestions,
* previews downstream effects,
* and decides whether something should leave their personal context.

The personal stream protects individual mobility.

It should include:

* **rehearsal cards** before sending,
* **visible tool calls**,
* **context activation controls**,
* **routing proposals**,
* **task promotion proposals**,
* **decision crystallization cards**,
* **drift warnings**,
* **reference feedback controls**.

The personal stream is not just chat. It is the cockpit for AI-augmented work.

---

## 6.2 Membrane: Context Boundary and Promotion Control

Membrane is the most important governance layer.

Its core principle:

> **Access does not imply activation. Creation does not imply memory. Visibility does not imply team commitment.**

A user may have access to a document, but may not want it inside their personal AI context. A user may create a task, but it should not automatically enter the team plan. A product person may generate a demo, but it should not automatically become production work.

Membrane decides:

* what can leave a personal stream,
* what can enter another person’s routed context,
* what can become project context,
* what can become organizational memory,
* what must stay personal,
* what must be summarized,
* what must be redacted,
* what must be quarantined,
* what requires human confirmation.

Membrane is not a single omniscient LLM agent. It should be a **policy engine with LLM-assisted semantic judgment**.

Scripts and deterministic rules should handle:

* access control,
* role permissions,
* TTL and lifecycle transitions,
* WIP thresholds,
* sensitivity flags,
* source trust levels,
* status changes,
* deprecation,
* archival,
* budget limits.

LLMs should handle:

* ambiguous intent classification,
* long-text meaning extraction,
* task/decision/risk candidate generation,
* conflict explanation,
* minimal-context rewriting,
* rationale summarization.

This keeps the system governable and cost-aware.

---

## 6.3 Routing: Replacing Low-Value Meetings

Routing is the second signature feature of Graph Flow.

Routing is not @mentioning. It is not forwarding. It is not assigning a task.

Routing means:

> **turning a personal signal into a structured judgment request and sending it to the right production-relation node.**

A routed signal contains:

* background,
* requested judgment,
* minimal necessary context,
* candidate options,
* tradeoffs,
* why this person is being asked,
* whether the reply is human-required or sub-agent-previewable,
* how the reply may affect tasks, risks, decisions, or knowledge.

A typical routed request should look like:

```text
Raj is considering a Boss-1 souvenir revive mechanic.

Requested judgment:
Can this be implemented within two weeks without endangering Alpha freeze?

Why you:
You own the relevant backend save-state logic and recently reviewed the Switch performance risk.

Please answer:
1. Feasible / not feasible / feasible with cuts
2. Main technical risk
3. Whether this affects the current milestone
```

Routing should use search/recommendation-style infrastructure:

* candidate generation,
* authority matching,
* graph proximity,
* workload awareness,
* interruption cost,
* historical routing feedback,
* ranking,
* and fallback targets.

Traditional recommender architectures often separate candidate generation from ranking; this is useful for Graph Flow because routing should not be decided purely by an LLM’s intuition. ([Elastic][3])

Routing should also use anti-disturbance logic:

* merge similar requests,
* rate-limit high-demand members,
* prefer sub-agent preview for low-risk questions,
* ask humans only when judgment is actually needed,
* downgrade weak requests to personal notes.

A meeting is needed only when routing fails to resolve a genuine multi-party conflict.

---

## 6.4 Hybrid Memory Graph: Store Broadly, Activate Narrowly

Graph Flow should not treat the graph as an ever-growing hot memory.

The system needs a hybrid memory strategy:

```text
Raw Store
Search Index
Memory Units
Graph Relations
Attention Layer
Feedback Layer
```

### Raw Store

Everything can be stored: streams, documents, commits, uploads, route replies, rendered artifacts, task changes.

### Search Index

Use hybrid retrieval:

* lexical search / BM25 for exact terms,
* vector search for semantic recall,
* graph neighbor retrieval for relationships,
* metadata filters for project, author, time, permission, status.

Hybrid search is a mature retrieval pattern; Elastic describes hybrid search as combining lexical and semantic methods into one ranked list, often improving precision and recall. ([Elastic][3])

### Memory Units

Long documents should not be remembered as wholes. AI-generated long-form text often contains only a few durable claims. The system should extract smaller units:

* claim,
* principle,
* constraint,
* preference,
* decision rationale,
* risk signal,
* task commitment,
* technical boundary,
* skill evidence,
* open question.

### Graph Relations

The graph should store relationships, not all text.

Important edges include:

* derived_from,
* supports,
* contradicts,
* supersedes,
* creates_task,
* blocks,
* assigned_to,
* reviewed_by,
* routed_to,
* confirmed_by,
* cited_in,
* feedback_on.

GraphRAG-style local and global search is relevant here: Microsoft GraphRAG distinguishes local search for entity-specific questions and global search for corpus-level synthesis. Graph Flow can borrow that distinction, but its graph is not merely semantic; it encodes responsibilities, decisions, commitments, and production relations. ([GitHub Microsoft][4])

### Attention Layer

Every AI interaction should generate a temporary **Context Bundle**.

The bundle records:

* active nodes,
* evidence refs,
* suppressed nodes,
* suppression reasons,
* scope,
* expiry,
* budget by category.

The graph preserves history; the attention layer serves the present.

### Feedback Layer

Every citation, routing, and task promotion can receive feedback:

* useful,
* irrelevant,
* outdated,
* only this turn,
* do not use again,
* promote to project context,
* use as decision evidence.

Implicit feedback adjusts attention weakly. Explicit confirmation promotes memory strongly.

---

## 6.5 Task Commitment System: From Personal Intention to Team Commitment

Graph Flow’s task system should not be a plain task list.

It should manage the conversion between personal autonomy and team-recognized commitment.

AI lets individuals plan more deeply and more freely. A user can generate many subtasks in a personal stream. But personal subtasks should not automatically become team obligations.

Graph Flow should distinguish four recognition levels:

```text
L0 Personal
L1 Visible
L2 Allocated
L3 Committed
```

### L0 Personal

Private personal task. Helps the user think and act. Does not occupy team capacity.

### L1 Visible

Team can see the work exists, but it does not count as scheduled work.

### L2 Allocated

Team acknowledges that this work occupies capacity.

Example: Raj spends half a day exploring a CRM tagging demo.

### L3 Committed

Work becomes a delivery commitment with owner, scope, reviewer, dependencies, and milestone effect.

This distinction matters because AI can easily generate task inflation. Kanban’s emphasis on limiting work in progress is relevant: without WIP limits, systems overload and flow degrades. ([Elastic][5])

Task Membrane handles promotion:

```text
Personal Task
→ Visible Work
→ Capacity Allocation
→ Team Commitment
```

The team is not judging whether a person is “working hard.” It is judging whether a piece of work should claim shared resources, dependencies, and schedule attention.

Task objects should track:

* origin,
* recognition level,
* work kind,
* owner,
* reviewer,
* approvers,
* estimate,
* confidence,
* capacity impact,
* dependencies,
* risk refs,
* decision refs,
* technical owner,
* membrane decision.

This allows Graph Flow to balance autonomy and coordination.

---

## 6.6 Technical Membrane: Sharing Architecture Without Exposing Source Code

AI changes the product-engineering boundary.

Previously, product and engineering often split because they held different contexts:

```text
Product: user research, business intent, workflow, market signal
Engineering: codebase, architecture, data model, performance, debt
```

AI allows product/design/ops roles to prototype faster. They can make HTML demos, simulate flows, and explore possibilities. But prototype feasibility is not production feasibility.

Graph Flow should expose **technical context slices** without exposing full source code.

Technical Membrane should provide:

* capability maps,
* API contracts,
* schema summaries,
* architecture constraints,
* technical debt notes,
* production risk levels,
* data sensitivity boundaries,
* test and deployment constraints,
* “demo-feasible vs production-feasible” classification.

This supports product exploration without violating least-privilege access. NIST’s Zero Trust Architecture emphasizes explicit, fine-grained access decisions and least privilege rather than broad implicit trust. ([MacDill FSS][6])

Technical Membrane should classify work as:

```text
Prototype-feasible
Integration-feasible
Production-feasible
Architecture-impacting
```

This changes the role of engineering.

Engineers do not disappear. They move upward:

* architecture boundary owners,
* code review authorities,
* merge gatekeepers,
* production hardening reviewers,
* technical debt stewards,
* interface contract maintainers,
* risk validators.

Product explores faster; engineering protects production.

---

## 6.7 Skill and Authority Graph: Routing, Not Ranking

The skill graph should not become a public performance scoreboard.

Its purpose is not to rank people. Its purpose is to help the system decide:

> Who is likely to have legitimate judgment authority over this signal?

Skill evidence should be separated into:

```text
Role-based skill
Self-declared skill
Observed skill
Validated skill
```

The system may use this internally to route judgment requests and weight feedback. But the UI should avoid public personal scores.

A better interface:

```text
Recommended target: Aiko

Reason:
- Engineering owner
- Recently reviewed save-state logic
- Related to two open technical risks
- Current routing load is acceptable
```

Not:

```text
Aiko: 92 engineering score
Raj: 70 engineering score
```

Graph Flow can support management views, but the default should show structural bottlenecks, not individual rankings.

It may show:

* capability coverage,
* overloaded domains,
* missing reviewers,
* unverified claimed skills,
* routing bottlenecks.

It should not casually expose:

* personal responsiveness rankings,
* adoption-rate leaderboards,
* AI productivity rankings,
* raw “performance scores.”

This is both ethically safer and organizationally more stable.

---

## 6.8 Knowledge Base: Callable Evidence, Not a File Cabinet

The knowledge base is not a Notion clone.

Each knowledge item should answer:

* Can AI use this?
* In what context?
* With what citation?
* At what confidence level?
* Is it personal, project, or external?
* Has it been used in decisions or tasks?
* Has anyone marked it outdated?
* Is it a weak signal or verified evidence?

Knowledge entries should have a context policy:

```text
search_only
answer_grounding
decision_evidence
task_generation
render_output
manual_only
ask_before_use
```

The knowledge base should show:

* source,
* trust level,
* freshness,
* activation policy,
* reverse references,
* recent calls,
* linked decisions,
* linked tasks,
* linked risks.

The key difference:

> **A knowledge base stores evidence; Membrane decides whether evidence becomes context.**

---

## 6.9 State Page: Projection, Not Dashboard Overload

The status page should not become a generic management dashboard.

Its role is narrower:

> **A read-only projection of the current graph state for non-core participants, reviewers, advisors, and external observers.**

It should answer:

* What is the project condition?
* What risks are active?
* What decisions have been made?
* What tasks are recognized team commitments?
* What artifacts exist?
* What needs attention?

It should not be the team’s primary working surface. The primary surface remains the personal stream and routing inbox.

The status page should be concise:

* AI state summary,
* key risks,
* committed work,
* recent decisions,
* rendered artifacts,
* membrane health,
* links into source nodes.

---

## 6.10 Rendering Layer: Documents as Outputs

Rendered documents are not where collaboration happens. They are generated views of the graph.

Examples:

* postmortem,
* handoff,
* milestone summary,
* decision log,
* audit report,
* technical feasibility note,
* stakeholder update.

Rendered artifacts must be grounded in graph nodes and source references. They should not be free-form LLM essays.

Each rendered artifact should include:

* cited decisions,
* cited tasks,
* cited risks,
* cited knowledge,
* source node links,
* generation timestamp,
* version history.

Documents become reliable because they are graph renderings.

---

## 6.11 Cell Model and Scope Tiers

> Cross-reference: this section + §9.1 + §9.4 + §10.1 supersede earlier corrections in `docs/north-star.md`. The diff is captured under "Architectural correction R (2026-04-28, WorkGraph Next)" in north-star; build tasks live in `PLAN-Next.md` at repo root.

Graph Flow uses a single structural metaphor for governed collaboration:

> **A project is a cell. An enterprise is an organism with many cells.**

Membrane is what sits between cells. It controls what crosses (scope-into-cell writes, decision crystallization, edge promotion, candidate review). The "single membrane is the only boundary" rule is the consequence of this metaphor: there is exactly one membrane per cell, and every promotion path runs through it.

### Four scope tiers

Context, knowledge, and memory are scoped on a four-tier ladder, orthogonal to ACL/license tiers (full-member / task-scoped / observer):

```text
Personal       me + my sub-agent
Cell           project members + relevant cross-cutting leaders
Department     functional subset (e.g., Eng KB, Design KB, Marketing KB)
Enterprise     org-wide (HR policy, brand, compliance)
```

Note on schema vocabulary: the existing `KbItemRow.scope='group'` value already means **cell** (project-scoped). The schema is not renamed; readers should interpret legacy `'group'` as the Cell tier. The Department and Enterprise tiers are net-new and need their own scope values when added.

The personal stream defaults to *personal + my-cells* and the user can broaden a single turn ("include Enterprise KB for this question") via explicit scope toggles. Membrane evaluates each tier admission separately.

"Relevant cross-cutting leaders" can read into cells they are relevant to even without explicit membership. Implementation is read-only bypass; write still requires explicit cell membership so the single-membrane rule is preserved.

### Multiple rooms per cell, smallest-relevant-vote default

A cell can host multiple team-room streams (sub-team rooms, topical rooms, ad-hoc rooms) — not just one. The decision system uses a Schelling-point rule:

> **A decision's vote scope defaults to the smallest relevant group.**

A 1:1 DM decision votes between two; a four-person room decision votes among four; a cell-level decision votes across all members. "Relevant" is determined by Membrane / Edge Agent from discussion context. This prevents room sprawl from causing vote spam, and gives quorum-routing for free.

### Manual creates as candidates

Users may manually create cells (projects), tasks, or KB items by typing. These do not become canonical state directly. They enter as **candidates** at L0/L1 and ascend through Membrane review like any other promotion. The "creation does not imply memory" principle of §6.2 applies equally to user typing and to AI-generated proposals.

---

# 7. Core Algorithmic Doctrine: The Attention Engine

Graph Flow is not built on the assumption that an AI agent should read everything it can access.

The core algorithmic problem is not simply retrieval. It is attention allocation under organizational constraints.

A team workspace contains many possible signals:

personal messages,
team discussions,
documents,
code,
tasks,
risks,
decisions,
technical constraints,
user research,
skill evidence,
route replies,
rendered artifacts.

Only a small subset should influence any given AI action.

Therefore, Graph Flow treats search, recommendation, graph traversal, and membrane policy as parts of one larger system:

an attention engine for AI-native teamwork.

The purpose of this engine is to decide:

What should be recalled?
What should be ranked?
What should be filtered?
What should be activated?
What should be suppressed?
What should be routed?
What should be promoted into organizational memory?

This differs from traditional enterprise search. Enterprise search helps a user find information. Graph Flow’s attention engine helps an agent decide what information is allowed to shape a judgment.

## 7.1 Search Is Candidate Generation, Not Context Selection

Graph Flow should use search as the first stage, not the final answer.

Search produces candidates. It does not decide what enters context.

The first stage should combine several retrieval channels:

Lexical search
Vector search
Graph-neighbor retrieval
Recent activity retrieval
Pinned context retrieval
User-selected context

This follows a mature pattern from large-scale recommender systems. The YouTube recommendation architecture, for example, separates candidate generation from ranking: the first stage retrieves a manageable set of candidates from a huge corpus, and the second stage ranks them more precisely.

Graph Flow should apply the same principle to organizational context:

Candidate generation finds possible context.
Ranking estimates usefulness.
Membrane decides admissibility.
Attention budgeting decides what is actually activated.
## 7.2 Hybrid Retrieval: Lexical, Vector, Graph, and Recency

Graph Flow should not rely on vector search alone.

Vector search is strong for semantic similarity, but weak for:

exact task IDs,
member names,
technical terms,
decision IDs,
API names,
recent operational state,
explicit dependency chains.

Lexical search remains important for exact matching. Graph traversal is important for relationships. Recency is important for active work.

Therefore, Graph Flow should use hybrid retrieval:

BM25 / full-text search
+ vector similarity
+ graph-neighbor expansion
+ recent active nodes
+ explicit user-selected context

Elastic’s hybrid search documentation describes combining lexical and semantic search, and Reciprocal Rank Fusion, or RRF, is especially useful because it can combine rank lists from different retrievers without requiring their raw scores to share the same scale.

A practical first implementation can be:

BM25 top 50
Vector top 50
Graph-neighbor top 30
Recent active nodes top 20
User-pinned nodes top 10
→ RRF merge
→ Membrane filtering
→ Context ranking

This keeps the system robust without immediately requiring a complex learning-to-rank model.

## 7.3 Graph Retrieval: Local, Global, and Work-State Search

Graph Flow can learn from GraphRAG, but should not copy it blindly.

Microsoft GraphRAG distinguishes between local search and global search. Local search is useful when answering questions about specific entities and their neighboring relationships; global search uses graph-level community summaries for broader questions about a whole corpus.

Graph Flow needs a related but different distinction:

Local work-state search:
What directly relates to this task, decision, risk, person, or route?

Global project-state search:
What does the overall project graph imply about health, direction, risk, or drift?

Personal-state search:
What matters to this user right now?

Authority-state search:
Who is qualified to judge this signal?

Graph Flow’s graph is not just a semantic graph. It is a production-relation graph.

It represents:

who judged what,
who owns what,
what decision created which task,
what risk blocks which milestone,
what knowledge supports which decision,
what skill evidence qualifies which person,
what context was suppressed and why.

The graph is therefore not merely for retrieval. It constrains organizational reasoning.

## 7.4 Ranking: From Relevance to Organizational Usefulness

A normal search engine ranks documents by relevance.

Graph Flow should rank context by organizational usefulness.

A candidate node should not be ranked only by semantic similarity. It should be scored by multiple dimensions:

semantic relevance
lexical relevance
graph proximity
recency
confirmation level
source trust
user feedback
domain authority
task urgency
milestone pressure
dependency centrality
sensitivity penalty
staleness penalty
supersession penalty
attention budget cost

A simple first-stage scoring function can be:

activation_score =
  semantic_relevance
+ lexical_relevance
+ graph_proximity
+ recency
+ confirmation_level
+ authority_weight
+ feedback_weight
+ urgency_weight
- sensitivity_penalty
- staleness_penalty
- superseded_penalty
- overload_penalty

This should be explainable. Early Graph Flow should prefer simple, transparent ranking over opaque optimization.

The first version does not need a trained ranking model. It can start with rule-weighted scoring and later evolve into learning-to-rank after enough feedback data is collected.

## 7.5 Recommendation for Agents, Not Users

Traditional recommendation systems recommend content to users.

Graph Flow recommends context and actions to agents.

The recommended objects are not videos or products. They are:

knowledge items
tasks
risks
decisions
people
routes
technical constraints
context bundles
next actions
candidate commitments

The recommender’s job is not engagement maximization. It is coordination quality.

Graph Flow should optimize for:

fewer unnecessary meetings
better routed judgments
lower context overload
higher decision traceability
lower rework
fewer stale references
faster task clarification
better resource fit

This is a different objective from consumer recommendation.

## 7.6 Feedback: Distributed Context Validation

Graph Flow should learn from user feedback, but cautiously.

Recommender systems have long distinguished implicit and explicit feedback. Hu, Koren, and Volinsky’s work on implicit feedback emphasizes that implicit signals indicate preference with varying confidence, rather than directly proving positive or negative intent.

Graph Flow should apply this principle to organizational memory.

A user clicking a reference does not mean the reference is true. A user not objecting does not mean they agree. A user accepting a routed answer does not mean it should become a decision.

Feedback should be tiered:

Weak implicit feedback:
clicked, expanded, continued discussion

Medium explicit feedback:
useful, irrelevant, outdated, only this turn, do not use again

Strong confirmation:
promote to project context, use as decision evidence, accept task, confirm decision

Only strong confirmation should promote an item into formal organizational memory.

Weak feedback should merely adjust:

activation_weight
personal relevance
source usefulness
routing preference
context policy

This creates a distributed governance model:

users validate context during normal work, instead of maintaining a centralized knowledge system.

## 7.7 Membrane as a Post-Retrieval Gate

Search and recommendation can rank candidates, but they cannot decide legitimacy.

A highly relevant item may still be forbidden, sensitive, stale, private, or misleading.

Therefore, every ranked candidate must pass through Membrane.

Membrane evaluates:

permission
user intent
sensitivity
source trust
freshness
confirmation status
scope
privacy
technical boundary
team impact

A candidate can be assigned one of several actions:

allow
personal_only
summarize
redact
downgrade
route
quarantine
reject
archive
supersede
merge

This prevents the common failure of RAG systems:

retrieved therefore used.

Graph Flow’s rule should be:

retrieved means possible; membrane-approved means usable; human-confirmed means durable.

## 7.8 Context Bundles: The Runtime Product of the Algorithm

The output of the attention engine is not a raw list of documents.

It is a Context Bundle.

A Context Bundle records:

intent
active nodes
evidence references
suppressed nodes
suppression reasons
scope
budget
expiry
membrane decisions
feedback hooks

Example:

Context Bundle for:
“Can we turn the CRM tagging demo into a production task?”

Activated:
- current CRM milestone
- existing upload capability
- customer data sensitivity rule
- previous decision on manual confirmation
- backend owner’s technical boundary note

Suppressed:
- private product draft: not user-approved for team context
- old prototype note: superseded
- external article: low source trust

This makes context selection inspectable.

The AI answer should be generated from the Context Bundle, not from arbitrary retrieval output.

## 7.9 Attention Budgeting: Preventing Graph Bloat

Graph Flow’s graph may grow, but active context must remain small.

The system should distinguish:

Raw Store
Warm Graph
Hot Graph
Runtime Context Bundle
Raw Store

Everything stored for traceability.

Warm Graph

Project memory that can be recalled.

Hot Graph

Currently active tasks, risks, decisions, constraints, and commitments.

Context Bundle

The temporary subset used by one AI action.

Every interaction should have a budget:

max decisions
max tasks
max risks
max knowledge items
max personal memories
max technical constraints
max routed signals

This is the algorithmic mechanism behind the principle:

The graph preserves history. Attention serves the present.

## 7.10 Lifecycle and Exit Mechanisms

Every graph node must have a lifecycle.

Possible states:

candidate
active
watch
dormant
superseded
deprecated
archived
rejected
expired
merged

Without exit mechanisms, the graph becomes a landfill.

Lifecycle rules should be mostly deterministic:

completed task + 7 days → watch
completed task + 30 days → archived
weak signal unused for 30 days → dormant
candidate decision unconfirmed for 7 days → expired
new decision replaces old decision → superseded
old technical note contradicted by newer owner review → deprecated
duplicate risk signals → merged

LLMs should not decide lifecycle transitions alone. They may propose merges or conflicts, but high-impact transitions require confirmation.

## 7.11 Routing as Recommendation Under Authority Constraints

Routing is also a recommendation problem.

Given a signal, the system recommends who should judge it.

Candidate features include:

role authority
declared skill
observed skill
validated skill
graph proximity
recent involvement
current workload
availability
previous routing acceptance
decision authority
permission boundary
interruption cost

The routing score should balance authority and interruption cost:

routing_score =
  authority
+ graph_relevance
+ recent_involvement
+ availability
+ historical_acceptance
- load_penalty
- interruption_penalty
- privacy_penalty

This avoids both extremes:

always ask the manager
always ask the most active expert
broadcast to everyone
let the LLM guess

Routing should be sparse. Most signals should go to one person, one sub-agent, or no one.

## 7.12 Task Recommendation: Balancing Autonomy and Capacity

Task scheduling should also use recommendation logic.

A personal task should not automatically become a team task. The system should recommend whether to keep it personal, make it visible, request capacity allocation, or promote it into a team commitment.

The recommended action depends on:

goal fit
milestone relevance
dependency impact
technical risk
capacity impact
owner authority
WIP pressure
confidence
urgency

This is not generic project management. It is resource-aware commitment recommendation.

## 7.13 Algorithmic Governance Principles

Graph Flow’s algorithmic layer should follow ten rules.

1. Search broadly, activate narrowly.

Large retrieval is acceptable. Large active context is not.

2. Retrieve by similarity, use by permission.

Semantic relevance is not enough.

3. Recommend context, not content consumption.

The goal is better coordination, not engagement.

4. Rank for usefulness, not popularity.

Frequent references are not automatically authoritative.

5. Promote by confirmation, not generation.

AI-generated candidates remain candidates until promoted.

6. Treat implicit feedback as weak evidence.

Clicks and silence do not equal agreement.

7. Use authority-weighted feedback.

A technical owner’s feedback on architecture carries more weight than a casual observer’s.

8. Keep lifecycle explicit.

Every node must be able to become stale, superseded, archived, or merged.

9. Make suppression explainable.

The system should explain not only what it used, but what it did not use and why.

10. Prefer simple rankers before learned rankers.

Early systems need debuggability more than optimization.

## 7.14 Practical First Implementation

The first version should be simple.

Stage 1: Hybrid Candidate Generation
BM25 top 50
Vector top 50
Graph neighbors top 30
Recent active top 20
Pinned context top 10
Stage 2: RRF Fusion

Merge ranks from different retrievers.

Stage 3: Rule-Based Membrane

Filter by:

permission
scope
sensitivity
staleness
supersession
recognition level
context budget
Stage 4: Explainable Ranking

Use weighted features:

relevance
recency
authority
confirmation
feedback
urgency
graph distance
Stage 5: Context Bundle Assembly

Create the actual runtime context.

Stage 6: Feedback Logging

Record:

shown
clicked
used
accepted
rejected
corrected
promoted
suppressed
Stage 7: Later Learning-to-Rank

Only after enough data exists, train a model to predict:

reference usefulness
route acceptance
task promotion
decision confirmation
context rejection

The first version should remain mostly transparent and deterministic.

## 7.15 The Algorithmic Identity of Graph Flow

Graph Flow’s algorithmic identity can be summarized as:

Search finds possible context.
Recommendation ranks useful context.
Membrane governs admissible context.
Graph structures durable context.
Feedback updates future context.
Agents act on runtime context bundles.

Or shorter:

Graph Flow is not a chatbot over a knowledge base. It is an attention allocation system for AI-mediated organizations.
---

# 8. Agent and Service Design

Graph Flow should avoid “too many autonomous agents.”

The system should be built from deterministic services plus a few LLM agents used where language judgment is necessary.

## Deterministic Services

### Retrieval Service

* lexical search,
* vector search,
* graph neighbor recall,
* RRF fusion,
* ACL filtering,
* metadata filtering.

### Membrane Policy Engine

* permission checks,
* sensitivity rules,
* lifecycle transitions,
* context scope,
* promotion rules,
* WIP checks,
* data/code access boundaries.

### Context Assembler

* builds Context Bundles,
* applies budgets,
* records suppressed nodes,
* controls context expiry.

### Routing Candidate Service

* generates candidate people or sub-agents,
* uses skills, ownership, graph proximity, load, and historical feedback.

### Routing Ranker

* ranks targets,
* balances authority and interruption cost.

### Task Scheduler / Commitment Engine

* distinguishes L0/L1/L2/L3 tasks,
* checks WIP and capacity,
* detects milestone conflicts,
* routes approvals.

### Graph Janitor

* expires,
* archives,
* merges,
* marks superseded nodes,
* prevents hot graph bloat.

## LLM Agents

### Edge Agent

Personal stream assistant. Handles conversation, rehearsal, tool use, routing suggestions, and explanation.

### Signal Framing Agent

Turns ambiguous personal messages into structured routed requests or task proposals.

### Extraction Agent

Extracts memory units from long text, meetings, documents, and complex streams.

### Crystallization Agent

Turns accepted judgments into decision, task, risk, or knowledge candidates. Requires human confirmation for high-impact nodes.

### Technical Membrane Agent

Summarizes technical constraints, capability maps, risk classes, and production feasibility based on authorized technical context.

### Render Agent

Generates grounded reports and handoffs from graph nodes.

### Drift Agent

Detects divergence between project intent and actual output.

The rule:

> **Use scripts for policy, ranking, lifecycle, permission, and budget. Use LLMs for semantic compression, explanation, routing language, and crystallization.**

This prevents the system from becoming expensive, unstable, or impossible to audit.

---

# 9. Product Modules

## 9.1 General-Agent Stream (the entry point)

There is no separate Home page. The user lands directly in the **general-agent stream** — their conversation with their personal sub-agent, with no cell anchor. This is the cross-cell command surface and the everyday default.

A persistent left sidebar surfaces, alongside (not replacing) the stream:

* pending routed signals,
* waiting judgments,
* active commitments,
* blocked items,
* recent important graph changes,
* cells requiring attention,
* DM list and recent rooms.

These are sidebar entries, not destination pages. The user can ask cross-cell questions ("what's missing for Stellar Drift launch?") directly in the stream and the Edge Agent infers cell scope per turn. Switching into a cell-scoped stream is a soft scope hint via the ProjectBar pills, not a forced navigation step.

## 9.2 Personal Project Stream

The main interface.

It supports:

* thinking,
* asking,
* rehearsal,
* context selection,
* routing proposals,
* task promotion,
* decision crystallization,
* reference feedback.

## 9.3 Routing Inbox

A judgment queue, not a message inbox.

Categories:

* waiting for my judgment,
* waiting for my confirmation,
* can be answered by my sub-agent,
* needs transfer,
* needs more context,
* high-impact route.

## 9.4 Team Rooms

A cell may host multiple team-room streams. Rooms are low-frequency shared streams for moments that genuinely need synchronous or group awareness — sub-team rooms, topical rooms, or ad-hoc rooms carved out of a cell.

Rooms must not become the default coordination channel; routing and personal streams remain primary. The constraint that prevents room sprawl is the **smallest-relevant-vote** rule (§6.11): a decision crystallized inside a room votes only among the people that decision concerns, not the whole cell. This keeps rooms cheap to create without producing vote spam.

A new room created by typing enters as a candidate; Membrane confirms it before it occupies any cell capacity.

## 9.5 Task / Commitment View

Shows recognized work, not every personal subtask.

It should distinguish:

* personal tasks,
* visible work,
* allocated capacity,
* committed delivery.

## 9.6 Knowledge Base

Callable evidence store with context policy, reverse links, and usage history.

## 9.7 Skill / Authority Graph

Routing and capability coverage layer.

Default member view should be limited and non-ranking.

Owner view can show aggregate capability gaps and routing bottlenecks.

## 9.8 Status Page

Read-only graph projection for quick alignment.

## 9.9 Rendered Artifacts

Grounded documents generated from graph state.

## 9.10 Audit / Node Detail

Source of truth for why-chain, lineage, membrane decisions, routing traces, and confirmations.

---

# 10. Design Principles

## 10.1 Flow First, Board Second

Work happens in streams. Boards are projections.

"Stream-centered" does not mean "stream-only." A user-composable side workbench — opt-in panels that are shortcut-views into underlying detail pages (tasks, knowledge, skills, routing inbox) — is acceptable next to the stream. The constraint: panels must link back to a real page, must be user-toggleable, and must not be the only place a piece of state lives. A multi-pane *console as destination* remains rejected; a *user-composed shortcut tray* on the side is fine.

## 10.2 Routing Before Meetings

Default to structured routing. Use meetings only for irreducible ambiguity, conflict, trust, or collective commitment.

## 10.3 Membrane Before Memory

No information should become active context merely because it exists.

## 10.4 Graph as State, Not Decoration

The graph is not a visual gimmick. It is the state model behind tasks, risks, decisions, knowledge, routing, and rendered artifacts.

## 10.5 Human Judgment, Machine Context

Machines preserve context, route signals, and prepare options. Humans make judgments and accept responsibility.

## 10.6 Store Broadly, Activate Narrowly

Keep raw records. Activate only what is relevant, permitted, fresh, and intended.

## 10.7 Promote by Confirmation, Not Generation

AI may propose. Promotion to team memory requires rules, feedback, or human confirmation.

## 10.8 Protect Autonomy and Coordination

Individuals may plan freely. Teams only need to confirm work when it claims shared capacity, affects dependencies, or becomes a delivery commitment.

## 10.9 Explain Every Boundary

When the system routes, filters, suppresses, or activates context, it should be explainable.

## 10.10 Avoid Performance Theater

The system may provide management intelligence, but default UI should surface structural bottlenecks rather than public personal rankings.

---

# 11. The Differentiation

Graph Flow is not:

* Slack with AI,
* Notion with AI,
* Jira with AI,
* a generic knowledge base,
* a dashboard,
* a meeting assistant,
* an autonomous project manager.

Graph Flow is:

> **An AI-native coordination protocol for teams whose individuals are already AI-augmented.**

The difference:

| Existing tool logic           | Graph Flow logic                                                                |
| ----------------------------- | ------------------------------------------------------------------------------- |
| Chat records what people said | Graph Flow routes what needs judgment                                           |
| Docs freeze shared thinking   | Graph Flow renders documents from graph state                                   |
| Tickets record assigned work  | Graph Flow promotes personal intent into team commitment                        |
| Knowledge base stores files   | Graph Flow manages callable evidence                                            |
| Dashboard shows manual status | Graph Flow projects graph state                                                 |
| Meetings align people         | Graph Flow decomposes alignment into routing, confirmation, and crystallization |
| AI assists individuals        | Graph Flow coordinates AI-augmented individuals                                 |

---

# 12. Example: Product–Engineering Collaboration

Before AI, product and engineering often met because they held different contexts.

Product knew users. Engineering knew code.

AI changes this. Product can now prototype, simulate, and explore. But demos do not equal production readiness. HTML feasibility does not imply backend feasibility. AI-generated prototypes may ignore data consistency, security, performance, observability, testing, and technical debt.

Graph Flow handles this through Technical Membrane and Routing:

1. Product explores in personal stream.
2. AI creates a prototype and identifies assumptions.
3. Technical Membrane exposes safe architecture context.
4. The system classifies the work:

   * prototype-feasible,
   * integration-feasible,
   * production-feasible,
   * architecture-impacting.
5. Routing sends only the necessary judgment request to the technical owner.
6. The technical owner confirms feasibility, narrows scope, or redirects.
7. The result becomes a task, risk, decision, or technical constraint node.

This replaces many requirement review meetings with targeted feasibility routing.

---

# 13. Example: Personal Task to Team Commitment

A user plans:

```text
Explore automatic customer tagging from imported order sheets.
```

At first this is a personal task.

The user then asks to submit it to the team.

Graph Flow generates:

```text
Task proposal:
CRM customer tagging demo

Recognition requested:
L2 Allocated

Expected capacity:
Raj: 0.5 day
Backend owner: 0.5 day review
Data sample: one anonymized order sheet

Not included:
Production integration
Automatic customer outreach
Permanent label schema changes

Suggested approvers:
Project owner
Backend owner
Data owner
```

The team may choose:

* keep personal,
* make visible,
* allocate capacity,
* commit for delivery,
* defer,
* split into exploration and implementation,
* request technical review.

This prevents AI-generated personal planning from becoming uncontrolled team workload.

---

# 14. Example: Routing Instead of Meeting

Maya asks:

```text
If permanent death only applies to boss fights, what is the engineering cost?
```

The Edge Agent detects an engineering judgment request.

Membrane removes unnecessary private context.

Routing identifies Aiko as the likely technical authority.

Aiko receives:

```text
Requested judgment:
Can this mechanic be implemented within two weeks?

Context:
Boss-1 frustration risk is high.
The team is exploring a softer penalty model.
Alpha freeze is approaching.

Answer format:
Feasible / infeasible / feasible with cuts.
Main technical risk.
Impact on milestone.
```

Aiko responds:

```text
Feasible only if we limit it to a souvenir revive mechanic and avoid a full progression tree.
```

Maya accepts.

The system crystallizes:

```text
Decision:
Use souvenir revive as the limited mitigation for Boss-1 permanent death frustration.

Reason:
Preserves tension while controlling engineering scope.

Effects:
Creates implementation task.
Adds Alpha freeze risk.
Supersedes earlier full permanent-death proposal.
```

No meeting required. No document required. The why-chain is preserved.

---

# 15. Strategic Conclusion

Graph Flow begins from a simple but non-trivial claim:

> **AI-native work does not need more AI inside old collaboration tools. It needs new coordination primitives.**

The old primitives were:

```text
meeting
document
chat
ticket
dashboard
```

Graph Flow’s primitives are:

```text
turn
membrane
route
judgment
commitment
crystallization
graph projection
```

The product’s deepest thesis:

> **When individuals become more capable through AI, coordination must shift from synchronous control to intent-driven, membrane-governed, route-mediated, graph-crystallized collaboration.**

Graph Flow is the system built around that shift.

[1]: https://dora.dev/research/2024/dora-report/?utm_source=chatgpt.com "DORA | Accelerate State of DevOps Report 2024"
[2]: https://www.doctrine.af.mil/Portals/61/documents/AFDP_1-1/AFDP%201-1%20Mission%20Command.pdf?utm_source=chatgpt.com "MISSION COMMAND - Air Force Doctrine"
[3]: https://www.elastic.co/what-is/hybrid-search?utm_source=chatgpt.com "What is hybrid search? How it works and when to use it"
[4]: https://microsoft.github.io/graphrag/query/local_search/?utm_source=chatgpt.com "Local Search - GraphRAG"
[5]: https://www.elastic.co/search-labs/blog/hybrid-search-elasticsearch?utm_source=chatgpt.com "Overview & hybrid search queries - Elasticsearch Labs"
[6]: https://macdillfss.com/wp-content/uploads/2026/04/Air-Force-Doctrine.pdf?utm_source=chatgpt.com "Air Force Doctrine"
