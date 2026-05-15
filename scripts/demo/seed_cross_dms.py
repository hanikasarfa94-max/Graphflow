"""Seed cross-DMs across cast pairs.

The base seed_storyshape dispatched 3 routed signals; each route
creates a source↔target DM stream as a side effect of
RoutingService.dispatch. That gives each user at most 1 DM.

This script dispatches an additional set of routes that cover the
pairs nobody routed yet, so every cast member has 2-3 DMs visible
on /conversations. Each route also seeds 1-2 follow-up messages on
the resulting DM stream so the conversation isn't empty when opened.

Run AFTER seed_moonshot + seed_storyshape.
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
        if "stellar drift" in p.get("title", "").lower() and "mobile" not in p.get("title", "").lower():
            return p["id"]
    raise RuntimeError("Stellar Drift EN project not found.")


# Cross-DM routes — phrased to match each target's declared role hints
# so the R2 grounding gate doesn't reject them.
#
# Existing routes (from seed_storyshape): maya→aiko, raj→sofia, diego→james.
# Adding pairs that haven't met yet, plus a few reverse-direction.

ROUTES: list[dict[str, Any]] = [
    {
        "from": "raj",
        "to": "aiko",
        "framing": (
            "Aiko — I want to lock the boss-1 timing window before the design "
            "call. Can the engine instrument tell-window opens reliably enough "
            "to A/B 200ms vs 350ms?"
        ),
        "options": [
            {"id": "yes", "label": "Yes — instrumented", "kind": "action"},
            {"id": "rough", "label": "Rough only, +1d to instrument", "kind": "action"},
        ],
    },
    {
        "from": "maya",
        "to": "raj",
        "framing": (
            "Raj — I'd like the boss difficulty design call moved to Wednesday "
            "so we have Sofia's round-2 playtest summary first. Does that work "
            "with your sprint shape?"
        ),
        "options": [
            {"id": "wed_ok", "label": "Wednesday works", "kind": "action"},
            {"id": "earlier", "label": "Earlier is better — Monday?", "kind": "action"},
        ],
    },
    {
        "from": "sofia",
        "to": "diego",
        "framing": (
            "Diego — community thread keeps surfacing 'boss 3 felt out of "
            "place tonally'. Is the palette swap going to read close enough "
            "to boss 2 that it amplifies that, or is it different enough?"
        ),
        "options": [
            {"id": "different", "label": "Different enough — distinct vibe", "kind": "action"},
            {"id": "concerning", "label": "Concerning — want to re-light", "kind": "action"},
        ],
    },
    {
        "from": "aiko",
        "to": "james",
        "framing": (
            "James — review on the NAT traversal fallback path. Specifically: "
            "is the cone-type confirmation handshake going to add observable "
            "latency on the happy path, or is it fully out-of-band?"
        ),
        "options": [
            {"id": "out_of_band", "label": "Fully out-of-band", "kind": "action"},
            {"id": "few_ms", "label": "+5-10ms on first packet", "kind": "action"},
        ],
    },
    {
        "from": "diego",
        "to": "maya",
        "framing": (
            "Maya — boss 3 palette goes to plan B. Should the launch trailer "
            "still feature boss 3, or pivot to boss 1 + boss 4 footage?"
        ),
        "options": [
            {"id": "keep_b3", "label": "Keep boss 3 — palette holds up", "kind": "action"},
            {"id": "pivot", "label": "Pivot trailer to 1 + 4", "kind": "action"},
        ],
    },
    {
        "from": "james",
        "to": "sofia",
        "framing": (
            "Sofia — for round 2, can we route a few testers through "
            "matchmaking with NAT-restrictive networks on purpose? I want "
            "data on the fallback path in the wild."
        ),
        "options": [
            {"id": "yes", "label": "Yes — I can recruit 3", "kind": "action"},
            {"id": "next_round", "label": "Better in round 3", "kind": "action"},
        ],
    },
    {
        "from": "aiko",
        "to": "maya",
        "framing": (
            "Maya — the scope-narrow permadeath proposal is up for review. "
            "Net-new code is small. Want me to land it behind a feature flag "
            "before round-2 playtest?"
        ),
        "options": [
            {"id": "flag_it", "label": "Yes — flag and A/B in round 2", "kind": "action"},
            {"id": "wait_design", "label": "Wait for design call decision", "kind": "action"},
        ],
    },
    {
        "from": "sofia",
        "to": "aiko",
        "framing": (
            "Aiko — for the Switch perf pass, do we have a baseline frame "
            "graph I can use to brief community on what 'boss arena floor 45fps' "
            "actually means for run pacing?"
        ),
        "options": [
            {"id": "yes_share", "label": "Yes — sharing a 30s clip", "kind": "action"},
            {"id": "after_pass", "label": "Better after the profile pass", "kind": "action"},
        ],
    },
]


def post_dm_followup(
    src: Session, dst: Session, signal_id: str, body: str
) -> None:
    """After a route is dispatched, the source↔target DM stream
    exists. Find it via /api/streams and post a follow-up message
    so the DM isn't just the routed-dm-log entry.
    """
    # The streams endpoint lists streams the caller is a member of.
    r = src.client.get("/api/streams")
    if r.status_code != 200:
        return
    streams = r.json()
    if isinstance(streams, dict):
        streams = streams.get("streams", [])
    # Find the DM with dst as the other party. The streams API returns
    # stream rows with member_user_ids; we pick the dm with exactly
    # {src.user_id, dst.user_id} as members.
    dm_id: str | None = None
    for s in streams:
        if s.get("type") != "dm":
            continue
        members = s.get("member_user_ids") or s.get("members") or []
        # Coerce to id strings if members is a list of objects.
        ids = {
            (m.get("user_id") if isinstance(m, dict) else m)
            for m in members
        }
        if ids == {src.user_id, dst.user_id}:
            dm_id = s.get("id")
            break
    if not dm_id:
        return
    rr = src.client.post(
        f"/api/streams/{dm_id}/messages", json={"body": body}
    )
    if rr.status_code != 200:
        log(f"  follow-up to {dst.username} on DM {dm_id[:8]} failed: {rr.status_code}")


def main() -> int:
    print("Seeding cross-DMs across cast pairs")
    print(f"  API: {BASE}")
    print()

    cast = ["maya", "raj", "aiko", "diego", "sofia", "james"]
    sessions: dict[str, Session] = {}
    for u in cast:
        sessions[u] = login(u)
    project_id = find_project(sessions["maya"])
    print(f"  using project {project_id}\n")

    log(f"dispatching {len(ROUTES)} routes...")
    for spec in ROUTES:
        author = sessions[spec["from"]]
        target = sessions[spec["to"]]
        r = author.client.post(
            "/api/routing/dispatch",
            json={
                "target_user_id": target.user_id,
                "project_id": project_id,
                "framing": spec["framing"],
                "background": [],
                "options": spec["options"],
            },
        )
        if r.status_code == 200:
            sig_id = r.json()["signal"]["id"]
            log(f"  route {spec['from']} -> {spec['to']}  ({sig_id[:8]})")
            # Drop a follow-up message in the DM so the conversation
            # has > 1 entry when opened.
            time.sleep(0.4)
            post_dm_followup(
                author,
                target,
                sig_id,
                f"({spec['from']}) Sent the routed question — let me know what you decide.",
            )
        elif r.status_code == 422:
            body = r.json()
            log(
                f"  route {spec['from']} -> {spec['to']} ungrounded "
                f"({body.get('error', '?')})"
            )
        else:
            log(
                f"  route {spec['from']} -> {spec['to']} FAILED "
                f"({r.status_code}): {r.text[:120]}"
            )
        time.sleep(0.3)

    print()
    print("=" * 64)
    print("[OK] cross-DMs seeded")
    print("=" * 64)
    print()

    for s in sessions.values():
        s.client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
