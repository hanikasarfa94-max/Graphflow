"""Seed story-shape content on top of seed_moonshot.

Mirrors the volume of the deleted Phase D FE mock fixtures (TikHub
narrative) but in Stellar Drift voice — the cast and project come
from seed_moonshot, this script layers on:

  *  6 docs (1 project brief + 5 KB notes/attachments)
  *  3 routed signals (Flow Center route packets)
  *  2 KB group drafts pending Membrane review
  *  4 personal tasks across assignee roles

Run AFTER `python scripts/demo/seed_moonshot.py`. Idempotent in the
loose sense — re-running double-seeds content, so re-init the SQLite
file (./data/workgraph.sqlite) between fresh runs if you want a
clean slate.

Targets a live local API on :8000.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

BASE = os.environ.get("WORKGRAPH_BASE_URL", "http://127.0.0.1:8000")
PASSWORD = "moonshot2026"


@dataclass
class Session:
    username: str
    client: httpx.Client
    user_id: str


def log(msg: str) -> None:
    print(f"  {msg}")


def login(username: str) -> Session:
    client = httpx.Client(base_url=BASE, timeout=30.0)
    r = client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    r.raise_for_status()
    user = r.json()
    return Session(username=username, client=client, user_id=user["id"])


def find_project(maya: Session) -> str:
    r = maya.client.get("/api/projects")
    r.raise_for_status()
    projects = r.json()
    if isinstance(projects, dict):
        projects = projects.get("projects", [])
    for p in projects:
        if "stellar drift" in p.get("title", "").lower():
            return p["id"]
    raise RuntimeError(
        "Stellar Drift project not found — run seed_moonshot.py first."
    )


# ---- docs (6) — KbItemRow scope=group, status varies --------------------
#
# The deleted FE fixtures had 1 project brief + 5 notes/attachments.
# We mirror the count; the narrative is Stellar Drift.

DOCS: list[dict[str, Any]] = [
    {
        # Pinned project brief. The FE Documents page pins
        # is_project_brief=true items to the top.
        "author": "maya",
        "scope": "group",
        "status": "published",
        "title": "Stellar Drift — Season 1 Launch Brief",
        "content_md": (
            "# Stellar Drift — Season 1 Launch Brief\n\n"
            "## Mission\n"
            "Ship Season 1 in 4 weeks with 4-player co-op matchmaking, "
            "4 unique boss encounters, and full crossplay across Steam + "
            "Xbox + PlayStation + Switch.\n\n"
            "## Decisions to date\n"
            "- Permadeath on bosses — under review (rage-quit 40% on boss 1).\n"
            "- Mid-run merchant — cut unless perf budget allows.\n"
            "- External QA — round 1 done, round 2 scheduled.\n\n"
            "## Open questions\n"
            "- Switch 60fps target — keep or relax to 30fps for boss arenas?\n"
            "- Boss 3 palette delay — does it ship Day 1 or in a 1.0.1 patch?\n"
        ),
    },
    {
        "author": "raj",
        "scope": "group",
        "status": "published",
        "title": "Boss tuning — first-boss rage-quit notes",
        "content_md": (
            "# Boss 1 tuning\n\n"
            "Sofia's playtest report: 40% rage-quit on boss 1, session "
            "length 23min vs 35min target. Three working hypotheses:\n\n"
            "1. Permadeath kills the run before players learn telegraphs.\n"
            "2. Tell-window on slam is 200ms; players in playtest needed "
            "~350ms minimum.\n"
            "3. Reward structure puts the cool drop after boss 2, so the "
            "first boss feels punitive without payoff.\n\n"
            "Next: 2 design calls + 1 telemetry pass before patch."
        ),
    },
    {
        "author": "aiko",
        "scope": "group",
        "status": "published",
        "title": "Matchmaking v2 — crossplay architecture",
        "content_md": (
            "# Crossplay matchmaking — v2\n\n"
            "Steam + Xbox + PlayStation + Switch via vendor SDK + NAT "
            "traversal fallback. Two open items:\n\n"
            "- Vendor renewal pending VP-ops approval (cost ~$40k/year).\n"
            "- Switch performance: matchmaking pings add ~80ms vs other "
            "platforms; needs a profile pass."
        ),
    },
    {
        "author": "diego",
        "scope": "group",
        "status": "published",
        "title": "Art pipeline — boss palettes",
        "content_md": (
            "# Boss palettes\n\n"
            "Boss 1, 2, 4: locked.\n"
            "Boss 3: delayed 2 days. Plan B is a palette swap of boss "
            "2's lighting rig — net-net negligible visual delta, no "
            "blocker."
        ),
    },
    {
        "author": "sofia",
        "scope": "group",
        "status": "published",
        "title": "Playtest round 1 — community signal",
        "content_md": (
            "# Playtest round 1\n\n"
            "5 testers across 3 sessions.\n\n"
            "- 3 of 5: boss fights feel unfair.\n"
            "- Rage-quit rate: 40% on first boss.\n"
            "- Avg session length: 23min (target 35min).\n"
            "- Positive: matchmaking 'just worked' on every Steam<->PS\n"
            "  pairing tested.\n\n"
            "Recommendation: re-run with 10+ testers after boss-1 patch."
        ),
    },
    {
        "author": "james",
        "scope": "personal",
        "status": "published",
        "title": "Personal notes — NAT traversal fallback path",
        "content_md": (
            "# Notes on NAT traversal\n\n"
            "Quick reference for what I'm pushing in feature/mm-v2:\n\n"
            "1. Vendor TURN as primary.\n"
            "2. Self-hosted relay (existing fleet) as fallback when "
            "vendor RTT > 200ms.\n"
            "3. Last-ditch: direct P2P with hole-punching, only when "
            "both peers' NATs are confirmed cone-type.\n\n"
            "Awaiting Aiko's review."
        ),
    },
]


def seed_docs(sessions: dict[str, Session], project_id: str) -> None:
    log(f"seeding {len(DOCS)} docs (5 group + 1 personal)...")
    for spec in DOCS:
        author = sessions[spec["author"]]
        r = author.client.post(
            f"/api/projects/{project_id}/kb-items",
            json={
                "title": spec["title"],
                "content_md": spec["content_md"],
                "scope": spec["scope"],
                "status": spec["status"],
                "source": "manual",
            },
        )
        if r.status_code == 200:
            doc_id = r.json().get("id", "?")[:8]
            log(f"  doc [{spec['scope']}/{spec['status']}] {spec['title'][:48]}  ({doc_id})")
        else:
            log(f"  doc FAILED ({r.status_code}): {spec['title'][:48]} — {r.text[:120]}")


# ---- 2 KB group drafts pending Membrane review --------------------------
#
# scope=group + status=draft is the path KbItemService takes for items
# that need Membrane approval. These show up in Flow Center as
# `promote_to_memory` packets and in the Memory Review drawer when
# the corresponding candidate row is produced.

DRAFTS: list[dict[str, Any]] = [
    {
        "author": "aiko",
        "scope": "group",
        "status": "draft",
        "title": "Permadeath policy — proposed scope-narrow",
        "content_md": (
            "# Permadeath policy (DRAFT)\n\n"
            "Proposal: permadeath applies only to boss-arena rooms, not "
            "to the lead-up corridors. Players who die in a corridor "
            "respawn at the room's start; only boss-room deaths kill "
            "the run.\n\n"
            "Rationale: gives newer players room to learn telegraphs "
            "before the run-ending decision. Sofia's data suggests this "
            "captures ~80% of the rage-quit population.\n\n"
            "Open: does this break the leaderboard run-time semantics? "
            "Needs Raj's signoff."
        ),
    },
    {
        "author": "aiko",
        "scope": "group",
        "status": "draft",
        "title": "Switch perf — 60fps target spec",
        "content_md": (
            "# Switch perf — 60fps target (DRAFT)\n\n"
            "Target: 60fps locked in non-boss arenas, 45fps floor in "
            "boss arenas (Switch only). Other platforms remain 60fps "
            "locked everywhere.\n\n"
            "Open: marketing has been saying '60fps on every platform'. "
            "Needs Maya's review before this becomes policy."
        ),
    },
]


def seed_drafts(sessions: dict[str, Session], project_id: str) -> None:
    log(f"seeding {len(DRAFTS)} KB group drafts (Membrane review feedstock)...")
    for spec in DRAFTS:
        author = sessions[spec["author"]]
        r = author.client.post(
            f"/api/projects/{project_id}/kb-items",
            json={
                "title": spec["title"],
                "content_md": spec["content_md"],
                "scope": spec["scope"],
                "status": spec["status"],
                "source": "manual",
            },
        )
        if r.status_code == 200:
            kb_id = r.json().get("id", "?")[:8]
            log(f"  draft {spec['title'][:50]}  ({kb_id})")
        else:
            log(f"  draft FAILED ({r.status_code}): {spec['title'][:50]} — {r.text[:120]}")


# ---- 3 routed signals — Flow Center route packets -----------------------

ROUTES: list[dict[str, Any]] = [
    {
        "from": "maya",
        "to": "aiko",
        "framing": (
            "Aiko — given the playtest data, do we have the engineering "
            "headroom this week to A/B test scope-narrow permadeath "
            "(boss-arena only)? I need to know before I commit to the "
            "design call on Wednesday."
        ),
        "background": [
            {
                "source": "graph",
                "snippet": "Sofia playtest: 40% rage-quit on boss 1, 23min avg session vs 35min target.",
            },
        ],
        "options": [
            {
                "id": "yes_this_week",
                "label": "Yes — A/B by Friday",
                "kind": "action",
                "background": "We have spare instrumentation budget.",
                "reason": "Reusing existing telemetry hooks.",
                "weight": 0.6,
            },
            {
                "id": "next_week",
                "label": "Push to next week",
                "kind": "action",
                "background": "Switch perf work is mid-stride.",
                "reason": "Don't want to interleave two big changes.",
                "weight": 0.4,
            },
        ],
    },
    {
        "from": "raj",
        "to": "sofia",
        "framing": (
            "Sofia — before I lock the boss-1 patch numbers, can you "
            "pull the community signal from the latest Steam thread? "
            "Specifically rage-quit phrasing vs 'too hard' phrasing — "
            "they're different problems."
        ),
        "background": [
            {
                "source": "graph",
                "snippet": "Boss-1 tuning doc lists three working hypotheses.",
            },
        ],
        "options": [
            {
                "id": "by_eod",
                "label": "Pull by EOD",
                "kind": "action",
                "weight": 0.7,
            },
            {
                "id": "tomorrow_am",
                "label": "Tomorrow AM",
                "kind": "action",
                "weight": 0.3,
            },
        ],
    },
    {
        "from": "diego",
        "to": "james",
        "framing": (
            "James — does the vendor matchmaking SDK have any palette/"
            "shader hooks I should know about? I'm sequencing boss 3's "
            "palette swap and don't want to clobber anything you're "
            "doing in the crossplay layer."
        ),
        "background": [
            {
                "source": "graph",
                "snippet": "Boss 3 palette is delayed 2d; plan B is palette swap of boss 2's lighting rig.",
            },
        ],
        "options": [
            {
                "id": "no_conflict",
                "label": "No conflict — safe to swap",
                "kind": "action",
                "weight": 0.5,
            },
            {
                "id": "need_check",
                "label": "Let me check the SDK release notes first",
                "kind": "action",
                "weight": 0.5,
            },
        ],
    },
]


def seed_routes(sessions: dict[str, Session], project_id: str) -> None:
    log(f"seeding {len(ROUTES)} routed signals (Flow Center packets)...")
    for spec in ROUTES:
        author = sessions[spec["from"]]
        target = sessions[spec["to"]]
        r = author.client.post(
            "/api/routing/dispatch",
            json={
                "target_user_id": target.user_id,
                "project_id": project_id,
                "framing": spec["framing"],
                "background": spec["background"],
                "options": spec["options"],
            },
        )
        if r.status_code == 200:
            sig_id = r.json()["signal"]["id"][:8]
            log(f"  route {spec['from']} -> {spec['to']}  ({sig_id})")
        elif r.status_code == 422:
            # R2 grounding gate — target_not_grounded. Try again with
            # a "skill-match" route by using the suggested alternative
            # if present; otherwise log and skip.
            body = r.json()
            alts = body.get("alternatives", [])
            log(
                f"  route {spec['from']} -> {spec['to']} ungrounded "
                f"({body.get('error', '?')}); alternatives={len(alts)}"
            )
        else:
            log(
                f"  route {spec['from']} -> {spec['to']} FAILED "
                f"({r.status_code}): {r.text[:120]}"
            )
        # Small gap so the IM agent can pick each one up before the next.
        time.sleep(0.5)


# ---- 4 tasks ------------------------------------------------------------

TASKS: list[dict[str, Any]] = [
    {
        "author": "maya",
        "title": "Fix boss 1 rage-quit rate to <20%",
        "description": (
            "Working hypotheses in `Boss tuning — first-boss rage-quit notes`. "
            "Outcome: rage-quit rate under 20% in playtest round 2."
        ),
        "estimate_hours": 16,
        "assignee_role": "design-lead",
    },
    {
        "author": "aiko",
        "title": "Switch perf profile pass — boss arenas",
        "description": (
            "Goal: 60fps non-boss arenas, 45fps floor in boss arenas. "
            "See `Switch perf — 60fps target spec` draft."
        ),
        "estimate_hours": 24,
        "assignee_role": "engineering-lead",
    },
    {
        "author": "sofia",
        "title": "Run playtest round 2 with 10+ testers",
        "description": (
            "After boss-1 patch lands. Same metrics as round 1: rage-quit "
            "rate, session length, qualitative comments."
        ),
        "estimate_hours": 8,
        "assignee_role": "qa-lead",
    },
    {
        "author": "diego",
        "title": "Finalize boss 3 palette",
        "description": (
            "Plan B confirmed: palette swap of boss 2's lighting rig. "
            "Pending James's SDK check (see routed signal)."
        ),
        "estimate_hours": 6,
        "assignee_role": "art-director",
    },
]


def seed_tasks(sessions: dict[str, Session], project_id: str) -> None:
    log(f"seeding {len(TASKS)} tasks...")
    for spec in TASKS:
        author = sessions[spec["author"]]
        r = author.client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "title": spec["title"],
                "description": spec["description"],
                "estimate_hours": spec["estimate_hours"],
                "assignee_role": spec["assignee_role"],
            },
        )
        if r.status_code == 200:
            task_id = (
                r.json().get("task", {}).get("id", "?")[:8]
                if isinstance(r.json(), dict)
                else "?"
            )
            log(f"  task [{spec['assignee_role']}] {spec['title'][:48]}  ({task_id})")
        else:
            log(f"  task FAILED ({r.status_code}): {spec['title'][:48]} — {r.text[:120]}")


# ---- main ---------------------------------------------------------------


def main() -> int:
    print("Seeding story-shape layer on top of seed_moonshot")
    print(f"  API: {BASE}")
    print()

    cast = ["maya", "raj", "aiko", "diego", "sofia", "james"]
    sessions: dict[str, Session] = {}
    for u in cast:
        try:
            sessions[u] = login(u)
        except httpx.HTTPStatusError as e:
            print(f"[FAIL] cannot log in {u} — run seed_moonshot.py first.")
            print(f"   ({e})")
            return 1

    project_id = find_project(sessions["maya"])
    print(f"using project {project_id}")
    print()

    seed_docs(sessions, project_id)
    print()
    seed_drafts(sessions, project_id)
    print()
    seed_routes(sessions, project_id)
    print()
    seed_tasks(sessions, project_id)
    print()

    print("=" * 64)
    print("[OK] story-shape layer seeded")
    print("=" * 64)
    print()
    print(f"  Flow Center:    http://localhost:3000/flow-center")
    print(f"  Conversations:  http://localhost:3000/conversations")
    print(f"  Tasks:          http://localhost:3000/tasks")
    print(f"  Docs:           http://localhost:3000/docs")
    print()

    for s in sessions.values():
        s.client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
