# WorkGraph — North Star

**Status:** written 2026-04-18. This is the current product intent. `dev.md`, `PLAN.md`, and `AGENT.md` are MVP-era artifacts; treat them as historical record, not as current spec. `docs/vision.md` remains the depth doc — this file is the short operational distillation.

---

## The one true thing

WorkGraph is **the group's shared operating system, externalized**. A team member talks to it the way they talk to Claude Code: one conversation, one input box, natural language. The system thinks with the user, routes questions to the right teammates, metabolizes their replies back into the user's frame, and crystallizes decisions as graph state. The chat is how humans interact; the graph is what the product actually is. Everything else — tasks, docs, plans, conflicts, meetings — is an emergent artifact of the conversation, not a thing the user manages.

The unit is **the turn**, not the document, the message, or the ticket.

Pre-AI, teams coordinated through frozen snapshots (docs) because the coordination layer couldn't think. Feishu/Notion/Lark unified around that. Post-AI, the coordination layer can think, route, remember, and crystallize. So the unit shifts: frozen snapshot → live routing organ. Our product is that organ.

## Positioning — the first epistemological machine

Ford didn't invent the car; he invented the physical workflow that defined factory work. Pre-Ford, a craftsman's identity was their skill (a wheelwright was a wheelwright). Post-Ford, a worker's identity was their position in the line. The *unit of work* changed. Productivity went up 10x.

Knowledge work today is still pre-Ford. Designers, PMs, engineers still define themselves by craft; Notion/Linear/Slack all assume this frame.

WorkGraph is the first **epistemological machine**: a workflow-definition system for knowledge work where the workflow is primary and workers are nodes in a relationship graph. Identity = sum of edges. When a node's occupant changes, the graph retains continuity and the new person inherits the relationship slot.

The critical difference from Ford's line: physical assembly dehumanized because worker judgment didn't matter (any warm body could tighten bolt #47). Knowledge work inverts this — judgment at the node IS the whole point. The machine is context-preserving, not judgment-replacing. The graph holds context; the human brings taste; the workflow ensures the right signals reach the right judgment at the right time.

Also unlike Ford: profiles *evolve*. As a node emits and metabolizes, the graph learns what they're actually good at. Growth is observable, not subjective. Performance management stops being annual narrative and becomes observable dataset.

This is the positioning that separates us from Notion-with-AI. We're not a better document tool. We're the first system that puts knowledge workflow before knowledge workers, while preserving individual judgment at each node.

**Honest caveat** — some human agency diminishes here. In-system, a person's cognitive work shifts from "invent options" to "pick from surfaced options." If the LLM is very good, rubber-stamping becomes default. Two things prevent collapse: the choice space is built from humans' prior theses and dissent (compounded taste), and counter/reject must remain first-class cheap gestures. Whether this balance holds is empirical, not theoretical.

## Profile as first-class primitive

Each user has a **response profile** — a data structure combining:
- **Self-declared abilities** (submitted at onboarding; aspiration + intent)
- **Observed emissions** (signals metabolized, decisions cited, risks closed, drift detected — accumulated from graph activity over rolling windows)
- **Assigned role** (initialization; can re-frame as profile sharpens)

Both self-declared and observed are displayed; they are not collapsed into one number. Their gap is itself information.

**Role lifecycle:** assigned on hire → profile initializes → signals accumulate → profile sharpens → role can be re-framed ("you are trending toward design from execution"). Management becomes advisory (pointing at profile trends), not directive (slotting people into boxes).

**Handoff = profile transfer.** When Sofia leaves, successor inherits her edges, not her name. Signals she metabolized reroute. Emission style is annotated for context. Continuity of work without continuity of person.

**Performance dataset:** all profile activity is queryable. Managers/HR work from observable history, not memory. v1 augments traditional review; v3+ may replace it (socially complicated — not a v1 concern).

**Hard questions to hold honestly:**
- **Privacy** — broad profile shape public, granular metrics private to self+manager+HR (same split modern perf systems use)
- **Gaming** — measure direction of engagement, not volume; weight by structural impact (risks closed, downstream citations), not turn count
- **Depth vs. volume** — deep-work nodes can be under-signalled; weighting by cited-downstream-decisions mitigates
- **Portable vs. relationship profile** — skill profile portable to a new employer; relationship profile stays with the graph. v3+ concern.

**v1 implementation floor:** `UserRow` gains profile fields (declared abilities + rolling-window signal tallies); profile is used as routing hint (signal-affinity §5.4) even if UI is minimal. Handoff mechanics (R11) use profile transfer. Visible profile rendering is v2.

---

## What it looks like in the hand (day 1 scenario)

Maya (CEO) opens the app. Types: *"what am I missing for the Stellar Drift launch?"*

System answers in-stream (not a dashboard):
> Last playtest report was 3 days ago (Sofia). Aiko flagged a memory leak Monday — unclear if resolved. Two open risks. Ping both for status?

Maya: *"yes."*

System pings Sofia and Aiko inside their own streams, framed for each:
- Sofia sees: *"Maya asked about launch risks. Your last boss-1 rage-quit data — did memento-revive fix it?"*
- Aiko sees: *"Memory-leak ticket Monday — fixed, or still open?"*

Sofia replies in her stream. Aiko replies in his. System metabolizes both and posts a single synthesized turn back in Maya's stream:
> Sofia: revive patch testing Wed, data Thu. Aiko: fixed Mon, shipped Tue. Risk registry updated (1 closed, 1 monitoring).

Zero docs. Zero tickets. Zero meetings. Risk registry on the graph updated itself from the conversation.

That's the product.

---

## What dies (the noise)

These concepts, surfaces, and phases are misaligned with the frame and must be removed or demoted:

**UI / surface:**
- The multi-pane web console (IM pane / Graph pane / Plan pane / Conflicts pane / Decisions pane). **One stream per project. No tabs.**
- "Conflict Center" as a destination page. **Deleted concept.** Conflict is what the LLM-on-edge does while metabolizing; resolutions route to the responsible human as an inline stream card.
- "Clarify Panel" as a destination page. **Deleted concept.** Clarifications are agent-to-human messages in the stream, like any other turn.
- "Tables view" for Tasks / Risks as primary UI. Demoted to `/detail/*` audit routes.
- Plan DAG as primary pane. Demoted to `/detail/plan`.
- Graph visualization as primary pane. **The graph is the state, not a screen.** Demoted to `/detail/graph`.
- Project intake as a dedicated form. **Projects are born from a conversation turn**, not a wizard.

**Conceptual:**
- "Delivery engine" framing (`dev.md` line 41, `AGENT.md`). We are not a delivery engine. We are an organ.
- "Workflow stages" as a first-class concept driving UI state. Stages are derived from the graph when anyone asks; they do not orchestrate surfaces.
- Role-based routing as the primary routing mechanism. Role is a crude projection of response profile (`vision.md §4.3`).
- The human-operates-the-agent-output pattern. If an agent produces output, the output is a signal routed to a specific human in-stream, not a browseable list in a panel.

**Phases (in `PLAN.md`) that are superseded:**
- Phase 8 "Conflict Detection" as a user-facing feature. Backend code stays (conflict detection logic), but the surface is deleted.
- Phase 9 "Decision Resolution" as a destination flow. Acceptance / counter / escalate happens inline in the stream.
- Phase 11 "Web console" as specified — the "messages view / tables view / conflict card view / docs view" split is the wrong shape. The right shape is one stream.

**Docs that must stop being read as current:**
- `docs/dev.md` — MVP-era spec. Archive.
- `PLAN.md` — MVP-era build plan. Archive.
- `AGENT.md` — MVP-era agent contract. Archive and replace with a minimal v2 brief pointing here + at `vision.md`.

---

## What survives

These are load-bearing and keep their current form:

**Backend:**
- Graph-native state model (no `current_stage` field; status derived from graph queries).
- Signal-chain backend (counter / escalate / accept / decision crystallization). Phase 7'/7'' code.
- WS realtime fanout.
- IMAssist (the metabolic layer on-edge) — renamed conceptually to "edge LLM", same code.
- Clarification Agent + Conflict Explanation Agent — **as agents**. Their outputs route to the stream as in-stream cards, never to a panel.
- Multi-user project membership.
- LLM orchestration across 7 agents (per `feedback_llm_orchestration_keep_agents.md`).
- `agent_run_log` + trace_id observability.
- DecisionRow with lineage (`source_suggestion_id`).

**Frontend (survives, but moves):**
- Next.js app shell, auth, session.
- WS client + optimistic update plumbing.
- Existing pane code is not deleted, but moved behind `/detail/*` routes for audit/debug only.

**Concepts:**
- Project as a container. (Open: may dissolve into subgraph slicing later; keep for now.)
- Decision-as-crystallization (`vision.md §5.1`). The punchline of the product.
- Signal chain (`vision.md §6`). The minimum demonstration.

---

## What the v2 surface actually is (tight spec)

One route: `/projects/[id]` → a single full-height conversation stream. Compose box at the bottom. No tabs, no sidebar-of-panels.

Stream items are polymorphic cards, all in one timeline:
- Human turns (from me or from a teammate; teammate turns are LLM-reframed for my context)
- Edge-LLM turns (answers to me, clarifying questions, routing announcements, metabolized replies from other members)
- Decision crystallizations (⚡ inline, with expandable lineage)
- Ambient signals (task created, risk closed, drift flagged, external membrane ingest)

The compose box is LLM-in-the-loop: the edge LLM may interject with a pre-commit rehearsal prompt before a turn is sent, if the framing is ambiguous.

Two modes of the same stream:
- **Team stream** (default) — shared with project members + routed edge LLM
- **Private thinking stream** — just you + your personal LLM, for pre-commit rehearsal; can "commit" a turn from private → team

Archive / audit at `/projects/[id]/detail/*`. Not primary UI.

Display bilingual zh + en, via `next-intl`. Language switches in UI; translation across members is a separate question (see open #3 below).

---

## Documents, knowledge, and edits

**Authorship dies; rendering lives.** Humans don't sit down and write 3000-word PRDs. They have conversations that crystallize into graph state. At sign-off moments (pitch, spec freeze, milestone review), the LLM renders a PRD-shaped document from the graph + stream + KB. Lightweight human edits are welcome; drafting from scratch is not a gesture this product supports.

Traditional documents have **three fates**:

1. **Dies outright** — decision logs, meeting minutes, action items. Replaced by graph-native decision crystallizations with lineage. The "why chain" (`vision.md §5.10`) is the authoritative decision log.
2. **LLM-backed retrieval KB** — tribal knowledge, runbooks, convention guides, third-party docs (Unity wiki, style guides), snapshots of past PRDs, pasted artifacts. This corpus exists for the edge LLM to query, not for humans to browse. Humans contribute by pasting into the stream; LLM ingests; future queries retrieve with citations.
3. **Graph state rendered as views** — tasks, risks, milestones, decisions, plans are first-class graph nodes. Rendered on demand as tables/DAGs at `/projects/[id]/detail/*` (audit) or as inline cards in the stream (when relevant). Not authored, rendered.

The mental model: **one high-dimensional graph, rendered into any slice on demand.** Traditional PM tools maintain N separate sheets (tasks × owner × deadline, risks × severity, roadmap × quarter); humans switch sheets to reassemble a picture. In our model, the graph holds all dimensions; the LLM projects the slice you need, when you ask. The `/status` dashboard is just one pre-computed default slice for when no specific question is in mind.

### Direct edits are signals, not silent state-mutations

Humans can edit the rendered spec (or any task title, decision summary, status line) directly. That's the natural gesture; we don't fight it. But **the edit itself is a signal metabolized by the edge LLM, exactly like a stream turn.** The model is git-diff-style: the LLM reads the diff, classifies the semantic impact, and either auto-applies or surfaces a choice to the editor. Edits never silently mutate the graph.

Four edit kinds, four responses:

1. **Prose polish (no semantic change).** LLM detects stylistic-only diff. Saves as prose override; graph untouched. Zero ceremony.
2. **Semantic reversal of a crystallized decision.** LLM detects the edit contradicts an existing DecisionRow. Stops and asks inline: "this reverses DecisionRow#X — crystallize a new superseding decision, or don't change the graph?" On approval, a new DecisionRow is created with lineage pointing at the superseded one; members' streams light up.
3. **New content the graph doesn't have.** LLM detects prose with no existing graph mapping. Asks: "this reads like a thesis commit / design note / runbook entry — record as [structured kind] or keep as free prose?"
4. **Structural data change** (deadline, assignment, dependency). LLM identifies the impacted graph entities and surfaces cascade choices ("this impacts 3 downstream tasks — cascade their deadlines, or just this one?").

The ceremony of "LLM asks before crystallizing a semantic edit" is not overhead — it is the product's thesis. If direct edits become silent graph mutations, the graph stops being a trustable source of truth and we are back to "humans maintain sheets." The edit pipeline and the stream pipeline are the same metabolism loop with different input modalities.

**v1 simplifications:**
- Any project member can edit anything. License-scoped editing deferred to v2.
- Concurrent editing: last-writer wins on underlying data, but both edits appear as separate events in the stream so nothing is silently lost.
- Type-1 edits save without prompts; types 2-4 always prompt (better to interrupt than to crystallize silently).
- Edits are tracked as revision events in the audit log — audit trail shows who changed what when.

## Users and interaction roadmaps

### Role taxonomy (full)

**Core delivery roles** — emit and route discipline-specific signals within a project:
- **Founder** — vision + strategy + final-call authority (Maya)
- **Lead** — owns a discipline (design, eng, art, QA/community, audio)
- **IC** — executes, learning their profile (James)
- **Multi-project lead** — senior contributor in 3+ projects simultaneously

**Scoped delivery roles** — transient or bounded contribution:
- **Contractor / external collaborator** — hired for specific deliverable, scoped access
- **Consultant / specialist** — one-decision engagement, write-once exit
- **Departing member** — handing off before exit
- **Returning member** — back from sabbatical, context-stale
- **New joiner** — first-day context absorption

**Administrative roles** — cross-cutting, gate the core loop at specific checkpoints:
- **Legal / compliance** — gates decisions with legal/IP/data-handling implications
- **Finance** — gates budget-impact decisions, tracks burn, approves vendor/hire actions
- **HR / People Ops** — owns onboarding/offboarding/transitions; gates role changes
- **Marketing / PR** — parallel stream; depends on feature-set crystallization + milestone dates
- **Sales / BD** — publishing deals, platform relations (where applicable)

**Observer roles** — read-mostly, external-facing:
- **Investor / board** — weekly/quarterly rendered slices
- **Cross-timezone member** — catch-up UX critical
- **External stakeholder** — partner, vendor, regulator

### Key principle for admin roles

Administrative roles sit **outside the core delivery loop but gate it at specific points**. A decision with legal implications cannot crystallize until legal approves; a hire cannot finalize until finance approves. This is implemented via the existing signal chain: a `decision`-kind suggestion routes to the gating admin as a block-to-crystallize signal before acceptance. The decision exists in "proposed, pending legal" state on the graph; on approval, it crystallizes with the approval attached in lineage.

Admin roles are members of multiple projects **independently**. The `/` home aggregates across their memberships — 3 projects' pending lists merged by recency — but no cross-project graph edges exist. This preserves the "no relationships among projects" constraint while supporting real cross-project attention.

### Quiet period — corrected framing

Quiet period is NOT "no assignments." It is: the user has an ongoing task, is mid-execution, and no new signal is demanding their attention. The home must show **pending signals AND active work context**:

- **Top:** signals needing your response (empty when quiet)
- **Below:** your current active task, its status, upstream context (what decision spawned it, why), downstream (what depends on it), adjacent teammates' status in related areas, edge LLM's offer to help refresh status or rehearse next step

The home is **never empty** because the user's cellular context is always populated. This is consistent with the organism/response-profile frame — a node always has context from its graph position, even when no new stimulus is arriving.

Active task is identified by: user's explicit focus setting, or inferred from recent commits / turns / edits. Inference is good-enough for v1; explicit setting is a polish affordance.

### High-impact roadmaps (frequency-ordered)

| ID | User × Condition | Frequency | Load-bearing UX |
|---|---|---|---|
| R1 | Founder, morning routine | daily | `/` shows pending-across-projects, jump to specific turn |
| R2 | Lead, interrupted reply | multi-daily | Notification → deep-link to specific turn, thumb-compose |
| R3 | IC, getting assigned | daily | Same as R2 |
| R6 | End-of-day check | daily | `/` summary: resolved today, pending tomorrow |
| R14' | Any user, quiet period | continuous | `/` shows active-task context when pending is empty |
| R10 | Cross-timezone catch-up | daily (distributed teams) | LLM-rendered overnight summary, not turn replay |
| R15 | Mobile interruption | daily | Mobile-native stream, thumb-scale compose |
| R19 | Legal/finance gated approval | irregular | Gated-decision flow: crystallize blocked until approval |
| R20 | Finance budget review | weekly-monthly | Dashboard is actually useful here; read-only slice |
| R22 | Marketing, launch-path sync | weekly → daily at launch | Stream + rendered feature-freeze milestones |
| R4 | Lead, escalation / fire | weekly | Paste URL + route to multiple streams |
| R11 | Departing handoff | per-exit | LLM-rendered handoff doc from graph slice |
| R12 | Postmortem / retro | per-milestone | LLM-rendered lineage; human annotates |
| R16 | Observer weekly check | weekly | Rendered slice only, no stream access |
| R9 | Contractor, scoped engagement | per-hire | Scoped license, revokes on completion |
| R17 | Consultant, one-decision write | irregular | Lineage-first entry point |
| R5 | New joiner, Day 1 | per-hire | Ambient onboarding over graph slice |
| R7 | Project boot | monthly-quarterly | Dead-simple modal (not LLM dialogue) in v1 |
| R13 | Incident / paged | rare, critical | Mobile native, OS push integration |

### Problems surfaced (v1 scope implications)

**Must be in v1:**
1. **Catch-up summaries** for any absence > a few hours (R10, R11, R14'). LLM-rendered, not turn replay.
2. **Scoped license model** — 3 tiers minimum: full member / task-scoped / read-only observer (R9, R16, R17, R19). Full subgraph slicing can wait for v2.
3. **Mobile-native stream + compose** (R2, R13, R15). Not shrunk-desktop.
4. **Notification → deep-link routing** as the real entry point. Most sessions don't start at `/`.
5. **Active-task context on `/`** to solve R14'. Home is never empty.
6. **Gated-decision flow** — some decisions wait for admin approval before crystallizing (R19, R20). This is a signal-chain variant we must implement.
7. **Attention triage at scale** — LLM priority ranking when streams exceed ~20 turns/day. Needs-you vs. FYI, collapsible FYI turns.
8. **Cross-project aggregation at `/`** without cross-project graph. Union of memberships, merged by recency.

**v2 polish:**
- Full subgraph slicing
- Private thinking stream (`vision §5.3`)
- Devil's-advocate mode
- Render caching
- Rich mobile features (offline drafts, OS-native push integration)
- Cross-member auto-translation

## Resolved product questions (answered 2026-04-18)

1. **Offline work stays offline.** The platform does NOT compile git, host repos, or run a coding engine. It does NOT replace Unity, Figma, or any external creative tool. The platform **captures status** about offline work, and optionally ingests finished artifacts into a KB. Specifically:
   - Git status can be linked (webhook or manual paste of commit/PR/branch references). The platform tracks what moved, not the code.
   - Docs can sometimes be authored in-stream (short decisions, summaries, status updates). Longer creative artifacts stay in their native tool; their URL and status are referenced.
   - Unity/Figma/DCC artifacts stay in their tools. The stream notes that a scene/asset was updated, by whom, for which task. Optionally, exported versions can be ingested into the KB for search/reference.
   - The **submit gesture** in v1: the compose box accepts text + paste of anything (commit hash, URL, file path, doc link). Edge LLM parses and files it — "task X advanced by commit abc123", "Unity scene ship/hull.unity updated by Diego", "decision doc linked: notion.so/...". If ambiguous, the LLM asks where it belongs. No separate "upload" button; paste-to-dispatch.

2. **Role-based routing in v0, response-profile in v1.** `UserRow` keeps role for now. Profile computation deferred.

3. **Each user picks a display language.** UI i18n only in v1 — chrome, buttons, system turns localized per user. Message content from other humans is left as-authored (not auto-translated). Cross-member auto-translation is a v2 polish, not v1.

4. **Team stream only in v1.** Private thinking stream deferred to v2.

5. **Kill the intake wizard.** Projects are born from a sentence typed in the personal home stream at `/`. A lightweight **project dashboard** survives at `/projects/[id]/status` — read-only status view (members, active tasks, open risks, recent decisions, linked external artifacts). Actions still happen in the stream; the dashboard is an X-ray, not a control panel.

6. **Main agent voice + attributed sub-agents.** The edge LLM is the primary voice in the stream. Clarification, conflict, planning, and other specialist agents post as attributed sub-turns when they contribute (e.g., `🧠 edge` vs. `❓ clarifier` vs. `⚖ conflict`). Mirrors Claude Code's main-agent + sub-agent pattern.

---

## Streams as the unifying primitive

Everything in the product is a **stream**. A stream has membership, an optional project anchor, and a privacy setting. Same renderer everywhere; LLM verbosity varies by type.

| Type | Membership | Anchor | LLM behavior | v1? |
|---|---|---|---|---|
| **Personal project stream** ★ primary | one user + their sub-agent | project | Active conversational — answers, clarifies, proposes routing; the main surface | **required — post-Phase-K rebuild** |
| **Team room stream** (secondary) | all project members | project | Passive shared log; used when group genuinely needs to co-present (rarely the default; still valuable for emergencies and group presence) | ✓ (repurposed from v1 "project stream") |
| **DM stream (1:1)** — dual purpose | 2 members | none | (a) Urgent bypass when routing latency is unacceptable; (b) Runtime log — LLM-routed flows between these two humans are mirrored here as shared history | ✓ |
| **Rehearsal stream** | 2 members, project-scoped private | project (private) | Active — devil's advocate; offers "publish to project?" on decision shape | v2 |
| **Group stream (3-10)** | 3-10 members | optional | Passive, same wake-on-signal as DM | v2 |

**Architectural correction (2026-04-18, post-Phase K):** the v1 build treated the per-project "team stream" as the primary surface and deferred per-user-with-sub-agent conversation to v2. That was wrong. The correct primary surface in every project is **the user's private conversation with their own sub-agent**. Team room and DM are secondary — kept for what they genuinely serve, but routing through sub-agents is the default, more efficient, cheaper path.

## Sub-agent and routing architecture

**One sub-agent per user, globally.** Each human has exactly one sub-agent identity — Maya's agent is the same across all Maya's projects. Consistent voice, consistent memory, accumulated profile. When a user opens `/projects/[id]`, they see their global sub-agent in that project's context (graph state, KB slice, recent activity for that project). This encodes the thesis that workers are bearers of their production relationships — and so are their agents.

**Parent agent** — cross-user routing hub. No UI. Dispatches signals between sub-agents, maintains routing state, ensures reply flows close the loop.

### The canonical interaction

1. **Maya types in her personal project stream.** "Should we drop permadeath given the rage-quit data?"
2. **Maya's sub-agent metabolizes.** Reads graph + KB slice + her recent history. Produces one of:
   - **Answer** — from graph/KB ("Sofia's playtest shows 40% rage-quit on boss 1; last permadeath decision was D#12 three weeks ago")
   - **Clarify** — asks back ("Do you mean drop entirely, or only for bosses?")
   - **Route proposal** — "This is a design call. I can ask Raj with your framing, attaching: Sofia's playtest, Aiko's memory-leak constraint, the last permadeath thesis. Want me to?"
3. **Maya clicks "Ask Raj"** (or declines, or picks a different target)
4. **Parent agent dispatches to Raj's sub-agent.** Raj's personal stream receives a routed-inbound turn
5. **Raj's sub-agent presents the inbound as a rich option card** — see "Option design" below. Raj replies with one click or types custom
6. **Reply flows back** through parent → Maya's sub-agent → Maya's stream as a framed reply card. Maya accepts → decision crystallizes; or counters → Raj sees the counter with his framing attached
7. **Both Maya and Raj see this flow mirrored in their 1:1 DM** (dual-purpose DM as runtime log), where they can also have urgent side-conversations

Humans never see each other's raw typed text unless they open the team room explicitly. They see metabolized, context-framed signals with rich context.

### Option design for routed inbound

When a routed inbound lands in Raj's stream, the sub-agent does NOT offer simple yes/no. Each option shows:

| Field | Purpose |
|---|---|
| **Label** | Short action name ("Drop permadeath") |
| **Background** | Graph/KB snippets informing this option (Sofia's playtest, prior decision D#12, Aiko's memory-leak) |
| **Reason** | Why the sub-agent surfaced this option (removes churn / preserves stakes / forces sync) |
| **Trade-off (bargain)** | What it costs (2-week un-build / new system to maintain / calendar time) |
| **Weight** | Sub-agent's assessment strength, 0–1, rendered as bar or chip |

Raj picks in one click, types custom, or picks + modifies. Goal: quick informed decision without re-reading Maya's context, without a sync meeting. This is the core efficiency claim — sub-agent compresses "I explained to Raj" into option chips so Raj decides in 30 seconds.

### Routing primitive (data model)

New entity: **RoutedSignalRow** (persisted on the graph).
- `source_user_id`, `target_user_id`, `source_stream_id`, `target_stream_id`
- `framing` (sub-agent's summary of what the source wants)
- `background_json` (context snippets with provenance)
- `options_json` (list of `{label, kind, background, reason, tradeoff, weight}`)
- `status` (`pending` | `replied` | `accepted` | `declined` | `expired`)
- `reply_json` (target's pick + custom text + time-to-respond)
- Timestamps + trace_id for lineage

Each routed signal also appends summary turns to the source↔target DM so the pair has a shared log.

### Primary surface after rebuild

`/projects/[id]` default view = **user's personal conversation with their sub-agent, scoped to this project**.
Secondary affordances at top of page:
- **[Team room]** — click to enter the shared team stream (used rarely; emergencies or group presence)
- **[DMs]** — per-pair history (urgent bypass + shared routing log)

Everything else (decisions, tasks, graph) remains audit views at `/detail/*`.

## Architectural correction Q (2026-04-18, post-dogfood)

The initial v2 build treated the personal stream as a routing inbox. User feedback after dogfooding: **this is wrong**. Corrections now baked into the spec:

### Q.1 Personal stream = working + learning space, not inbox

The sub-agent's default mode is **conversational**, not routing-centric. Most turns should be:
- **Answer** from graph/KB (factual / recall)
- **Clarify** when the user's framing is ambiguous
- **Tool-call** — the agent can execute skills (KB search, decision-history query, plan proposal, risk scan, drift check) as visible tool calls, like Claude Code runs `Grep` or `Read`. Results thread back as tool-result turns.
- **Argue back** when the user's opinion conflicts with graph state or another member's thesis — the agent surfaces the conflict and gives the user a choice to keep arguing OR route.

**Routing is ONE available action, not the default.** The agent only proposes routing when: target expertise is genuinely required AND the user hasn't indicated they want to think alone first, OR the user's proposal requires a gate-keeper's sign-off.

### Q.2 Routed-inbound lives OUTSIDE the personal stream

When Raj routes to Aiko, the inbound **must not interrupt Aiko's own agent conversation**. It appears as:
- A **badge** in the sidebar or header (number indicator)
- Click opens a **drawer** (right-side slide-in) or **popup** with the rich-options card
- Resolve → status updates → drawer closes → Aiko's stream is undisturbed

This preserves the "personal working space" thesis — your sub-agent conversation is protected context; routed asks are interrupts you consume on your own schedule.

### Q.3 Options are replies, never re-routes

The routed-inbound options surface must never contain a "route this further" action. Options are strictly **reply kinds**: `accept` / `counter` / `escalate` / `custom`. The target is replying to the source, not re-dispatching.

### Q.4 Source-side reply surface is symmetric

When the target replies (e.g., "ask for more info"), the source's reply card must have symmetric affordances:
- **Accept** the reply as final
- **Counter-back** with more info / different framing (triggers another round)
- **Escalate** (request sync)
- **Reply custom** (free-form follow-up)

Currently the frontend RoutedReplyCard only handles the accept case — bug.

### Q.5 Sidebar-first global navigation

Standard chat-tool UX:
- **Left sidebar** (global, always visible): Home + list of projects (each project expandable into: personal stream, team room, status, KB, renders) + DM list + notification badges
- Main pane: the selected view
- Replaces current top-tab approach inside projects

### Q.6 KB / wiki is user-facing, not just LLM corpus

Earlier v1 decision deferred `/kb` browsing to v2. That was wrong. Add browseable `/projects/[id]/kb` page listing ingested artifacts (membrane signals, pasted docs, tribal-knowledge entries) with search + view + light editing.

### Q.7 Render triggers must be visible

Rendered artifacts (postmortem, handoff) exist at `/projects/[id]/renders/[slug]` but nothing in the UI triggers them. Add visible buttons on `/projects/[id]/status` or in project settings: "📝 Generate postmortem" and "📝 Generate handoff for …".

**Why 1:1 DM ships in v1:** we aim to replace Lark / Feishu / DingTalk for work coordination. Without DM, users keep Lark open for quick alarms, urgent pings, and direct asks — and the "close the old tool" thesis breaks. DMs won't be heavily used (project streams are where real work lives), but the surface must exist to demo complete coverage.

**Scope of v1 DM (minimum demoable):**
- 1:1 only (group streams deferred)
- Standard notification behavior. No Lark-style "ding" force-ring in v1; OS push is enough.
- LLM passive until a decision-shape or project-relevant signal appears — then wakes, offers to publish to the relevant project stream. Decision ceremony stays explicit.
- Basic affordances: send message, read receipt (silent), presence indicator on profile cards (online/away), emoji reactions on turns, file/screenshot paste-ingest (same as project stream).
- No voice, no video, no call — meeting is the pain signal (`vision §4.4`); if you need voice, you've already failed at async.

**v2 DM polish:** priority/alarm flag (phone ring), group streams, cross-project topical channels (maybe; probably never).

## What we replace vs. coexist with

**Replace (center of gravity moves to us):**
- Project coordination, cross-member questions, decisions, status
- Team streams, project-scoped DMs, pre-commit rehearsal
- Most of what Lark / Feishu / DingTalk / Slack / Teams are used for in a work day

**Coexist with (companies can keep their existing tool):**
- Personal social chat, coffee, banter
- Company-wide HR announcements, all-hands comms
- Deep-integration OA workflows (approvals, forms, signature flows — if the company is wired into Feishu OA)

We don't force exclusivity. A team can use us as their sole work tool if they want, or keep Lark open for non-work. Our bar: their work-coordination center of gravity moves to us and they feel their day is better.

## v1 page inventory (locked)

Every route the v1 app exposes. No page not on this list.

### Auth (2 pages)
- `/login` — credentials
- `/register` — credentials + display language pick (zh/en)

### Personal surface (2 pages + 1 modal)
- `/` — personal home. Sections (in order): pending signals needing your response (across all your projects, merged by recency), gated approvals if you're an admin role, active-task context when pending is empty (current task + status + upstream why + downstream dependents + adjacent-teammate status), project list. `+ new project` button opens a dead-simple modal (name + description + invite members). No cross-project graph edges.
- `/settings/profile` — your self-declared abilities, display language, notification preferences. View your own observed profile summary (v2 enriches this).

### Project primary surface (3 pages)
- `/projects/[id]` — team stream. Main work surface. Polymorphic cards (human turns, edge-LLM turns, attributed sub-agent turns, decision crystallizations, ambient signals, gated-approval proposals, catch-up summaries at top after absence). Compose box with LLM pre-commit rehearsal interjection. Default cursor on newest routed-to-you turn.
- `/projects/[id]/status` — read-only dashboard. Members + presence, active tasks, open risks, recent decisions, linked external artifacts (git, docs). First-use surface for finance role; audit for everyone else.
- `/projects/[id]/settings` — members, role assignments (including gated admin roles: legal, finance, HR approvers), scoped license for contractors/observers, integrations (git webhook endpoint, KB ingestion).

### Project audit (demoted, accessible from `/detail` nav menu only)
- `/projects/[id]/detail/graph` — graph viz
- `/projects/[id]/detail/plan` — DAG
- `/projects/[id]/detail/tasks` — task table
- `/projects/[id]/detail/risks` — risk table
- `/projects/[id]/detail/decisions` — decision table with lineage
- `/projects/[id]/nodes/[nodeId]` — deep-link view for any graph node (decision, task, risk, thesis) with full lineage render. Shareable URL. Used by R17 (consultant linked to specific decision), audit citations, stream-card expand.

### Rendered artifacts (generated on-demand, cached)
- `/projects/[id]/renders/[slug]` — LLM-rendered documents: PRD snapshots, postmortems (R12), handoff docs (R11), compliance slices (R23), observer weekly briefs (R16). Timestamped, regenerable. Human can lightly edit; edits flow through the edit-as-signal pipeline.

### Utility
- `/search` — global search across streams, decisions, KB; or as a keyboard-shortcut modal overlay on any page (ctrl/cmd+K). One of these, not both.
- `/404`, `/500` — error pages

### DM streams (1:1 only in v1)
- `/streams/[id]` — ad-hoc 1:1 DM stream. Same renderer as project stream, no project-anchor cards (no status dashboard, no settings menu). LLM passive until decision-shape detected.
- Home `/` gains a **streams section** alongside the project list: recent DMs ordered by activity.
- **New-DM affordance:** from any user's profile card in any stream, "Message [name]" opens or creates the 1:1 stream. Also `/` has a "+ new message" action.

### Explicitly NOT in v1
- No group streams (3-10 ad-hoc) — v2
- No cross-project topical channels — probably never
- No voice/video/call — meeting is a pain signal, not a feature
- No `/notifications` page — notifications funnel into `/` (pending section) + OS push for deep-link
- No `/approvals` — admin approvals are part of `/` pending section, filtered by gate type
- No `/kb` — KB is LLM-facing corpus, not a browseable page in v1. Inspection deferred to v2.
- No `/pulse` cross-project aggregator — `/` already aggregates; no separate dashboard
- No project-creation wizard — replaced by modal on `/`
- No onboarding page — ambient onboarding overlays the new member's first visit to `/projects/[id]`
- No private thinking stream page — v2 polish
- No Lark-style "ding" force-ring alarm — OS push is enough for v1; true alarm is v2

### Total v1 page count
12 unique routes + 1 modal + 1 global search + 2 error pages. Plus demoted `/detail/*` (existing Phase 11 code kept, moved to audit nav).

---

## Next step (locked)

1. Archive banner on `dev.md`, `PLAN.md`, `AGENT.md` pointing here.
2. Write `PLAN-v2.md` with v1 build phases.
3. Scaffold: `next-intl` (zh + en, per-user pick), new `/projects/[id]` route, stream renderer, compose box, demote existing panes to `/detail/*`.
4. Route clarification + conflict agent outputs as in-stream cards with sub-agent attribution.
5. Build `/projects/[id]/status` dashboard (read-only).
6. Build `/` personal home with project-creation-from-sentence.
7. Dogfood in two browsers with the Moonshot demo, verify the canonical signal chain in the new surface.
