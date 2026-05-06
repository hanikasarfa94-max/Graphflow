<p align="center">
  <img src="apps/web/public/brand/logo-mark.png" alt="GraphFlow" width="120" />
</p>

<h1 align="center">GraphFlow</h1>

<p align="center">
  <strong>Coordination as a graph, not a document.</strong>
  <br />
  Group-layer collaboration. Built for the AI era.
</p>

<p align="center">
  <a href="https://graphflow.flyflow.love"><img src="https://img.shields.io/badge/live%20demo-graphflow.flyflow.love-2563eb" alt="Live demo" /></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License" /></a>
  <a href="./README.zh-CN.md"><img src="https://img.shields.io/badge/中文-README-red" alt="中文" /></a>
</p>

<p align="center"><a href="./README.zh-CN.md">中文 README →</a></p>

---

## The thesis

For the past decade, collaboration tools have iterated on the same premise: **the unit of information is the document.** Notion, Lark, Slack, and the rest unified around it. That assumption made sense pre-AI, when only frozen snapshots could carry shared meaning across multiple people.

AI changed the substrate. The coordination layer itself can now think, route, remember, and crystallize. So the unit of information has to shift: **from document to turn.** Every conversation, every routed question, every accepted decision is a node or an edge on a graph. Documents become emergent artifacts of those turns — not inputs.

GraphFlow is the first **epistemological assembly line** for knowledge work: workflow is primary, people are nodes that carry judgment, and the AI layer guarantees context-preservation between them.

> "Ford didn't invent the car. He invented the workflow that made workers nodes in a line. Productivity went up 10×.
> Knowledge work today is still pre-Ford."

---

## Live demo

**Site:** https://graphflow.flyflow.love
**Demo project:** Moonshot Studios — a 6-person indie game team, four weeks from launch, navigating Boss-difficulty / Switch-performance / permadeath tradeoffs.
**Demo accounts** (`raj_zh`, `aiko_zh`, `maya_zh`) — password is in `scripts/demo/seed_moonshot.py`.
**Demo script:** [`docs/demo_script.md`](docs/demo_script.md) — 8 scenes, ~7 minutes.

The 90-second core narrative: Raj types a question into his personal stream → his sub-agent recognizes it as routable → routes to Aiko with structured options → Aiko picks one in 4 seconds → Raj accepts → ⚡ decision crystallizes into the graph with full lineage. **Zero meeting, zero document written.**

---

## Three graphs

GraphFlow models a team as the intersection of three graphs:

| Graph | What it holds | What it answers |
|---|---|---|
| **World Graph** | shared context, knowledge, decisions, risks, constraints | "what does the team know / has decided / is at stake?" |
| **Org Graph** | members, role inheritance, capability evidence (Trust Ladder), routing trust | "who's responsible? who's trusted on this?" |
| **Work Graph** | tasks, routing edges, handoffs, reviews, state transitions | "what's in flight? where is it? who is it on?" |

All three intersect at every member's **personal stream** — the only surface they actually interact with. The graph is the product. The chat is just how humans interact with it.

---

## Core primitives (V1 shipped)

- **One sub-agent per member.** Cross-project, persistent. Carries the user's context, calls skills, drafts replies, proposes routes.
- **Routing replaces meetings.** A question + 2–4 structured options + weights. Answered in seconds. Persisted as an edge with full lineage.
- **Decision crystallization (⚡).** Every accepted decision becomes a permanent graph node with sources, options, rationale, and what it touched. Three months later, "why did we pick this?" returns a causal chain — not someone's memory.
- **Membrane is the single boundary.** Every group-scope write — KB entries, task promotion, decision crystallization, room creation, skill_tag changes, member invites — passes through the same review gate. New write kinds extend an enum, never bypass.
- **Citations everywhere.** Every claim a sub-agent makes carries structured citations to graph / KB nodes. Uncited claims render dimmer, never get hidden.
- **Trust Ladder (5 levels).** Capability is a projection over evidence — `declared` (self) → `role` (project) → `observed` (graph activity) → `validated` (accepted reply / completed task) → `trusted` (≥3 validated rows). Skills are never invented from row text.
- **Dissent as first-class.** Members can record structured dissent on any decision. Outcomes track whether dissents were `supported` / `refuted` / `still-open`. Judgment quality becomes observable over time.
- **Silent consensus.** When ≥3 members act consistently around a deliverable in a 7-day window with no dissent, the system proposes a consensus to be ratified.
- **Agent-vs-agent scrimmage.** Before a routed question reaches a human, the two sub-agents debate 2–3 rounds. Convergence → directly proposes a decision. Divergence → human gets the structured disagreement, never a blank question.
- **Active membrane ingestion.** External signals (RSS / pasted URLs / web search / cron) flow through the membrane with prompt-injection defense. Always `proposed` until a human confirms.
- **Meeting transcript metabolism.** Upload a transcript (Lark, Zoom, raw text) and the membrane extracts decisions / tasks / risks / positions as `proposed` graph candidates — never auto-applied.

---

## Tech stack

| Layer | Choice |
|---|---|
| Web | Next.js 15 (App Router), React 19, TypeScript strict, next-intl (zh + en) |
| API | FastAPI · Python 3.11 · SQLAlchemy + aiosqlite |
| Realtime | FastAPI WebSocket + Redis pub/sub |
| Storage | SQLite (single-node), 33+ ORM tables, 13+ Alembic migrations |
| LLM | DeepSeek (OpenAI-compatible) — provider-agnostic prompts |
| Visualization | React Flow (graph canvas), PixiJS (rare animation moments) |
| Deploy | Single VPS · Cloudflare Tunnel · Nginx · Docker Compose |
| Observability | Structured logging, `trace_id` end-to-end, `agent_run_log` per LLM call |

13 specialized LLM agents handle different responsibilities: `EdgeAgent` (sub-agent), `MembraneAgent` (signal classification + injection defense), `MembraneReviewer` (semantic review), `ClarificationAgent`, `PlanningAgent`, `DriftAgent`, `RenderAgent`, `PreAnswerAgent`, `ConflictExplanationAgent`, `IMAssistAgent`, `MeetingIngestService`, `DeliveryAgent`, `RequirementAgent`. Each carries a versioned prompt + structured output schema + recovery gradient (JSON-mode → 3 retries → `manual_review` fallback).

---

## Quick start

Requirements: **Python 3.11**, **uv**, **bun** (or **npm**), Redis (optional in dev).

```bash
# Backend
uv sync
cp .env.example .env  # add DEEPSEEK_API_KEY
uv run alembic -c apps/api/alembic.ini upgrade head
uv run uvicorn workgraph_api.main:app --reload --port 8000

# Frontend
cd apps/web
bun install
bun dev   # localhost:3000

# Tests
uv run pytest                    # 683/683 backend tests
cd apps/web && bun test          # frontend unit tests
```

Seed demo data:

```bash
uv run python scripts/demo/seed_moonshot.py        # Stellar Drift / Moonshot Studios
```

---

## Repository layout

```
apps/
  api/               FastAPI — routers, services, agent wiring
  web/               Next.js — app router, components, i18n
  worker/            Celery — async agent runs
packages/
  agents/            13 LLM agents — prompts, schemas, recovery gradient
  domain/            EventBus, entity schemas
  persistence/       SQLAlchemy ORM, repositories, Alembic migrations
  schemas/           Shared Pydantic DTOs
  observability/     Structured logging, trace_id propagation
  orchestrator/      Workflow stage logic
  feishu_adapter/    Lark / Feishu integration (deferred)
docs/
  north-star.md      Current product intent (read first)
  architecture.md    Visual architecture summary
  competition.zh-CN.md  Submission narrative
  demo_script.md     7-minute demo run-through
  flow-packets-spec.md  Flow Packets v1.1 spec
  membrane-reorg.md     Membrane single-boundary thesis
deploy/
  docker-compose.yml, nginx config, Alembic harness
```

**Read first:** `docs/north-star.md`. It's the current product intent. `PLAN.md`, `docs/dev.md`, `AGENT.md`, and similar carry archive banners — they're MVP-era historical record, not current spec.

---

## Status

V1 is shipped and live. V2 → V4 features (dissent, silent consensus, scrimmage, ambient onboarding, hierarchical KB, meeting metabolism, license-aware replies, Org Graph Trust Ladder, Epistemic Event Contract, Membrane semantic review M1–M5.1) are all live as of `2026-05-07`.

683 backend tests green. TypeScript strict mode. Production: single VPS, Cloudflare Tunnel, Aliyun mainland, ~6 months stable.

---

## Contributing

This started as a competition submission and is now an open-source experiment. Contributions welcome — please read `docs/north-star.md` first to understand the product intent. PRs that pull the product back toward "Notion + AI" or "ChatOps" patterns will be respectfully redirected.

Architecture invariants (enforced by tests + CI):
1. **Thin routers** — pydantic validation → membership gate → service call → status code. No business logic in routers.
2. **Membrane is one boundary** — every scope-into-cell write flows through `MembraneService.review()`. New write kinds extend `CandidateKind` enum, never bypass.
3. **LLM orchestration in `packages/agents/`** — all `LLMClient` instantiation lives there. Services orchestrate, agents call LLMs.
4. **License gate is single-source** — tier filtering goes through `LicenseContextService`; replies are validated by `lint_reply()`.

---

## License

MIT — see [`LICENSE`](LICENSE).

---

## Acknowledgments

Built as a submission to the ByteDance "AI for Collaboration" competition (2026 round). Heavy intellectual debts to the [North Star doc](docs/north-star.md) and the body of work on knowledge-graph-as-state, multi-agent orchestration, and modal logic for collective belief.

The brand mark is "G + F" interlaced — Graph + Flow — as a single continuous form, mirroring the product's claim that coordination should be one continuous flow over a graph, not a stack of fragmented documents.
