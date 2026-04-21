> ⚠️ **STALE 2026-04-21 — SNAPSHOT FROM 2026-04-18, KEPT AS HISTORICAL RESUME NOTE.**
>
> This handoff was written mid-Phase-K of the chat-centered rebuild. Since
> then v1 shipped + was submitted to ByteDance (2026-04-20) and a wide v2
> feature set landed (see `git log`). Do not use this file to understand
> current state.

---

# Resume after restart

Session state as of 2026-04-18. Compact handoff so the next session picks up in <2 min.

## Read first (in this order)

1. `docs/vision.md` — v2 thesis. Organism model, signals, decisions-as-crystallizations, membranes, response profiles. Supersedes `docs/dev.md` framing.
2. `docs/signal-chain-plan.md` — API contract for the canonical signal chain (§6 of vision).
3. `docs/demo-game-company.md` — Moonshot Studios demo story + live-moment script.
4. Memory `project_vision_v2.md` (already loaded via `MEMORY.md` index) — v2 pivot summary.

## Verify MCP loaded

Run `/mcp` in Claude Code. You should see `chrome-devtools` registered (added to `~/.claude/settings.json` before the restart). If missing, check the Chrome DevTools MCP quick-start and confirm `cmd /c npx -y chrome-devtools-mcp@latest` runs manually.

## Running processes (may need restart after Claude Code restart)

- **API** — `uv run uvicorn workgraph_api.main:app --host 127.0.0.1 --port 8000`
- **Web** — `cd apps/web && bun dev` (Next.js on :3000)

If the background processes died when Claude Code exited, restart both. The SQLite dev DB at `data/workgraph.sqlite` has the seeded state — **do not delete it** unless you want to re-seed.

## Seeded Moonshot demo (already in the DB)

- **Project ID:** `6fb72b5a-82b4-43ca-92af-5185f14a1099`
- **Project title:** "Stellar Drift — Season 1 Launch"
- **Direct URL:** http://localhost:3000/projects/6fb72b5a-82b4-43ca-92af-5185f14a1099/im
- **Users** (all password `moonshot2026`): `maya, raj, aiko, diego, sofia, james`
- **State:** project created, 5 members invited, 5 older IM messages seeded, parse+graph+plan complete (10 tasks, 2 risks), ready for the live moment

If DB was wiped, reseed: `uv run python scripts/demo/seed_moonshot.py`

## Last pending task

Task #14: **integrate + verify the canonical signal chain in two browsers.**

The live moment (from `docs/demo-game-company.md`):
1. Log in as `raj` in one browser, `aiko` in an incognito
2. Raj posts the permadeath-drop message — IMAssist classifies as decision-kind
3. Aiko clicks **Counter** with the memento-revive framing
4. Raj clicks **Accept** on Aiko's counter
5. Both browsers: ⚡ Decision recorded chip lights up simultaneously

**Use chrome-devtools MCP to auto-drive this** instead of the user clicking through. Capture screenshots at each step.

## What's uncommitted

`git status` will show:

- `docs/vision.md` (new — v2 thesis)
- `docs/signal-chain-plan.md` (new — build contract)
- `docs/demo-game-company.md` (new — demo narrative)
- `docs/resume.md` (this file)
- `scripts/demo/seed_moonshot.py` + `scripts/demo/tour.mjs` (new — seeder + playwright fallback)
- Backend signal-chain work: `packages/persistence/src/workgraph_persistence/{orm,repositories}.py`, `apps/api/src/workgraph_api/services/{im,decisions}.py`, `apps/api/src/workgraph_api/routers/collab.py`, new `apps/api/tests/test_signal_chain.py`
- Frontend signal-chain work: `apps/web/src/lib/api.ts`, `apps/web/src/app/projects/[id]/im/ChatPane.tsx`, `apps/web/src/app/projects/[id]/conflicts/ConflictsPane.tsx`
- `.gitignore` (added playwright-report + .gstack + apps/web/data sqlite)

**Commit after verifying the demo chain works.** Suggested message: `feat: signal chain (counter + escalate + decision crystallization)` + `docs: v2 vision + Moonshot demo`. Two commits or one, your call.

## Tests status (as of the backend agent's last report)

- `apps/api/tests/test_signal_chain.py`: 7/7 pass (new)
- `apps/api/tests/test_collab.py`: 9/9 pass
- Full `apps/api/tests/`: 125/125, no skips
- Frontend `tsc --noEmit`: clean

## Fallback if chrome-devtools MCP misbehaves

`cd apps/web && node ../../scripts/demo/tour.mjs` — uses the web app's vendored Playwright to log in as maya, walk every page, screenshot to `/tmp/moonshot-tour/*.png`, report console errors per page. Pure Node, no MCP dependency.

## One-line product summary for context

WorkGraph is a synthetic organism for a group. Signals propagate along graph edges, LLM-on-edge metabolizes them, decisions crystallize as graph nodes with full lineage. Humans are differentiated nodes with response profiles. Meetings = pain signal when signal propagation fails. Membranes = external signal ingestion. Current focus: build §6 canonical signal chain (code done, verification pending).
