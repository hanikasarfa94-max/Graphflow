"""Participants sidecar — resolves user_ids to display names in one
DB query so the FE evidence block can render names without N+1 fetches.
"""
from __future__ import annotations

from typing import Any

from workgraph_persistence import UserRepository


async def _resolve_participants(
    session, packets: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Build a `{user_id: {display_name, username}}` sidecar from the
    set of user_ids referenced across all packets. One UserRepository
    query per /flows call; the FE looks up locally without N+1.

    Pulls from: source_user_id, target_user_ids, current_target_user_ids,
    authority_user_ids, evidence.human_gates[*].user_id, and
    timeline[*].actor_user_id.
    """
    ids: set[str] = set()
    for p in packets:
        if p.get("source_user_id"):
            ids.add(str(p["source_user_id"]))
        for uid in p.get("target_user_ids") or []:
            if uid:
                ids.add(str(uid))
        for uid in p.get("current_target_user_ids") or []:
            if uid:
                ids.add(str(uid))
        for uid in p.get("authority_user_ids") or []:
            if uid:
                ids.add(str(uid))
        evidence = p.get("evidence") or {}
        for gate in evidence.get("human_gates") or []:
            uid = gate.get("user_id")
            if uid:
                ids.add(str(uid))
        for ev in p.get("timeline") or []:
            uid = ev.get("actor_user_id")
            if uid:
                ids.add(str(uid))
    if not ids:
        return {}
    rows = await UserRepository(session).get_many(list(ids))
    return {
        row.id: {
            "display_name": row.display_name or row.username,
            "username": row.username,
        }
        for row in rows
    }
