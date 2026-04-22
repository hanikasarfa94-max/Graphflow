# WorkGraph — Architecture (image-gen friendly)

**Single page, visually structured, current as of V4.**
One-line purpose: an AI-native operating graph for a team — humans are nodes, sub-agents metabolize signals on edges, the graph is the shared nervous system.

---

## 0. Whole-system layout (one diagram)

```
┌──────────────────────────────────────────────────────────────────────┐
│                         BROWSER CLIENT                               │
│  Next.js 15 · React 19 · next-intl (zh / en)                         │
│  Chat-stream layout: user turns right, agent turns left flowing.     │
│  Cards only for structural events (⚡ decision, drift, scrimmage).    │
└──────────────────────────────────────────────────────────────────────┘
                     ↕  HTTPS + WebSocket
┌──────────────────────────────────────────────────────────────────────┐
│                       EDGE (per-user sub-agent)                      │
│  Each human has ONE sub-agent, global across projects.               │
│  Consumes user's license-scoped graph slice + recent emissions.      │
│  Produces: answer · clarify · tool-call · argue-back · silence.      │
│  Every reader-facing claim carries structured citations.             │
└──────────────────────────────────────────────────────────────────────┘
                     ↕  routed signals
┌──────────────────────────────────────────────────────────────────────┐
│                  PARENT AGENT (routing hub, no UI)                   │
│  Dispatches signals sub-agent → sub-agent.                           │
│  Pre-answer: target's sub-agent drafts reply without waking target.  │
│  Scrimmage: two sub-agents debate 2-3 turns before involving humans. │
└──────────────────────────────────────────────────────────────────────┘
                     ↕  LLM calls (provider-agnostic)
┌──────────────────────────────────────────────────────────────────────┐
│  DeepSeek (dev/prod) · OpenAI-compatible · swappable to Kimi/Doubao  │
│  Prompt-cached, observability via trace_id + agent_run_log.          │
└──────────────────────────────────────────────────────────────────────┘

     ↓ all of the above mutates / reads from ↓

┌──────────────────────────────────────────────────────────────────────┐
│                       THE GRAPH  (shared state)                      │
│  SQLite (prod) · aiosqlite · Alembic migrations 0001-0013            │
│  No current_stage column · the graph IS the state.                   │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 1. Stream types (four, single primitive)

```
╔═══════════════════╦════════════════════════╦══════════════════════╗
║  personal  ★      ║  project (team room)   ║  dm (1:1)            ║
║  primary surface  ║  shared shallow log    ║  urgent bypass       ║
║  user + sub-agent ║  all members           ║  2 humans            ║
║  LLM active       ║  LLM passive           ║  LLM passive         ║
╚═══════════════════╩════════════════════════╩══════════════════════╝
(rehearsal + group streams: deferred v5)
```

---

## 2. The 13 load-bearing primitives (vision §5)

```
5.1  Decision crystallization ⚡      pending chat line → graph node
5.2  Thesis-commit                    "I believe X" as first-class edge
5.3  Pre-commit rehearsal             stress-test draft vs graph
5.4  Signal-affinity routing          profile × graph-distance × attention
5.5  License = subgraph slice         full / task_scoped / observer
5.6  Collab SLA ladder                LLM → IM → face-to-face
5.7  Translation between edges        PM-speak ↔ dev-speak on transit
5.8  Drift detection                  vision vs current reality
5.9  Silent consensus  (NEW V4)       behavior-inferred agreement
5.10 Why-chain                        decision → parent decisions → vision
5.11 Ambient onboarding (NEW V4)      day-1 narrated slice tour
5.12 Membranes                        external signal ingestion + firewall

+ V3 trust floor
   · License-aware reply lint (never leak across tiers)
   · Leader escalation (scoped agent → full-license owner draft)
   · Citations on every LLM claim
   · Dissent rows + outcome validation
   · Agent-vs-agent scrimmage
```

---

## 3. Agents (13 specialized LLM services)

```
┌──────────────────┬──────────────────────────────────────────────────┐
│ edge (per user)  │ conversational · tool-calling · routing          │
│ clarification    │ needs-more-info questions                         │
│ conflict         │ detected conflict → 2-3 resolution options       │
│ planning         │ requirement v+1 → task DAG + milestones          │
│ drift            │ vision vs produce deltas (auto-trigger)           │
│ membrane         │ external signal → tagged proposal + injection gate│
│ render           │ graph slice → postmortem / handoff markdown      │
│ pre-answer       │ skill-anchored target-side preview               │
│ scrimmage        │ multi-turn two-agent debate                      │
│ silent-consensus │ scanner: N members acting → proposal             │
│ dissent          │ outcome validator → supported/refuted            │
│ onboarding       │ day-1 slice narrator                              │
│ meeting-ingest   │ uploaded transcript → proposed signals           │
└──────────────────┴──────────────────────────────────────────────────┘
```

---

## 4. Graph state (ORM rows, V4 full set)

```
 CORE                 │ COLLABORATION        │ INTELLIGENCE          │ V3/V4 EXTENSIONS
 ─────────────────────┼──────────────────────┼──────────────────────┼────────────────────────
 ProjectRow           │ StreamRow            │ DecisionRow          │ LicenseAuditRow
 RequirementRow       │ StreamMemberRow      │ CommitmentRow        │ DissentRow
 UserRow (+profile)   │ MessageRow           │ ScrimmageRow         │ SilentConsensusRow
 ProjectMemberRow     │ RoutedSignalRow      │ RiskRow              │ OnboardingStateRow
 GoalRow              │ IMSuggestionRow      │ MilestoneRow         │ MembraneSubscriptionRow
 DeliverableRow       │ NotificationRow      │ DriftAlertRow        │ MeetingTranscriptRow
 TaskRow              │ CommentRow           │ ConflictRow          │ KbFolderRow
 DependencyRow        │ AssignmentRow        │ StatusTransitionRow  │ KbItemLicenseRow
 ConstraintRow        │                      │ HandoffRow           │
 MembraneSignalRow    │                      │ SkillRow             │
                      │                      │ AgentRunLogRow       │
```

---

## 5. Canonical signal chain (the 30-second demo)

```
Raj (human)        ─┐
  "drop permadeath?"├─→ Raj's sub-agent  ─┐
  draft             │   (edge LLM)        │
                    └─ license-scoped slice│
                                           ├─→ Parent agent
                                           │    (routing hub)
                                           │
   Aiko's sub-agent ←────────────────────┐│
   drafts reply options                   ├┘
   (NOT "Ask Aiko" — reader-identity      │
    injected; self-exclusion enforced)    │
                                          ▼
   Aiko's routed-inbound card ─→ pick option ─┐
   (drawer, no interrupt to her own stream)   │
                                              ▼
                          reply flows back ─→ Raj's personal stream
                                              with CitedClaims
                                              dedup'd (no twin cards)
                                              │
                                              ▼
                   Raj accepts  →  ⚡ DecisionRow crystallizes
                                    + ripple via WS to all members
                                    + DissentRow slot opens
                                    + StatusTransitionRow logged
                                    + why-chain queryable
```

---

## 6. Deployment topology (prod)

```
[ User ] ─── https ───→ Cloudflare edge ─── tunnel ───→ VPS
                                                          │
                                         127.0.0.1:8080  ▼
                                        ┌──────────────────┐
                                        │   nginx:1.27     │
                                        └────┬─────────┬───┘
                                    / (HTML) │  /api    │ /ws (WebSocket)
                                             │          │
                                  ┌──────────▼──┐   ┌──▼──────────┐
                                  │ web :3000   │   │ api :8000   │
                                  │ Next.js 15  │   │ FastAPI     │
                                  │ (SSR + RSC) │   │ aiohttp WS  │
                                  └─────────────┘   └──┬───┬──────┘
                                                        │   │
                                                        ▼   ▼
                                               SQLite volume  Redis (fanout)
                                                        │
                                                        ▼
                                               DeepSeek HTTPS
```

---

## 7. Stats (current, for captions)

```
· 13 migrations (0001-0013)
· 13 specialized LLM agents
· 13 load-bearing primitives
· ~92,500 LOC (55K Python + 35K TypeScript + 2K CSS/JSON)
· ~8K LOC of markdown spec
· 340+ backend tests (1 known intra-module flake)
· Bilingual zh + en (next-intl)
· Single-node VPS deploy, 4 GB RAM
```

---

**For image generation prompting:** treat each `┌───┐` box as a visual node, each `↔ / ↕ / →` as an arrow, each indented list as a label group. Style cue: technical architecture diagram, clean lines, monospace labels, minimal color (one accent for crystallization / decision events, one muted for ambient signals).
