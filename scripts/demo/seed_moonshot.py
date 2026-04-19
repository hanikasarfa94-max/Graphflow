"""Seed the Moonshot Studios demo — Stellar Drift Season 1.

Creates 6 users, submits Maya's intake (triggers the parse → graph → plan
pipeline), invites the team, and seeds ~5 older IM messages that set up
the live permadeath-vs-playtest moment.

Run against a live local API on :8000:

    uv run python scripts/demo/seed_moonshot.py

Or against a remote deploy:

    WORKGRAPH_BASE_URL=https://demo.example.com \
        uv run python scripts/demo/seed_moonshot.py

Idempotency: if a user already exists the script logs in instead. If the
project already exists as created by `maya` it re-uses it. Safe to re-run
while iterating.

Prints at the end a two-browser login plan so you know exactly which
tabs to open for the canonical signal chain demo.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

import httpx

BASE = os.environ.get("WORKGRAPH_BASE_URL", "http://127.0.0.1:8000")
WEB_BASE = os.environ.get("WORKGRAPH_WEB_URL", "http://localhost:3000")

PASSWORD = "moonshot2026"

CAST = [
    ("maya", "Maya Chen", "CEO / Game Director"),
    ("raj", "Raj Patel", "Design Lead"),
    ("aiko", "Aiko Nakamura", "Engineering Lead"),
    ("diego", "Diego Torres", "Art Director"),
    ("sofia", "Sofia Rossi", "QA / Community Lead"),
    ("james", "James Okoro", "Junior Engineer"),
]

# Profile seed — drives EdgeAgent signal-to-role matching.
# `role_hints` are what the LLM reads first; `declared_abilities` are
# what the user self-declared at onboarding (R1 in roadmaps).
PROFILES: dict[str, dict[str, list[str]]] = {
    "maya": {
        "role_hints": ["founder", "ceo", "game-director"],
        "declared_abilities": ["vision", "strategy", "scope-decisions", "fundraising"],
    },
    "raj": {
        "role_hints": ["design-lead", "game-design"],
        "declared_abilities": ["systems-design", "combat-feel", "balance", "boss-design"],
    },
    "aiko": {
        "role_hints": ["engineering-lead", "tech-lead"],
        "declared_abilities": ["systems", "memory-profiling", "save-state", "performance", "unity"],
    },
    "diego": {
        "role_hints": ["art-director", "art-lead"],
        "declared_abilities": ["art-direction", "character-design", "palette", "pipeline"],
    },
    "sofia": {
        "role_hints": ["qa-community-lead", "qa-lead"],
        "declared_abilities": ["playtest", "steam-community", "rage-quit-analysis", "external-data"],
    },
    "james": {
        "role_hints": ["junior-engineer"],
        "declared_abilities": ["matchmaking", "networking"],
    },
}

PROJECT_INTAKE = (
    "We're launching Stellar Drift Season 1 in 4 weeks. Core scope: "
    "4-player co-op matchmaking over Steam with crossplay, 4 unique boss "
    "encounters with permadeath mechanics, full controller support "
    "(Xbox + PlayStation + Switch), daily run seeds, and leaderboards. "
    "Art is 80% locked. Main risks are boss difficulty tuning and Switch "
    "performance. We need external QA playtests with 20+ players before "
    "launch."
)

# (username, body). Posted in order; 1s gap so classifier can run per message.
SEED_CHAT = [
    (
        "maya",
        "Team — alpha build is locked. Final-stretch focus: ship polish + "
        "external QA. Stretch goal, only if perf allows, is a mid-run "
        "merchant vendor. Otherwise we cut it.",
    ),
    (
        "diego",
        "Art's tracking well. Boss 3 palette is delayed 2 days — plan B "
        "is a palette swap of boss 2's lighting rig. Net-net negligible, "
        "no blocker.",
    ),
    (
        "james",
        "I pushed the matchmaking draft to feature/mm-v2. Need a review "
        "before I continue, specifically the NAT traversal fallback path. "
        "Aiko can you glance?",
    ),
    (
        "sofia",
        "First external playtest done. 3 of 5 testers said the boss "
        "fights feel unfair. Rage-quit rate 40% on the first boss. "
        "Session length averaged 23min against our 35min target. Full "
        "report incoming.",
    ),
    (
        "aiko",
        "Looked at Sofia's report. Main cause looks like permadeath on "
        "boss deaths — kills the session too early for inexperienced "
        "players. We need a design call before we touch code.",
    ),
]


@dataclass
class Session:
    username: str
    client: httpx.Client
    user_id: str


def log(msg: str) -> None:
    print(f"  {msg}")


def register_or_login(username: str, display_name: str) -> Session:
    """Try register; fall back to login if the user already exists."""
    client = httpx.Client(base_url=BASE, timeout=30.0)
    r = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": PASSWORD,
            "display_name": display_name,
        },
    )
    if r.status_code in (200, 201):
        user = r.json()
        log(f"registered {username} ({display_name})")
        return Session(username=username, client=client, user_id=user["id"])
    if r.status_code in (400, 409):
        # Already exists — log in instead.
        r = client.post(
            "/api/auth/login",
            json={"username": username, "password": PASSWORD},
        )
        r.raise_for_status()
        user = r.json()
        log(f"logged in existing {username}")
        return Session(username=username, client=client, user_id=user["id"])
    r.raise_for_status()
    raise RuntimeError(f"unexpected register response {r.status_code}: {r.text}")


def find_or_create_project(maya: Session) -> str:
    """Return project_id. If Maya already has a Stellar Drift project, reuse it."""
    r = maya.client.get("/api/projects")
    r.raise_for_status()
    existing = r.json()
    if isinstance(existing, dict):
        existing = existing.get("projects", [])
    for p in existing:
        title = p.get("title", "").lower()
        if "stellar drift" in title:
            log(f"re-using existing project '{p['title']}' ({p['id']})")
            return p["id"]

    log("submitting Maya's intake — triggers parse → graph → plan (may take 10–30s)...")
    r = maya.client.post(
        "/api/intake/message",
        json={"text": PROJECT_INTAKE, "title": "Stellar Drift — Season 1 Launch"},
    )
    r.raise_for_status()
    data = r.json()
    project_id = data["project"]["id"]
    log(f"created project {project_id}")
    return project_id


def invite_all(maya: Session, project_id: str, cast: list[Session]) -> None:
    for s in cast:
        if s.username == "maya":
            continue
        r = maya.client.post(
            f"/api/projects/{project_id}/invite",
            json={"username": s.username},
        )
        if r.status_code == 200:
            log(f"invited {s.username}")
        elif r.status_code in (400, 409):
            log(f"{s.username} already a member")
        else:
            r.raise_for_status()


def post_message(sess: Session, project_id: str, body: str) -> str:
    r = sess.client.post(
        f"/api/projects/{project_id}/messages",
        json={"body": body},
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        return "<?>"
    # Response may be either a bare message payload or {message: {...}}
    nested = data.get("message")
    if isinstance(nested, dict):
        return nested.get("id", "<?>")
    return data.get("id", "<?>")


def seed_chat_history(sessions: dict[str, Session], project_id: str) -> None:
    log(f"seeding {len(SEED_CHAT)} prior messages...")
    for author, body in SEED_CHAT:
        sess = sessions[author]
        msg_id = post_message(sess, project_id, body)
        log(f"  {author}: {body[:56]}{'...' if len(body) > 56 else ''}  ({msg_id[:8]})")
        # Let IMAssist pick up each message async before the next post.
        time.sleep(1.2)


def main() -> int:
    print("Seeding Moonshot Studios demo — Stellar Drift Season 1")
    print(f"  API:  {BASE}")
    print(f"  Web:  {WEB_BASE}")
    print()

    # Health check before anything.
    try:
        httpx.get(f"{BASE}/health", timeout=5.0).raise_for_status()
    except Exception as exc:
        print(f"[FAIL] API not reachable at {BASE}/health - start it first.")
        print(f"   Underlying error: {exc}")
        return 1

    print("registering cast...")
    sessions: dict[str, Session] = {}
    for username, display_name, _ in CAST:
        sessions[username] = register_or_login(username, display_name)
    maya = sessions["maya"]

    # Seed each user's profile so EdgeAgent can do signal-to-role
    # matching when proposing routing targets.
    print()
    print("seeding profiles...")
    for username, _, _ in CAST:
        profile = PROFILES.get(username)
        if not profile:
            continue
        session = sessions[username]
        r = session.client.patch(
            "/api/users/me",
            json={
                "declared_abilities": profile["declared_abilities"],
                "role_hints": profile["role_hints"],
            },
        )
        if r.status_code == 200:
            log(f"profile set for {username}: {','.join(profile['role_hints'])}")
        else:
            log(f"profile PATCH for {username} returned {r.status_code}: {r.text[:200]}")

    print()
    print("creating project...")
    project_id = find_or_create_project(maya)

    print()
    print("inviting team...")
    invite_all(maya, project_id, list(sessions.values()))

    print()
    print("seeding chat history...")
    seed_chat_history(sessions, project_id)

    print()
    print("=" * 64)
    print("[OK] Moonshot Studios demo seeded")
    print("=" * 64)
    print()
    print(f"  Project IM:  {WEB_BASE}/projects/{project_id}/im")
    print(f"  Project hub: {WEB_BASE}/projects/{project_id}")
    print(f"  Console:     {WEB_BASE}/console/{project_id}")
    print()
    print("  Two-browser plan for the live signal-chain demo:")
    print("    Browser A  →  log in as  raj   / moonshot2026")
    print("    Browser B  →  log in as  aiko  / moonshot2026")
    print()
    print("  Optional observer:  maya / moonshot2026 (third tab)")
    print()
    print("  All passwords: moonshot2026")
    print()
    print("  Live script at docs/demo-game-company.md §'The live moment'.")
    print()

    for sess in sessions.values():
        sess.client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
