"""Sprint 3a — Org view (cross-project meta-graph).

Given a user and a project they're viewing, return a meta-graph of the
peer projects that user belongs to, plus "shared member" edges between
projects that have overlapping membership. The landing page scripts this
zoom-out with canned data (MorphingGraphDemo.tsx); this service is the
real thing, backed by live ProjectMemberRow / RiskRow / MessageRow state.

v1 edge semantics: two projects are connected iff they share >= 1 member.
The payload includes each edge's `shared_users` list so the UI can
explain "why is there a line here?" on hover. Decision-based edges
(conflict.targets pointing across projects) are deferred to v2 — v1
keeps the edge-building cost O(membership) rather than O(decisions).

The center project is always excluded from `peers` so the frontend can
render it as a distinct "you are here" cluster without having to filter
client-side.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from workgraph_persistence import (
    DecisionRow,
    MessageRow,
    ProjectMemberRow,
    ProjectRow,
    RiskRow,
)


# Risk lifecycle states that DO count as "open" in the org-view badge.
# Anything outside this set (closed / resolved / dismissed / mitigated
# / stale) is considered settled and suppresses the amber pill.
_OPEN_RISK_STATUSES = {"open", "active", "monitoring"}


def _aware(dt: datetime | None) -> datetime | None:
    """Coerce a datetime to tz-aware UTC.

    SQLite's DateTime(timezone=True) columns come back naive after read;
    Postgres preserves the zone. Serializing a naive datetime via
    isoformat() silently produces a string without an offset which the
    web client then treats as local time — wrong for "last activity"
    ticks. Coerce here so the wire contract stays UTC.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


async def _count_open_risks(session: AsyncSession, project_id: str) -> int:
    """Count RiskRow rows for `project_id` whose status is still open.

    RiskRow statuses in v1: 'open' by default, 'closed' / 'resolved' /
    'dismissed' when a decision or manual action retires them. We treat
    anything not explicitly in `_OPEN_RISK_STATUSES` as settled; that's
    the conservative read for a "needs attention" badge.
    """
    stmt = select(func.count(RiskRow.id)).where(
        RiskRow.project_id == project_id,
        RiskRow.status.in_(_OPEN_RISK_STATUSES),
    )
    return int((await session.execute(stmt)).scalar_one())


async def _last_activity_at(
    session: AsyncSession, project_id: str
) -> datetime | None:
    """Return the most recent signal of life for a project.

    Preferred source is MessageRow.created_at (chat = primary surface).
    Fall back to DecisionRow.created_at for projects that haven't had
    any messages yet but have seen at least one decision crystallize.
    Still nothing → None (the UI shows a dash).
    """
    msg_stmt = select(func.max(MessageRow.created_at)).where(
        MessageRow.project_id == project_id
    )
    latest_msg = (await session.execute(msg_stmt)).scalar_one_or_none()
    if latest_msg is not None:
        return _aware(latest_msg)

    dec_stmt = select(func.max(DecisionRow.created_at)).where(
        DecisionRow.project_id == project_id
    )
    latest_dec = (await session.execute(dec_stmt)).scalar_one_or_none()
    return _aware(latest_dec)


async def org_graph_for_user(
    session: AsyncSession,
    *,
    user_id: str,
    center_project_id: str,
) -> dict[str, Any]:
    """Build the cross-project meta-graph for `user_id`.

    Return shape matches the contract the router + frontend agree on:

        {
          "center": {"id", "title"},
          "peers":  [{ id, title, role, member_count, open_risks,
                       last_activity_at }],
          "edges":  [{ from_project_id, to_project_id, kind, weight,
                       shared_users }],
        }

    Invariants:
      * `center.id == center_project_id` is always present even if the
        center has no peers (empty `peers`, empty `edges`).
      * peers excludes the center project.
      * peers is restricted to projects where `user_id` is a member —
        we never surface strangers' projects even if they share a peer.
      * edges are undirected in meaning but emitted as a single directed
        pair (from=center, to=peer) so the frontend renders one line per
        relationship, not two.
    """
    # --- center project row + title -------------------------------------
    center_row = (
        await session.execute(
            select(ProjectRow).where(ProjectRow.id == center_project_id)
        )
    ).scalar_one_or_none()
    if center_row is None:
        # Router will already have 404'd if the center is unknown; the
        # fallback exists so this function stays usable from non-HTTP
        # callers (seeders, eval scripts) without additional plumbing.
        return {
            "center": {"id": center_project_id, "title": ""},
            "peers": [],
            "edges": [],
        }

    # --- user's own memberships (source-of-truth for peer scoping) ------
    my_memberships_stmt = select(ProjectMemberRow).where(
        ProjectMemberRow.user_id == user_id
    )
    my_memberships = list(
        (await session.execute(my_memberships_stmt)).scalars().all()
    )
    my_project_ids = {m.project_id for m in my_memberships}
    # Role-on-peer lookup so the returned peers carry the user's own
    # role in each peer project (the UI labels observer vs owner).
    my_role_by_project: dict[str, str] = {
        m.project_id: m.role for m in my_memberships
    }

    # Peers = projects the user is a member of, minus the center project.
    peer_project_ids = [pid for pid in my_project_ids if pid != center_project_id]

    # --- resolve peer ProjectRows in one query --------------------------
    peer_rows_by_id: dict[str, ProjectRow] = {}
    if peer_project_ids:
        peer_rows_stmt = select(ProjectRow).where(
            ProjectRow.id.in_(peer_project_ids)
        )
        peer_rows = list(
            (await session.execute(peer_rows_stmt)).scalars().all()
        )
        peer_rows_by_id = {p.id: p for p in peer_rows}

    # --- member_count per relevant project (center + peers) ------------
    # We need counts for all projects that might appear on the payload
    # (center for completeness in logs; peers for the badge). One query
    # grouped by project_id is cheaper than N round-trips.
    relevant_ids = [center_project_id, *peer_project_ids]
    member_count_by_project: dict[str, int] = {pid: 0 for pid in relevant_ids}
    if relevant_ids:
        counts_stmt = (
            select(
                ProjectMemberRow.project_id,
                func.count(ProjectMemberRow.id),
            )
            .where(ProjectMemberRow.project_id.in_(relevant_ids))
            .group_by(ProjectMemberRow.project_id)
        )
        for pid, cnt in (await session.execute(counts_stmt)).all():
            member_count_by_project[pid] = int(cnt)

    # --- shared-member edges (center ↔ each peer) ----------------------
    # We compute edges only from the center outward because v1 renders
    # a hub-and-spoke — the center cluster IS the current project, and
    # an edge to a peer means "these two share people." Peer-to-peer
    # edges are a v2 addition (they produce a more network-y look at
    # the cost of an O(peers^2) query).
    edges: list[dict[str, Any]] = []
    if peer_project_ids:
        # Grab the full membership of each relevant project in one shot.
        all_mem_stmt = select(
            ProjectMemberRow.project_id, ProjectMemberRow.user_id
        ).where(ProjectMemberRow.project_id.in_(relevant_ids))
        membership_by_project: dict[str, set[str]] = {
            pid: set() for pid in relevant_ids
        }
        for pid, uid in (await session.execute(all_mem_stmt)).all():
            membership_by_project.setdefault(pid, set()).add(uid)

        center_members = membership_by_project.get(center_project_id, set())
        for pid in peer_project_ids:
            peer_members = membership_by_project.get(pid, set())
            overlap = sorted(center_members & peer_members)
            if overlap:
                edges.append(
                    {
                        "from_project_id": center_project_id,
                        "to_project_id": pid,
                        "kind": "shared_member",
                        "weight": len(overlap),
                        "shared_users": overlap,
                    }
                )

    # --- per-peer badges: open_risks + last_activity_at -----------------
    # Both are single-column aggregates with a project_id filter; no
    # batched version wins over the straightforward loop at v1 scale
    # (demo = 2-3 peer projects; a real org might have 10-30). If peer
    # count crosses 50 we'd switch to a single GROUP BY per-metric.
    peers_payload: list[dict[str, Any]] = []
    for pid in peer_project_ids:
        peer_row = peer_rows_by_id.get(pid)
        if peer_row is None:
            # User has membership but the project was deleted — skip
            # quietly rather than 500ing. The orphan row will get GC'd
            # via CASCADE on the next schema migration.
            continue
        open_risks = await _count_open_risks(session, pid)
        last_at = await _last_activity_at(session, pid)
        peers_payload.append(
            {
                "id": peer_row.id,
                "title": peer_row.title,
                "role": my_role_by_project.get(pid, "member"),
                "member_count": member_count_by_project.get(pid, 0),
                "open_risks": open_risks,
                "last_activity_at": last_at.isoformat() if last_at else None,
            }
        )

    # Sort peers by recency (most recently active first, unknown last)
    # so the most relevant org context clusters near the center visually.
    def _sort_key(p: dict[str, Any]) -> tuple[int, str]:
        ts = p.get("last_activity_at")
        # None sorts after any real timestamp
        return (0 if ts else 1, ts or "")

    peers_payload.sort(key=_sort_key)
    # Within the "has a timestamp" bucket, newest first — we inverted
    # the sort key above by timestamp ascending, so flip that subset.
    # The simplest correct form: sort desc by ts, None-last separately.
    with_ts = [p for p in peers_payload if p.get("last_activity_at")]
    without_ts = [p for p in peers_payload if not p.get("last_activity_at")]
    with_ts.sort(key=lambda p: p["last_activity_at"], reverse=True)
    peers_payload = with_ts + without_ts

    return {
        "center": {"id": center_row.id, "title": center_row.title},
        "peers": peers_payload,
        "edges": edges,
    }


__all__ = ["org_graph_for_user"]
