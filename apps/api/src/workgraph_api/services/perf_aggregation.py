"""Team performance aggregation — project-scoped, compute-on-read.

Powers `GET /api/projects/{project_id}/team/perf`, the project-admin
observability panel. One record per project member, with per-metric
counts + the 10 most recent ids so the UI can deep-link.

Design mirrors `profile_tallies.compute_profile`: plain DB counts
scoped to the project, no denormalized columns, no cache. The graph
is the source of truth; the panel projects it.

Metric definitions (all scoped to `project_id`):
  * decisions_made    — DecisionRow.resolver_id == user
  * routings_answered — RoutedSignalRow.target_user_id == user AND reply_json IS NOT NULL
  * risks_owned       — RiskRow.status == 'open' on this project, credited
                        to members with role == 'owner' (same semantic as
                        profile_tallies — RiskRow has no per-user owner)
  * tasks_completed   — TaskRow.status == 'done' with an AssignmentRow
                        (active or resolved) binding it to the user
  * activity_last_30d — MessageRow count + MAX(created_at) across
                        messages / decisions / assignments
  * skills_validated  — declared / observed / overlap counts lifted
                        from UserRow.profile and profile_tallies
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    AssignmentRow,
    DecisionRow,
    DissentRow,
    MessageRow,
    ProjectMemberRepository,
    RiskRow,
    RoutedSignalRow,
    SilentConsensusRepository,
    TaskRow,
    UserRepository,
    session_scope,
)

from .profile_tallies import compute_profile


# Number of most-recent ids to surface per metric. The UI shows one
# deep-link per count; more than 10 is rarely useful and keeps the
# payload small.
_RECENT_ID_LIMIT = 10


class PerfAggregationService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def is_project_admin(
        self, *, project_id: str, user_id: str
    ) -> bool:
        """Admin = role 'owner' AND license_tier 'full'. Observers and
        task_scoped members (even if 'owner' role) cannot see the
        panel; in practice owners are always 'full' tier, but the
        license gate keeps the contract crisp for v2 when tier
        changes become more common."""
        async with session_scope(self._sessionmaker) as session:
            for r in await ProjectMemberRepository(
                session
            ).list_for_project(project_id):
                if r.user_id == user_id:
                    return (
                        r.role == "owner"
                        and (r.license_tier or "full") == "full"
                    )
        return False

    async def team_perf(
        self, *, project_id: str
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            members = await ProjectMemberRepository(
                session
            ).list_for_project(project_id)
            if not members:
                return []

            user_repo = UserRepository(session)
            now = datetime.now(timezone.utc)
            window_30d = now - timedelta(days=30)

            records: list[dict[str, Any]] = []
            for m in members:
                user = await user_repo.get(m.user_id)
                if user is None:
                    continue

                decisions = await self._recent(
                    session,
                    select(DecisionRow.id)
                    .where(DecisionRow.project_id == project_id)
                    .where(DecisionRow.resolver_id == m.user_id)
                    .order_by(DecisionRow.created_at.desc()),
                )
                decisions_total = await self._count(
                    session,
                    select(func.count(DecisionRow.id))
                    .where(DecisionRow.project_id == project_id)
                    .where(DecisionRow.resolver_id == m.user_id),
                )

                routings = await self._recent(
                    session,
                    select(RoutedSignalRow.id)
                    .where(RoutedSignalRow.project_id == project_id)
                    .where(RoutedSignalRow.target_user_id == m.user_id)
                    .where(RoutedSignalRow.reply_json.is_not(None))
                    .order_by(RoutedSignalRow.created_at.desc()),
                )
                routings_total = await self._count(
                    session,
                    select(func.count(RoutedSignalRow.id))
                    .where(RoutedSignalRow.project_id == project_id)
                    .where(RoutedSignalRow.target_user_id == m.user_id)
                    .where(RoutedSignalRow.reply_json.is_not(None)),
                )

                # Risks: RiskRow has no per-user owner column. Mirror
                # profile_tallies semantics — open risks on this project
                # are "owned" by whoever holds role='owner'. Non-owner
                # members get 0.
                if m.role == "owner":
                    risks = await self._recent(
                        session,
                        select(RiskRow.id)
                        .where(RiskRow.project_id == project_id)
                        .where(RiskRow.status == "open")
                        .order_by(RiskRow.created_at.desc()),
                    )
                    risks_total = await self._count(
                        session,
                        select(func.count(RiskRow.id))
                        .where(RiskRow.project_id == project_id)
                        .where(RiskRow.status == "open"),
                    )
                else:
                    risks = []
                    risks_total = 0

                # Tasks completed: TaskRow.status == 'done' with an
                # AssignmentRow binding it to this user. We include
                # resolved assignments too — unassignment before the
                # task flipped done means we'd undercount; a completed
                # task the user touched at any point still credits
                # them. Dedup task_ids because a task may have been
                # (re-)assigned more than once.
                tasks_rows = list(
                    (
                        await session.execute(
                            select(TaskRow.id, AssignmentRow.created_at)
                            .join(
                                AssignmentRow,
                                AssignmentRow.task_id == TaskRow.id,
                            )
                            .where(TaskRow.project_id == project_id)
                            .where(TaskRow.status == "done")
                            .where(AssignmentRow.user_id == m.user_id)
                            .order_by(AssignmentRow.created_at.desc())
                        )
                    ).all()
                )
                seen_task_ids: set[str] = set()
                tasks_recent: list[str] = []
                for tid, _ in tasks_rows:
                    if tid in seen_task_ids:
                        continue
                    seen_task_ids.add(tid)
                    if len(tasks_recent) < _RECENT_ID_LIMIT:
                        tasks_recent.append(tid)
                tasks_total = len(seen_task_ids)

                # Dissent accuracy — count the member's dissents on
                # decisions within this project, bucketed by validation
                # state. `still_open` is the explicit-null bucket so the
                # UI can render (supported + refuted) / total as the
                # judgment accuracy score.
                dissent_rows = list(
                    (
                        await session.execute(
                            select(DissentRow.validated_by_outcome)
                            .join(
                                DecisionRow,
                                DecisionRow.id == DissentRow.decision_id,
                            )
                            .where(DecisionRow.project_id == project_id)
                            .where(
                                DissentRow.dissenter_user_id == m.user_id
                            )
                        )
                    ).all()
                )
                dissent_bucket = {
                    "total": 0,
                    "supported": 0,
                    "refuted": 0,
                    "still_open": 0,
                }
                for (validated,) in dissent_rows:
                    dissent_bucket["total"] += 1
                    if validated == "supported":
                        dissent_bucket["supported"] += 1
                    elif validated == "refuted":
                        dissent_bucket["refuted"] += 1
                    else:
                        # Treat both null (not yet observed) and the
                        # explicit 'still_open' as still-open for the
                        # panel view. Separate counting is a v2
                        # concern; v1 has no code path that writes
                        # 'still_open' anyway.
                        dissent_bucket["still_open"] += 1

                # Phase 1.A — silent-consensus ratified count.
                # Ratification IS the action being measured here: the
                # ratifier crystallized group agreement into a decision.
                # Stored on DecisionRow.resolver_id, joined through
                # SilentConsensusRow.ratified_decision_id.
                sc_count, sc_recent = await SilentConsensusRepository(
                    session
                ).count_ratified_by_user_in_project(
                    project_id=project_id, user_id=m.user_id
                )

                messages_30d = await self._count(
                    session,
                    select(func.count(MessageRow.id))
                    .where(MessageRow.project_id == project_id)
                    .where(MessageRow.author_id == m.user_id)
                    .where(MessageRow.created_at >= window_30d),
                )

                # Last-active across project-scoped emissions.
                last_message = (
                    await session.execute(
                        select(func.max(MessageRow.created_at))
                        .where(MessageRow.project_id == project_id)
                        .where(MessageRow.author_id == m.user_id)
                    )
                ).scalar_one_or_none()
                last_decision = (
                    await session.execute(
                        select(func.max(DecisionRow.created_at))
                        .where(DecisionRow.project_id == project_id)
                        .where(DecisionRow.resolver_id == m.user_id)
                    )
                ).scalar_one_or_none()
                last_assignment = (
                    await session.execute(
                        select(func.max(AssignmentRow.created_at))
                        .where(AssignmentRow.project_id == project_id)
                        .where(AssignmentRow.user_id == m.user_id)
                    )
                ).scalar_one_or_none()
                candidates = [
                    t
                    for t in (last_message, last_decision, last_assignment)
                    if t is not None
                ]
                last_active = max(candidates) if candidates else None

                # Skills: reuse compute_profile's observed set via the
                # same rules the atlas uses. Declared count comes from
                # the user's stored profile; overlap is the count of
                # declared tokens that appear as observed signals
                # (case-insensitive).
                profile = dict(user.profile or {})
                declared = [
                    str(a) for a in (profile.get("declared_abilities") or [])
                ]
                tallies = await compute_profile(session, m.user_id)
                observed_set = _observed_skill_tags(tallies.observed)
                declared_lower = {d.lower() for d in declared}
                overlap = len(observed_set & declared_lower)

                records.append(
                    {
                        "user_id": user.id,
                        "display_name": user.display_name or user.username,
                        "username": user.username,
                        "role_in_project": m.role,
                        "license_tier": m.license_tier or "full",
                        "decisions_made": {
                            "count": decisions_total,
                            "ids": decisions,
                        },
                        "routings_answered": {
                            "count": routings_total,
                            "ids": routings,
                        },
                        "risks_owned": {
                            "count": risks_total,
                            "ids": risks,
                        },
                        "tasks_completed": {
                            "count": tasks_total,
                            "ids": tasks_recent,
                        },
                        "skills_validated": {
                            "declared": len(declared),
                            "observed": len(observed_set),
                            "overlap": overlap,
                        },
                        "dissent_accuracy": dissent_bucket,
                        "silent_consensus_ratified": {
                            "count": sc_count,
                            "ids": sc_recent,
                        },
                        "activity_last_30d": {
                            "messages": messages_30d,
                            "last_active_at": (
                                last_active.isoformat()
                                if last_active is not None
                                else None
                            ),
                        },
                    }
                )
            return records

    @staticmethod
    async def _count(session, stmt) -> int:
        raw = (await session.execute(stmt)).scalar_one_or_none()
        return int(raw or 0)

    @staticmethod
    async def _recent(session, stmt) -> list[str]:
        rows = (await session.execute(stmt.limit(_RECENT_ID_LIMIT))).all()
        return [r[0] for r in rows]


def _observed_skill_tags(observed: Any) -> set[str]:
    """Mirror SkillAtlasService._resolve_observed_skills without the
    import cycle. Keeps perf independent of the atlas module."""
    out: set[str] = set()
    if observed.messages_posted_30d >= 10:
        out.add("communication")
    if observed.decisions_resolved_30d >= 1:
        out.add("decision-making")
    if observed.risks_owned >= 1:
        out.add("risk-management")
    if observed.routings_answered_30d >= 3:
        out.add("expertise-routing")
    return out


__all__ = ["PerfAggregationService"]
