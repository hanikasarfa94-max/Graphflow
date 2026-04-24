"""Observed-profile tallies — compute-on-read, no schema mutation.

Per docs/north-star.md §"Profile as first-class primitive": every user has a
response profile combining self-declared abilities + *observed* emissions.
This module surfaces the observed half. No new columns, no migrations —
we just count existing rows in rolling windows.

The key design choice (decision 1E carried forward): the graph IS the
state. A user's observed profile is a projection of what they've already
emitted into the graph — messages, decisions, assignments, project
memberships. Recomputing on read keeps it honest: the tallies never
drift from the source of truth because they're derived from it on
every call.

Semantic mapping to the current schema (no RoutingSignalRow yet; see
eng_backlog when/if we add it):
  - messages_posted_*d     → MessageRow.author_id in window
  - decisions_resolved_30d → DecisionRow.resolver_id in window
  - risks_owned            → RiskRow.status='open' on projects where
                             the user has role='owner'
  - routings_answered_30d  → AssignmentRow.resolved_at in window
                             (user acted on a task routed to them)
  - projects_active        → distinct ProjectMemberRow for user
  - last_activity_at       → MAX(created_at) across the user's emissions

If/when RoutingSignalRow lands, swap the `routings_answered_30d` query
to count target_user_id matches with status in {replied, accepted,
declined}; the wire format stays identical.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from workgraph_persistence import (
    AssignmentRow,
    DecisionRow,
    MessageRow,
    ProjectMemberRow,
    RiskRow,
    UserRow,
    VoteRow,
)


@dataclass(frozen=True)
class ProfileObserved:
    """Observed tallies, all non-negative integers."""

    messages_posted_7d: int
    messages_posted_30d: int
    decisions_resolved_30d: int
    risks_owned: int
    routings_answered_30d: int
    projects_active: int
    # Phase S — governance participation. votes_cast_30d counts all
    # verdicts (approve / deny / abstain); the split lets
    # voting_profile consumers distinguish engaged-but-critical voters
    # (many denies) from engaged-and-approving voters (many approves).
    votes_cast_30d: int
    votes_approve_30d: int
    votes_deny_30d: int
    votes_abstain_30d: int


@dataclass(frozen=True)
class ProfileTallies:
    """Full payload — user identity + role distribution + observed."""

    user_id: str
    display_name: str
    role_counts: dict[str, int]
    observed: ProfileObserved
    last_activity_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "display_name": self.display_name,
            "role_counts": dict(self.role_counts),
            "observed": {
                "messages_posted_7d": self.observed.messages_posted_7d,
                "messages_posted_30d": self.observed.messages_posted_30d,
                "decisions_resolved_30d": self.observed.decisions_resolved_30d,
                "risks_owned": self.observed.risks_owned,
                "routings_answered_30d": self.observed.routings_answered_30d,
                "projects_active": self.observed.projects_active,
                "votes_cast_30d": self.observed.votes_cast_30d,
                "votes_approve_30d": self.observed.votes_approve_30d,
                "votes_deny_30d": self.observed.votes_deny_30d,
                "votes_abstain_30d": self.observed.votes_abstain_30d,
            },
            "last_activity_at": (
                self.last_activity_at.isoformat() if self.last_activity_at else None
            ),
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _scalar_count(session: AsyncSession, stmt) -> int:
    """Run a `select(func.count(...))` stmt and return 0 on NULL."""
    raw = (await session.execute(stmt)).scalar_one_or_none()
    return int(raw or 0)


async def compute_profile(
    session: AsyncSession, user_id: str, *, now: datetime | None = None
) -> ProfileTallies:
    """Compute-on-read: returns the user's observed profile snapshot.

    One session, six count queries + one MAX query + a small join for
    role_counts. Each count scopes to a time window (7d / 30d) or to
    the user's open risk surface. No row writes, no cache — the next
    call sees the next state.

    `now` is injectable for deterministic tests; defaults to UTC wall
    clock. Windows are inclusive of rows at the boundary.
    """
    ref_now = now or _utcnow()
    window_7d = ref_now - timedelta(days=7)
    window_30d = ref_now - timedelta(days=30)

    # -- identity + role distribution -----------------------------------
    display_name = (
        await session.execute(
            select(UserRow.display_name).where(UserRow.id == user_id)
        )
    ).scalar_one_or_none() or ""

    role_rows = (
        await session.execute(
            select(ProjectMemberRow.role, func.count(ProjectMemberRow.id))
            .where(ProjectMemberRow.user_id == user_id)
            .group_by(ProjectMemberRow.role)
        )
    ).all()
    role_counts: dict[str, int] = {role: int(n) for role, n in role_rows}
    projects_active = sum(role_counts.values())

    # -- messages (7d + 30d) --------------------------------------------
    messages_7d = await _scalar_count(
        session,
        select(func.count(MessageRow.id)).where(
            MessageRow.author_id == user_id,
            MessageRow.created_at >= window_7d,
        ),
    )
    messages_30d = await _scalar_count(
        session,
        select(func.count(MessageRow.id)).where(
            MessageRow.author_id == user_id,
            MessageRow.created_at >= window_30d,
        ),
    )

    # -- decisions resolved (30d) ---------------------------------------
    decisions_30d = await _scalar_count(
        session,
        select(func.count(DecisionRow.id)).where(
            DecisionRow.resolver_id == user_id,
            DecisionRow.created_at >= window_30d,
        ),
    )

    # -- risks on projects the user owns --------------------------------
    # No RiskRow.owner_id column — we project "risks owned" as open risks
    # on any project where the user's membership role == 'owner'. This
    # matches how owners hold accountability for risk closure today.
    owner_project_ids_subq = (
        select(ProjectMemberRow.project_id)
        .where(
            ProjectMemberRow.user_id == user_id,
            ProjectMemberRow.role == "owner",
        )
        .scalar_subquery()
    )
    risks_owned = await _scalar_count(
        session,
        select(func.count(RiskRow.id)).where(
            RiskRow.project_id.in_(owner_project_ids_subq),
            RiskRow.status == "open",
        ),
    )

    # -- routings answered (30d) ----------------------------------------
    # Proxy until RoutingSignalRow ships: count assignments that were
    # resolved (accepted / completed / declined) by this user in window.
    routings_30d = await _scalar_count(
        session,
        select(func.count(AssignmentRow.id)).where(
            AssignmentRow.user_id == user_id,
            AssignmentRow.resolved_at.is_not(None),
            AssignmentRow.resolved_at >= window_30d,
        ),
    )

    # -- votes (30d) — Phase S governance participation -----------------
    # One query, returns per-verdict counts in the window. GROUP BY
    # verdict keeps it to a single round-trip; Python bucket after.
    vote_rows = (
        await session.execute(
            select(VoteRow.verdict, func.count(VoteRow.id))
            .where(
                VoteRow.voter_user_id == user_id,
                VoteRow.updated_at >= window_30d,
            )
            .group_by(VoteRow.verdict)
        )
    ).all()
    vote_counts = {verdict: int(n) for verdict, n in vote_rows}
    votes_approve_30d = vote_counts.get("approve", 0)
    votes_deny_30d = vote_counts.get("deny", 0)
    votes_abstain_30d = vote_counts.get("abstain", 0)
    votes_cast_30d = votes_approve_30d + votes_deny_30d + votes_abstain_30d

    # -- last activity --------------------------------------------------
    # MAX across the three tables the user can write to directly. We
    # fold NULLs by filtering inside each subquery, then take Python max
    # so one empty table doesn't poison the answer with NULL semantics.
    last_message = (
        await session.execute(
            select(func.max(MessageRow.created_at)).where(
                MessageRow.author_id == user_id
            )
        )
    ).scalar_one_or_none()
    last_decision = (
        await session.execute(
            select(func.max(DecisionRow.created_at)).where(
                DecisionRow.resolver_id == user_id
            )
        )
    ).scalar_one_or_none()
    last_assignment = (
        await session.execute(
            select(func.max(AssignmentRow.created_at)).where(
                AssignmentRow.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    candidates = [t for t in (last_message, last_decision, last_assignment) if t is not None]
    last_activity_at = max(candidates) if candidates else None

    return ProfileTallies(
        user_id=user_id,
        display_name=display_name,
        role_counts=role_counts,
        observed=ProfileObserved(
            messages_posted_7d=messages_7d,
            messages_posted_30d=messages_30d,
            decisions_resolved_30d=decisions_30d,
            risks_owned=risks_owned,
            routings_answered_30d=routings_30d,
            projects_active=projects_active,
            votes_cast_30d=votes_cast_30d,
            votes_approve_30d=votes_approve_30d,
            votes_deny_30d=votes_deny_30d,
            votes_abstain_30d=votes_abstain_30d,
        ),
        last_activity_at=last_activity_at,
    )
