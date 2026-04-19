# WorkGraph AI — Vision (v2)

**Status:** articulated 2026-04-18. Supersedes the "delivery coordination engine" framing in `docs/dev.md` and `AGENT.md` as the long-term product north star. MVP (Phases 1–13) is retained as the scaffolding demo; v2 is what we build toward.

---

## 1. What We're Not Building

We are **not** building:

- Notion-with-AI
- Feishu-with-AI
- A PM/Dev/QA ticket tool with chatbot bolted on
- A "super-individual" tool that makes each person faster in isolation
- A generic LLM copilot shell

AI has made individuals faster. Group collaboration has not caught up. Teams still hold meetings, write docs, and debate in chat — because every person's AI is private. The collective is still running on the old office stack.

## 2. What We Are Building

WorkGraph is an **AI-native operating graph for an organization**.

- **Humans are first-class nodes** in the graph. Each has capabilities, attention, commits, and a personal AI.
- **The graph is the shared context.** Not a chat log, not a doc — a live structural representation of goals, decisions, tasks, and the edges between people.
- **LLM lives on the edges.** Every interaction between two humans passes through an LLM that sees the graph, not a private assistant that sees only its user.
- **Decisions flow along edges and mutate graph state.** Nothing dies in a chat window.
- Goal: **super-groups**, not super-individuals.

## 3. Core Shift

| Old office | AI-native office |
|---|---|
| Documents are the coordination medium | **Signals** are the coordination medium (docs are artifacts of past chains) |
| Messages are the default unit | **Decisions** crystallize from signal chains; stored as graph nodes |
| Docs freeze knowledge | Graph state is live and queryable |
| Tickets disconnect from why | Every task traces to a vision commit via a decision chain |
| Org chart routes work (roles) | **Response profiles** route work (signal-affinity + graph distance + attention) |
| Meeting is the fallback | **LLM → IM → face-to-face** is the escalation ladder; meeting = emergency protocol |
| Each person's AI is private | One AI sees the group graph; personal AI is a slice of it |

## 4. The Organism Model

The deepest frame behind every primitive below: **WorkGraph is a synthetic organism for a group**, not a document tool with AI stapled on. A living body doesn't coordinate via memos. Cells receive signals, interpret them locally, and respond within their capability. Chains of local responses produce coherent global behavior — disciplined emergence, not central planning.

This is why the product is categorically different from Notion-with-AI, Slack-with-AI, or Linear-with-AI. Those are document/message tools wearing AI. We are building the organism.

The graph is not a database of projects. It is a **nervous-endocrine-immune system** for a team.

### 4.1 Biological analogues (useful frames, not literal)

- **Nervous system** — fast, discrete signal propagation: IM, WS realtime fanout, urgent conflict surfacing. Action-potential speed.
- **Endocrine system** — slow, diffuse signals: vision commits, thesis broadcasts, drift alerts. Hormone-speed, organization-wide, affects downstream differentiation.
- **Immune system** — membranes (§5.12). External signal validation, source-policy gating, prompt-injection defense. Detects non-self and decides what to internalize.
- **Morphogenesis** — position-dependent differentiation: a node's response profile emerges from where it sits in the graph, not from a role assignment memo.
- **Metabolism** — LLM on the edges: processes incoming signals into the form the next node can act on (translation, clarification, decision extraction).

### 4.2 Signals, not documents

Signals are the transport layer. A signal is context-rich by what it is, where it arrives, when, and at what concentration. Documents are frozen bundles that require a reader to reconstruct meaning — useful as artifacts, not as the live coordination medium.

Everything the team emits — a chat line, a commit, a vision statement, an external-membrane ingestion — is a signal. The LLM-on-edges shapes it into the form the receiving node can process.

### 4.3 Response profiles

Each node (human or agent) has a **response profile**: the set of signals it processes and the signals it emits in return. This is cell differentiation.

- A junior dev responds strongly to implementation-detail signals, emits code-decision signals.
- A CEO responds to market + strategy signals, emits vision signals.
- A product lead responds to customer signals + engineering-capability signals, emits prioritization decisions.
- An agent responds to its specific signal class (requirement text, conflict conditions, external RSS ingest).

Response profiles are **not explicit job descriptions**. They emerge from the node's position in the graph (what it's connected to) + its history (what it has processed and emitted). New commits sharpen the profile over time.

This replaces "role-based" or even "skill-based" routing. Signals flow to nodes whose **profile matches** the signal type, at the graph distance required, with the attention currently available. Role is a crude projection of profile; skill is one input into profile.

### 4.4 Emergent decision chains

No single node "knows" the whole system. Each node decides locally from the signals it receives. Chains of local decisions produce global behavior.

The graph stores the **persistent crystallizations** of those chains — decision nodes, committed theses, checkpoints — so that "why are we doing this" is queryable later. But the live coordination is the signal flow, not the commit log.

**A meeting is what happens when signal propagation fails locally.** It's centralizing, expensive, and necessary only when the normal chain can't produce a decision. A healthy organism needs very few meetings. A body "meets" when it inflames — localized pain, fever — and that's an emergency signal, not a design feature.

## 5. Primitives

### 5.1 Decision-as-crystallization

Signals propagate; decisions crystallize. Every incoming signal is pre-processed: *does this signal demand a decision?* If yes, the decision becomes a first-class graph node — committable, routable, auditable. A chat line is a raw signal; the decision is the crystallization that persists.

**Inbox flips from "unread messages" to "decisions you owe + decisions waiting on you."** Everything else is ambient signal, processed by your personal AI and only surfaced if it changes your response profile's output.

### 5.2 Thesis-commit

New primitive. Each person can commit **"I believe X about this project."** All theses are visible. Divergence between theses is surfaced by AI as a decision that needs resolving, *early* — before it becomes a two-week code disagreement.

The canonical user story: user and partner both have a vision; both fail to describe it vividly; both chat with AI separately to refine; AI explicitly surfaces the difference between their theses as a choice to be made; whoever has license decides.

### 5.3 Pre-commit rehearsal (graph-aware AI)

Before engaging others, every user sharpens their idea with their personal AI. This already happens today with ChatGPT. The difference: **graph-aware AI stress-tests the idea against the actual org** — prior decisions, adjacent theses, likely objections from known edges, conflicting vision commits. It delivers a sharper version because it simulates the real group, not a generic one.

Compounds: if everyone rehearses before debate, debates become fast. All low-quality objections are pre-resolved. Real meetings exist only for genuine divergence.

### 5.4 Signal-affinity routing

Work doesn't route by role ("find a dev") or even raw skill. Signals flow to the node whose **response profile (§4.3)** matches the signal class, at the graph distance required, with the attention currently available. Role is a crude projection of profile onto org-chart columns; with a real graph, profile is directly computable from the node's position, history, and recent emissions.

Role-based routing is acceptable as a fallback when profile data is thin (e.g., new org, new node with no history). As signals accumulate, profiles sharpen and routing gets more accurate.

### 5.5 License = subgraph visibility slice

Not binary member/non-member. Each user sees a slice of the graph — self, relevant projects, adjacent human edges — auto-pruned by AI. A junior dev sees decisions + tasks + context relevant to their active work, not the whole org. The CEO sees the vision layer; a dev sees the task layer of their slice.

The slice is **AI-chosen**, not admin-assigned. Rules are declarative (license class), the slice is derived.

### 5.6 Collaboration SLA — escalation ladder

> **LLM → IM → face-to-face**

Every decision resolves at the lowest level possible. If LLM clarification works, stay there. If the receiver can't commit, surface to IM. Only unresolvable-after-IM escalates to a synchronous meeting.

This is the inverse of today's office, where meetings are the default and docs are the fallback. AI-native means most decisions never touch the calendar.

### 5.7 Translation layer between edges

When work flows PM → Dev, the LLM re-frames the PM's output in dev idiom ("here's what she means in API terms"). Going back, dev concerns re-frame in product terms. Fewer lost-in-translation moments without forcing a shared vocabulary.

### 5.8 Drift detection

AI continuously checks whether committed work matches the committed vision. Old office: drift found in final review (too late). AI-native: flagged on day 2 — "the plan no longer covers checkpoint 3, is that deliberate?"

### 5.9 Silent consensus

Vote-with-your-commits. If 5 of 5 engineers commit code assuming approach A, that's consensus — no meeting. If 4 commit A and 1 commits B, *that* is the decision to surface. The graph infers agreement from behavior, not from explicit polls.

### 5.10 "Why" chain

Every task traces back through decisions → checkpoints → original vision commit. Ask the graph "why are we building this?" and the answer is a chain from the committed history, not anyone's memory.

### 5.11 Ambient onboarding

New hire joins → personal AI walks them through their graph-slice: here's the vision, here's what's been decided, here's what's yours, here's who adjacent edges are. 10 minutes replacing 2 weeks of ramp.

### 5.12 Membranes (external signal ingestion)

The graph can't just track internal state. The org operates in a world of competitor moves, technical shifts, regulatory news, customer signals. Without semi-permeable surfaces to the outside, decisions happen in ignorance — the org converges on a self-consistent but outdated view.

A membrane, like its biological namesake, is **actively selective** — it transports what belongs, rejects what doesn't, and protects the interior. Different membranes for different substance classes: market membrane, tech membrane, regulatory membrane, customer-signal membrane.

**Two ingestion modes:**

- **Agent-driven (push).** Continuous monitors — news feeds, competitor products, market data, arxiv, relevant blogs, regulatory changes — run as agents. They watch, filter via LLM for relevance to the current graph, and propose signal nodes.
- **Human-driven (pull).** A member drops a link, screenshot, forwarded email. Same pipeline: LLM tags and routes.

**Routing is the same machinery as internal work:** graph-aware context matching + license-based subgraph slicing. A competitor launch goes to the product lead's slice; an arxiv paper routes to nodes whose work is adjacent. No broadcasts. No shared inbox firehose. Each person sees only the external signals relevant to their slice.

**Dedup and decay:** multiple ingests of the same signal collapse into one node. Old signals age out unless they link to an active decision, task, or thesis — in which case they persist with provenance.

**How external info couples to other primitives:**

- **Thesis-commit (§5.2)** — a new external signal can *challenge* a committed thesis, surfacing a re-examination as a decision ("competitor just shipped X — is our Y-first approach still correct?").
- **Drift detection (§5.8)** — external market/tech moves trigger drift checks against the committed vision.
- **Pre-commit rehearsal (§5.3)** — graph-aware AI stress-tests ideas against external reality, not just internal state. "Your proposal conflicts with a FCC ruling flagged last week" catches mistakes before they leave the user's head.

**Security boundary (non-negotiable):** external ingestion is the primary prompt-injection attack surface of any AI-first product. Ingested content can propose signal nodes but **never** issues graph mutations directly. All proposed signals require policy-gated LLM evaluation or human approval before they influence routing, state, or decisions.

**Source license:** ingestion respects source. If a member forwards content from a private channel or NDA document, the signal is scoped to whichever subgraph slice the source permission allows — it doesn't bleed into the wider org graph.

## 6. The Canonical Signal Chain

The interaction that compresses the entire organism thesis into ~30 seconds:

1. **Node A emits a raw signal** — a confused framing typed into project IM. Not yet a decision; just emission.
2. **The LLM-on-edge metabolizes the signal** — extracts the latent decision inside it, shapes it into the form node B's response profile can process. Output: `SignalArtifact{ question, frame, raw_text, from: A }`.
3. **Node B receives the signal in both forms** — A's raw text (preserved for trust) alongside the LLM's interpretation (for speed).
4. **B's response profile fires** — one of: `accept` (crystallize as decision) / `counter` (emit a different framing signal; LLM re-metabolizes back to A) / `escalate` (request face-to-face — the organism's pain signal).
5. **An accept crystallizes a decision node** on the graph. Adjacent edges re-route their flow based on the new state. Signal propagation continues.
6. **A's console shows the ripple** via WebSocket — state change propagates back along the graph without A having to ask. The organism has moved.

This single chain demonstrates: humans as differentiated nodes, LLM as metabolic layer on edges, signals as transport, decisions as crystallizations, graph state as ground truth, realtime propagation.

If this works, everything else (org layer, thesis commits, license slicing, drift detection, membranes) is the same primitive scaled up.

## 7. What We Have (from MVP)

The MVP backend is the scaffolding v2 needs:

- ✅ Graph-native state model
- ✅ Multi-user project membership + WS realtime fanout (Redis-ready)
- ✅ Per-agent run logs + trace_id observability
- ✅ `IMAssistAgent` — seed of decision-extraction (currently passive classifier)
- ✅ Clarification loop — seed of "LLM re-asks user"
- ✅ DecisionRow + conflict-resolution flow — seed of decision-as-node

## 8. What's Missing for v2

- ❌ User as graph node (no capability / attention model; `UserRow` is just auth)
- ❌ Org / strategy layer above Project (no vision-commit cascade)
- ❌ Subgraph slicing (license is binary today)
- ❌ Personal AI per user (IMAssist runs on messages, not on behalf of a user)
- ❌ Context-based routing (assignments are manual today)
- ❌ Document co-authoring loop with gap detection
- ❌ IM with LLM interpretation as first-class surface (suggestions are side-chips today, not the main frame)
- ❌ Pre-commit rehearsal UX (no "think with graph-aware AI" surface)
- ❌ Membranes / external signal ingestion (§5.12) — no agent-driven monitors, no human-drop pipeline, no signal nodes on the graph. Org currently has no perception of the outside world.
- ❌ Organism model not reflected anywhere in backend. Current `collab.py` treats messages as first-class; v2 needs a signal-metabolism layer (LLM-on-edge transforming signals into the form the next node's response profile can process).
- ❌ Response profiles (§4.3) — users today are just auth rows; no profile computed from graph position or emission history.

## 9. Relationship to MVP (Phases 1–13)

The MVP is **not** discarded. It is:

- The scaffolding that the v2 primitives will extend
- A valid demo of "delivery coordination on a graph" (the competition demo fixture)
- The smallest version of "graph is the state" that works end-to-end

The MVP demo (event registration) and the v2 demo (two-user LLM-mediated exchange) are **different fixtures**. Both can coexist.

## 10. Tensions with Existing Docs

`AGENT.md` currently constrains:

- "do not build a large custom UI platform" — contradicts v2
- "do not add full RBAC systems" — contradicts subgraph slicing
- "WorkGraph AI is a delivery coordination engine" — narrower than v2

These will be revised once v2 direction is confirmed and the minimum proof (§6) is built.

## 11. Open Questions

- **Does the canonical signal chain (§6) actually feel like the future when built?** This is the first experiment to run before committing to the broader v2 rebuild.
- **Org layer shape** — is there one "Org" entity above Projects, or is it graphs-of-graphs all the way? Affects the data model.
- **Personal AI model** — one model per user with graph-slice context injected per call? Or a shared model with per-user cache? Affects cost.
- **Decision revocation** — can a committed decision be un-committed, or does it require a new opposing decision? Affects audit and revert semantics.
- **The meeting escape hatch** — when AI + IM fail, what's the minimum "schedule face-to-face" affordance? Video? Async voice memo? In-person only?
- **Signal dedup + retention** (§5.12) — when is a signal "the same" as one already ingested? How long do unlinked signals persist before decay? Is there a per-user "signal history" view or only routed-to-decision linkage?
- **Membrane trust model** (§5.12) — what policy gates prevent prompt-injection from ingested web content from issuing graph mutations? Allowlist of sources? LLM-as-firewall pattern? Explicit human confirmation for any ingested-content-triggered action?
- **Response profile computation** (§4.3) — from what inputs is a node's profile computed? Recent emissions? Graph distance to signal class? Explicit self-declaration? Some mix with a decay function over time?
- **Signal vs decision boundary** — at what LLM confidence does a signal "become" a decision proposal vs. stay ambient? Threshold-based? Graph-activity-based? User-configurable?

## 12. Next Step

Build §6 (the canonical signal chain) on top of the MVP backend. Timebox: 1–2 focused days. Do not expand scope until that single chain feels right in the browser.
