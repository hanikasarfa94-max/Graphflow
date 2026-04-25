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

Query shape: a single call fans out to a small constant number of
batched queries (roughly 15) regardless of team size. Each batched
query is grouped by user_id and the result zipped back onto members
in Python. This replaces an older per-member loop that ran O(15 × N)
round-trips for an N-member team.
"""
from __future__ import annotations

from collections import defaultdict
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
    ProjectMemberRow,
    RiskRow,
    RoutedSignalRow,
    SilentConsensusRow,
    TaskRow,
    TaskScoreRow,
    UserRow,
    session_scope,
)


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

            now = datetime.now(timezone.utc)
            window_30d = now - timedelta(days=30)
            user_ids = [m.user_id for m in members]

            # ---- batch 1: users ---------------------------------------
            user_rows = list(
                (
                    await session.execute(
                        select(UserRow).where(UserRow.id.in_(user_ids))
                    )
                )
                .scalars()
                .all()
            )
            users_by_id: dict[str, UserRow] = {u.id: u for u in user_rows}

            # ---- batch 2: decisions (count + recent ids) --------------
            decisions_rows = list(
                (
                    await session.execute(
                        select(
                            DecisionRow.resolver_id,
                            DecisionRow.id,
                            DecisionRow.created_at,
                        )
                        .where(DecisionRow.project_id == project_id)
                        .where(DecisionRow.resolver_id.in_(user_ids))
                        .order_by(DecisionRow.created_at.desc())
                    )
                ).all()
            )
            decisions_total: dict[str, int] = defaultdict(int)
            decisions_recent: dict[str, list[str]] = defaultdict(list)
            decisions_last: dict[str, datetime] = {}
            for resolver_id, did, created_at in decisions_rows:
                decisions_total[resolver_id] += 1
                if len(decisions_recent[resolver_id]) < _RECENT_ID_LIMIT:
                    decisions_recent[resolver_id].append(did)
                # rows are DESC-ordered, so the first is MAX per resolver
                if resolver_id not in decisions_last:
                    decisions_last[resolver_id] = created_at

            # ---- batch 3: routings (answered, i.e. reply_json set) ----
            routings_rows = list(
                (
                    await session.execute(
                        select(
                            RoutedSignalRow.target_user_id,
                            RoutedSignalRow.id,
                        )
                        .where(RoutedSignalRow.project_id == project_id)
                        .where(RoutedSignalRow.target_user_id.in_(user_ids))
                        .where(RoutedSignalRow.reply_json.is_not(None))
                        .order_by(RoutedSignalRow.created_at.desc())
                    )
                ).all()
            )
            routings_total: dict[str, int] = defaultdict(int)
            routings_recent: dict[str, list[str]] = defaultdict(list)
            for target_uid, rid in routings_rows:
                routings_total[target_uid] += 1
                if len(routings_recent[target_uid]) < _RECENT_ID_LIMIT:
                    routings_recent[target_uid].append(rid)

            # ---- batch 4: open risks on this project ------------------
            # RiskRow has no per-user owner column; mirror
            # profile_tallies — the set of open risks on this project is
            # credited wholesale to every member with role='owner'. One
            # query fetches the shared list; non-owners get zeros.
            risks_rows = list(
                (
                    await session.execute(
                        select(RiskRow.id)
                        .where(RiskRow.project_id == project_id)
                        .where(RiskRow.status == "open")
                        .order_by(RiskRow.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            risks_total_shared = len(risks_rows)
            risks_recent_shared = risks_rows[:_RECENT_ID_LIMIT]

            # ---- batch 5: completed tasks (task_id, user_id) ----------
            # Task-id dedupe per user; a task may have been (re-)assigned
            # more than once. DESC by assignment.created_at so "recent"
            # picks the freshest binding per task.
            tasks_rows = list(
                (
                    await session.execute(
                        select(
                            AssignmentRow.user_id,
                            TaskRow.id,
                        )
                        .join(
                            AssignmentRow,
                            AssignmentRow.task_id == TaskRow.id,
                        )
                        .where(TaskRow.project_id == project_id)
                        .where(TaskRow.status == "done")
                        .where(AssignmentRow.user_id.in_(user_ids))
                        .order_by(AssignmentRow.created_at.desc())
                    )
                ).all()
            )
            tasks_seen: dict[str, set[str]] = defaultdict(set)
            tasks_recent: dict[str, list[str]] = defaultdict(list)
            for uid, tid in tasks_rows:
                if tid in tasks_seen[uid]:
                    continue
                tasks_seen[uid].add(tid)
                if len(tasks_recent[uid]) < _RECENT_ID_LIMIT:
                    tasks_recent[uid].append(tid)

            # ---- batch 5b: task scores (Phase U) ----------------------
            # Joins task_scores → plan_tasks to scope by project, then
            # buckets by assignee for the perf rollup. quality_index =
            # weighted mean of {good=1.0, ok=0.5, needs_work=0.0};
            # treat as "0..1 quality score" surfaceable as a percent.
            task_score_rows = list(
                (
                    await session.execute(
                        select(
                            TaskScoreRow.assignee_user_id,
                            TaskScoreRow.quality,
                        )
                        .join(TaskRow, TaskRow.id == TaskScoreRow.task_id)
                        .where(TaskRow.project_id == project_id)
                        .where(TaskScoreRow.assignee_user_id.in_(user_ids))
                    )
                ).all()
            )
            task_score_buckets: dict[str, dict[str, int]] = defaultdict(
                lambda: {"good": 0, "ok": 0, "needs_work": 0, "total": 0}
            )
            for assignee_uid, quality in task_score_rows:
                bucket = task_score_buckets[assignee_uid]
                if quality in ("good", "ok", "needs_work"):
                    bucket[quality] += 1
                bucket["total"] += 1

            # ---- batch 6: dissent (bucketed per user) -----------------
            dissent_rows = list(
                (
                    await session.execute(
                        select(
                            DissentRow.dissenter_user_id,
                            DissentRow.validated_by_outcome,
                        )
                        .join(
                            DecisionRow,
                            DecisionRow.id == DissentRow.decision_id,
                        )
                        .where(DecisionRow.project_id == project_id)
                        .where(DissentRow.dissenter_user_id.in_(user_ids))
                    )
                ).all()
            )
            dissent_buckets: dict[str, dict[str, int]] = defaultdict(
                lambda: {
                    "total": 0,
                    "supported": 0,
                    "refuted": 0,
                    "still_open": 0,
                }
            )
            for diss_uid, validated in dissent_rows:
                bucket = dissent_buckets[diss_uid]
                bucket["total"] += 1
                if validated == "supported":
                    bucket["supported"] += 1
                elif validated == "refuted":
                    bucket["refuted"] += 1
                else:
                    bucket["still_open"] += 1

            # ---- batch 7: silent-consensus ratified per ratifier ------
            # Ratifier = DecisionRow.resolver_id on the ratified decision.
            sc_rows = list(
                (
                    await session.execute(
                        select(
                            DecisionRow.resolver_id,
                            SilentConsensusRow.id,
                            SilentConsensusRow.ratified_at,
                        )
                        .join(
                            DecisionRow,
                            DecisionRow.id
                            == SilentConsensusRow.ratified_decision_id,
                        )
                        .where(SilentConsensusRow.project_id == project_id)
                        .where(SilentConsensusRow.status == "ratified")
                        .where(DecisionRow.resolver_id.in_(user_ids))
                        .order_by(SilentConsensusRow.ratified_at.desc())
                    )
                ).all()
            )
            sc_count: dict[str, int] = defaultdict(int)
            sc_recent: dict[str, list[str]] = defaultdict(list)
            for ratifier_id, sc_id, _ in sc_rows:
                sc_count[ratifier_id] += 1
                if len(sc_recent[ratifier_id]) < _RECENT_ID_LIMIT:
                    sc_recent[ratifier_id].append(sc_id)

            # ---- batch 8: messages in 30d (count + MAX) ---------------
            messages_30d_rows = list(
                (
                    await session.execute(
                        select(
                            MessageRow.author_id,
                            func.count(MessageRow.id),
                        )
                        .where(MessageRow.project_id == project_id)
                        .where(MessageRow.author_id.in_(user_ids))
                        .where(MessageRow.created_at >= window_30d)
                        .group_by(MessageRow.author_id)
                    )
                ).all()
            )
            messages_30d: dict[str, int] = {
                uid: int(n or 0) for uid, n in messages_30d_rows
            }

            # ---- batch 9: last_message per user (all time) ------------
            last_message_rows = list(
                (
                    await session.execute(
                        select(
                            MessageRow.author_id,
                            func.max(MessageRow.created_at),
                        )
                        .where(MessageRow.project_id == project_id)
                        .where(MessageRow.author_id.in_(user_ids))
                        .group_by(MessageRow.author_id)
                    )
                ).all()
            )
            last_message: dict[str, datetime] = {
                uid: t for uid, t in last_message_rows if t is not None
            }

            # last_decision piggybacked off the decisions batch above
            last_decision = decisions_last

            # ---- batch 10: last_assignment per user -------------------
            last_assignment_rows = list(
                (
                    await session.execute(
                        select(
                            AssignmentRow.user_id,
                            func.max(AssignmentRow.created_at),
                        )
                        .where(AssignmentRow.project_id == project_id)
                        .where(AssignmentRow.user_id.in_(user_ids))
                        .group_by(AssignmentRow.user_id)
                    )
                ).all()
            )
            last_assignment: dict[str, datetime] = {
                uid: t for uid, t in last_assignment_rows if t is not None
            }

            # ---- batch 11-14: observed-profile inputs (global, per user)
            # We only need what `_observed_skill_tags` looks at, not the
            # whole compute_profile payload:
            #   * messages_posted_30d  (threshold 10)
            #   * decisions_resolved_30d (threshold 1)
            #   * risks_owned           (threshold 1)
            #   * routings_answered_30d (threshold 3; proxied via
            #     AssignmentRow.resolved_at, same rule as compute_profile)
            # Each is a single GROUP-BY query over the full member set;
            # project scope is intentionally dropped for symmetry with
            # profile_tallies which computes cross-project tallies.
            global_messages_30d = _dict_from_group_count(
                await session.execute(
                    select(
                        MessageRow.author_id,
                        func.count(MessageRow.id),
                    )
                    .where(MessageRow.author_id.in_(user_ids))
                    .where(MessageRow.created_at >= window_30d)
                    .group_by(MessageRow.author_id)
                )
            )
            global_decisions_30d = _dict_from_group_count(
                await session.execute(
                    select(
                        DecisionRow.resolver_id,
                        func.count(DecisionRow.id),
                    )
                    .where(DecisionRow.resolver_id.in_(user_ids))
                    .where(DecisionRow.created_at >= window_30d)
                    .group_by(DecisionRow.resolver_id)
                )
            )
            # risks_owned: open risks on any project where the user is
            # role='owner'. Two-step join via ProjectMemberRow keeps this
            # to one query.
            global_risks_owned_rows = list(
                (
                    await session.execute(
                        select(
                            ProjectMemberRow.user_id,
                            func.count(RiskRow.id),
                        )
                        .join(
                            RiskRow,
                            RiskRow.project_id == ProjectMemberRow.project_id,
                        )
                        .where(ProjectMemberRow.user_id.in_(user_ids))
                        .where(ProjectMemberRow.role == "owner")
                        .where(RiskRow.status == "open")
                        .group_by(ProjectMemberRow.user_id)
                    )
                ).all()
            )
            global_risks_owned = {
                uid: int(n or 0) for uid, n in global_risks_owned_rows
            }
            global_routings_30d = _dict_from_group_count(
                await session.execute(
                    select(
                        AssignmentRow.user_id,
                        func.count(AssignmentRow.id),
                    )
                    .where(AssignmentRow.user_id.in_(user_ids))
                    .where(AssignmentRow.resolved_at.is_not(None))
                    .where(AssignmentRow.resolved_at >= window_30d)
                    .group_by(AssignmentRow.user_id)
                )
            )

            # ---- assemble records -------------------------------------
            records: list[dict[str, Any]] = []
            for m in members:
                user = users_by_id.get(m.user_id)
                if user is None:
                    continue

                if m.role == "owner":
                    risks_ids = list(risks_recent_shared)
                    risks_count = risks_total_shared
                else:
                    risks_ids = []
                    risks_count = 0

                candidates = [
                    t
                    for t in (
                        last_message.get(m.user_id),
                        last_decision.get(m.user_id),
                        last_assignment.get(m.user_id),
                    )
                    if t is not None
                ]
                last_active = max(candidates) if candidates else None

                profile = dict(user.profile or {})
                declared = [
                    str(a)
                    for a in (profile.get("declared_abilities") or [])
                ]
                observed_set = _observed_skill_tags_from_counts(
                    messages_30d=global_messages_30d.get(m.user_id, 0),
                    decisions_30d=global_decisions_30d.get(m.user_id, 0),
                    risks_owned=global_risks_owned.get(m.user_id, 0),
                    routings_30d=global_routings_30d.get(m.user_id, 0),
                )
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
                            "count": decisions_total.get(m.user_id, 0),
                            "ids": list(
                                decisions_recent.get(m.user_id, [])
                            ),
                        },
                        "routings_answered": {
                            "count": routings_total.get(m.user_id, 0),
                            "ids": list(
                                routings_recent.get(m.user_id, [])
                            ),
                        },
                        "risks_owned": {
                            "count": risks_count,
                            "ids": risks_ids,
                        },
                        "tasks_completed": {
                            "count": len(tasks_seen.get(m.user_id, ())),
                            "ids": list(tasks_recent.get(m.user_id, [])),
                        },
                        # Phase U — quality of completed off-platform
                        # work, scored by project owners after the
                        # owner marks done. quality_index rolls
                        # good/ok/needs_work into a 0..1 mean. total=0
                        # → no scores; UI shows "—" for the index.
                        "task_quality": _task_quality_payload(
                            task_score_buckets.get(m.user_id)
                        ),
                        "skills_validated": {
                            "declared": len(declared),
                            "observed": len(observed_set),
                            "overlap": overlap,
                        },
                        "dissent_accuracy": dict(
                            dissent_buckets.get(
                                m.user_id,
                                {
                                    "total": 0,
                                    "supported": 0,
                                    "refuted": 0,
                                    "still_open": 0,
                                },
                            )
                        ),
                        "silent_consensus_ratified": {
                            "count": sc_count.get(m.user_id, 0),
                            "ids": list(sc_recent.get(m.user_id, [])),
                        },
                        "activity_last_30d": {
                            "messages": messages_30d.get(m.user_id, 0),
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


def _dict_from_group_count(result) -> dict[str, int]:
    """Collect a (id, count) GROUP BY result into a dict."""
    return {row[0]: int(row[1] or 0) for row in result.all()}


def _observed_skill_tags_from_counts(
    *,
    messages_30d: int,
    decisions_30d: int,
    risks_owned: int,
    routings_30d: int,
) -> set[str]:
    """Batched-input form of the original `_observed_skill_tags`.

    Mirrors SkillAtlasService._resolve_observed_skills and the previous
    implementation that ran `compute_profile` per-member. Pulled out so
    the loop doesn't need to materialize a full ProfileObserved dataclass
    just to thresh four integers."""
    out: set[str] = set()
    if messages_30d >= 10:
        out.add("communication")
    if decisions_30d >= 1:
        out.add("decision-making")
    if risks_owned >= 1:
        out.add("risk-management")
    if routings_30d >= 3:
        out.add("expertise-routing")
    return out


def _observed_skill_tags(observed: Any) -> set[str]:
    """Compatibility shim for any external caller still passing a
    ProfileObserved dataclass. Internal callers use the batched form
    above."""
    return _observed_skill_tags_from_counts(
        messages_30d=observed.messages_posted_30d,
        decisions_30d=observed.decisions_resolved_30d,
        risks_owned=observed.risks_owned,
        routings_30d=observed.routings_answered_30d,
    )


def _task_quality_payload(
    bucket: dict[str, int] | None,
) -> dict[str, Any]:
    """Roll a per-user score bucket into a payload the perf surface
    renders. quality_index = (good + 0.5*ok) / total, in [0, 1]; null
    when no scores."""
    if not bucket or bucket.get("total", 0) == 0:
        return {
            "good": 0,
            "ok": 0,
            "needs_work": 0,
            "total": 0,
            "quality_index": None,
        }
    good = int(bucket.get("good", 0))
    ok = int(bucket.get("ok", 0))
    nw = int(bucket.get("needs_work", 0))
    total = good + ok + nw
    idx = (good + 0.5 * ok) / total if total else None
    return {
        "good": good,
        "ok": ok,
        "needs_work": nw,
        "total": total,
        "quality_index": round(idx, 3) if idx is not None else None,
    }


__all__ = ["PerfAggregationService"]
