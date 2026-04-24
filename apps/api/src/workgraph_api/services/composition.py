"""CompositionService — org-composition diagnostic (HR / COO wedge).

Read-only v0. Given a project, returns a health snapshot of the group's
authority structure:

  * per-member authority load (how many gates + voter pools they sit in,
    plus observed engagement over the last 30 days)
  * per-class coverage map (gate-keeper + voter pool + health bucket)
  * shared-authority overlaps (pairs of users who co-hold authority on
    one or more classes)
  * summary counters (member count, classes covered, SPOF count, most-
    loaded user)

Design notes:

  * Health buckets for a class's voter pool are
    spof  → pool_size == 1  (single point of failure, red)
    thin  → pool_size == 2  (brittle, amber)
    healthy → pool_size >= 3 (green)

    The voter pool for a class is ``owners ∪ {gate_keeper_for_class}``
    (gate_keeper de-duped if already an owner) — same shape as the
    GatedProposalService vote pool. Classes without a named gate-keeper
    fall back to just the owner set.

  * load_score = gate_count * 2 + vote_pool_count. Gates weigh double
    because being a named gate-keeper is strictly harder duty than
    being one voice in a pool. Deliberately coarse — this is diagnostic,
    not a scheduling optimization.

  * active_in_flight_count counts GatedProposalRows where the user is
    either the named gate-keeper (status='pending') OR in voter_pool
    (status='in_vote'). It's the user's current governance workload.

  * Dissent + decisions_resolved are 30-day counts pulled through the
    persistence repos directly — no separate materialized tally.

v1 (not in this service): drag-rebalance mutations, simulate-departure,
suggested rebalance ranked by risk reduction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    DecisionRow,
    DissentRow,
    GatedProposalRow,
    ProjectMemberRepository,
    ProjectRow,
    UserRow,
    VoteRow,
    session_scope,
)

from .gated_proposals import VALID_DECISION_CLASSES, VOTE_SUBJECT_KIND


class CompositionError(Exception):
    """Raised for service-layer failures mapped to 4xx by the router."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class _MemberCtx:
    user_id: str
    display_name: str
    role: str


def _health(pool_size: int) -> str:
    if pool_size <= 1:
        return "spof"
    if pool_size == 2:
        return "thin"
    return "healthy"


class CompositionService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def compose(self, *, project_id: str) -> dict[str, Any]:
        """Return the composition diagnostic payload for a project.

        Caller is responsible for membership enforcement (router-layer).
        This method assumes project_id exists; if it doesn't, returns a
        payload flagged with ``project_not_found`` so the router can map
        it to 404 without a second round-trip.
        """
        now = datetime.now(timezone.utc)
        window_30d = now - timedelta(days=30)

        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                raise CompositionError("project_not_found", status=404)

            pm_repo = ProjectMemberRepository(session)
            member_rows = await pm_repo.list_for_project(project_id)
            member_ids = [m.user_id for m in member_rows]
            role_by_user = {m.user_id: (m.role or "member") for m in member_rows}

            # Batch-load user display names in one round-trip.
            users_by_id: dict[str, UserRow] = {}
            if member_ids:
                user_rows = (
                    await session.execute(
                        select(UserRow).where(UserRow.id.in_(member_ids))
                    )
                ).scalars().all()
                users_by_id = {u.id: u for u in user_rows}

            # Gate-keeper map keyed to VALID_DECISION_CLASSES — untrusted
            # values in the project JSON are ignored silently (same
            # contract as get_gate_keeper).
            raw_map = dict(project.gate_keeper_map or {})
            gate_map: dict[str, str | None] = {}
            for cls in VALID_DECISION_CLASSES:
                uid = raw_map.get(cls)
                if isinstance(uid, str) and uid and uid in member_ids:
                    gate_map[cls] = uid
                else:
                    gate_map[cls] = None

            owner_ids = sorted(
                [uid for uid, role in role_by_user.items() if role == "owner"]
            )

            # Build per-class voter pool: owners ∪ {gate_keeper}.
            class_rows: list[dict[str, Any]] = []
            # per-user counters
            gate_count: dict[str, int] = {uid: 0 for uid in member_ids}
            vote_pool_count: dict[str, int] = {uid: 0 for uid in member_ids}
            gated_classes_by_user: dict[str, list[str]] = {
                uid: [] for uid in member_ids
            }
            # pairwise co-authority — key = frozenset({a, b}), value = list[class]
            overlaps: dict[frozenset, list[str]] = {}

            for cls in sorted(VALID_DECISION_CLASSES):
                gk = gate_map.get(cls)
                pool_set = set(owner_ids)
                if gk is not None:
                    pool_set.add(gk)
                pool = sorted(pool_set)
                pool_size = len(pool)
                class_rows.append(
                    {
                        "decision_class": cls,
                        "gate_keeper_user_id": gk,
                        "voter_pool": pool,
                        "pool_size": pool_size,
                        "health": _health(pool_size),
                    }
                )
                if gk is not None:
                    gate_count[gk] = gate_count.get(gk, 0) + 1
                    gated_classes_by_user.setdefault(gk, []).append(cls)
                for uid in pool:
                    if uid in vote_pool_count:
                        vote_pool_count[uid] += 1
                # Pairwise overlap for this class's pool.
                for i, a in enumerate(pool):
                    for b in pool[i + 1 :]:
                        key = frozenset({a, b})
                        overlaps.setdefault(key, []).append(cls)

            # Active in-flight count per member.
            active_in_flight: dict[str, int] = {uid: 0 for uid in member_ids}
            proposal_rows = (
                await session.execute(
                    select(GatedProposalRow).where(
                        GatedProposalRow.project_id == project_id,
                        GatedProposalRow.status.in_(("pending", "in_vote")),
                    )
                )
            ).scalars().all()
            for row in proposal_rows:
                if row.status == "pending":
                    gk = row.gate_keeper_user_id
                    if gk in active_in_flight:
                        active_in_flight[gk] += 1
                elif row.status == "in_vote":
                    for uid in row.voter_pool or []:
                        if uid in active_in_flight:
                            active_in_flight[uid] += 1

            # votes_cast_30d — one grouped query over members.
            votes_cast_30d: dict[str, int] = {uid: 0 for uid in member_ids}
            if member_ids:
                vote_rows = (
                    await session.execute(
                        select(
                            VoteRow.voter_user_id, func.count(VoteRow.id)
                        )
                        .where(
                            VoteRow.subject_kind == VOTE_SUBJECT_KIND,
                            VoteRow.voter_user_id.in_(member_ids),
                            VoteRow.updated_at >= window_30d,
                        )
                        .group_by(VoteRow.voter_user_id)
                    )
                ).all()
                for uid, n in vote_rows:
                    votes_cast_30d[uid] = int(n or 0)

            # decisions_resolved_30d — grouped count of DecisionRow.resolver_id
            # scoped to this project + window.
            decisions_resolved_30d: dict[str, int] = {uid: 0 for uid in member_ids}
            if member_ids:
                dec_rows = (
                    await session.execute(
                        select(
                            DecisionRow.resolver_id, func.count(DecisionRow.id)
                        )
                        .where(
                            DecisionRow.project_id == project_id,
                            DecisionRow.resolver_id.in_(member_ids),
                            DecisionRow.created_at >= window_30d,
                        )
                        .group_by(DecisionRow.resolver_id)
                    )
                ).all()
                for uid, n in dec_rows:
                    decisions_resolved_30d[uid] = int(n or 0)

            # dissent_events_30d — join DissentRow→DecisionRow to scope to
            # this project + window.
            dissent_events_30d: dict[str, int] = {uid: 0 for uid in member_ids}
            if member_ids:
                dissent_rows = (
                    await session.execute(
                        select(
                            DissentRow.dissenter_user_id,
                            func.count(DissentRow.id),
                        )
                        .join(
                            DecisionRow,
                            DecisionRow.id == DissentRow.decision_id,
                        )
                        .where(
                            DecisionRow.project_id == project_id,
                            DissentRow.dissenter_user_id.in_(member_ids),
                            DissentRow.created_at >= window_30d,
                        )
                        .group_by(DissentRow.dissenter_user_id)
                    )
                ).all()
                for uid, n in dissent_rows:
                    dissent_events_30d[uid] = int(n or 0)

        # ---------------- build output ----------------
        members_out: list[dict[str, Any]] = []
        most_loaded_uid: str | None = None
        most_loaded_score = -1
        for uid in member_ids:
            user_row = users_by_id.get(uid)
            display = (
                (user_row.display_name or user_row.username)
                if user_row is not None
                else uid
            )
            gc = gate_count.get(uid, 0)
            vpc = vote_pool_count.get(uid, 0)
            load = gc * 2 + vpc
            members_out.append(
                {
                    "user_id": uid,
                    "display_name": display,
                    "role": role_by_user.get(uid, "member"),
                    "gate_count": gc,
                    "vote_pool_count": vpc,
                    "gated_classes": sorted(gated_classes_by_user.get(uid, [])),
                    "active_in_flight_count": active_in_flight.get(uid, 0),
                    "votes_cast_30d": votes_cast_30d.get(uid, 0),
                    "dissent_events_30d": dissent_events_30d.get(uid, 0),
                    "decisions_resolved_30d": decisions_resolved_30d.get(uid, 0),
                    "load_score": load,
                }
            )
            if load > most_loaded_score:
                most_loaded_score = load
                most_loaded_uid = uid
        # Stable sort by load desc, then by display_name asc for UI.
        members_out.sort(
            key=lambda m: (-m["load_score"], (m["display_name"] or "").lower())
        )

        overlaps_out = [
            {
                "user_a_id": sorted(pair)[0],
                "user_b_id": sorted(pair)[1],
                "shared_classes": sorted(classes),
            }
            for pair, classes in overlaps.items()
            # Single-owner + no gate still produces a length-1 pool, which
            # overlaps.setdefault won't populate (no pair). Filter to
            # defensive-proof the shape anyway.
            if len(pair) == 2 and classes
        ]
        overlaps_out.sort(
            key=lambda o: (o["user_a_id"], o["user_b_id"])
        )

        spof_count = sum(1 for c in class_rows if c["health"] == "spof")
        classes_covered = sum(
            1 for c in class_rows if c["gate_keeper_user_id"] is not None
        )

        return {
            "composition": {
                "members": members_out,
                "classes": class_rows,
                "overlaps": overlaps_out,
                "summary": {
                    "total_members": len(member_ids),
                    "total_owners": len(owner_ids),
                    "classes_covered": classes_covered,
                    "spof_count": spof_count,
                    "most_loaded_user_id": (
                        most_loaded_uid if most_loaded_score >= 0 else None
                    ),
                    "most_loaded_score": (
                        most_loaded_score if most_loaded_score >= 0 else 0
                    ),
                },
            }
        }


__all__ = ["CompositionService", "CompositionError"]
