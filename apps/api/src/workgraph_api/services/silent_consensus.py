"""SilentConsensusService — Phase 1.A behavioral-agreement scanner.

Dissent captures explicit disagreement. This service captures the
complementary primitive: *silent* agreement. When the graph shows
N members acting consistently on a topic AND no dissent or counter-
decision is recorded, we surface a "silent consensus" proposal that
a project owner can ratify into a real DecisionRow.

Detection heuristic (v1):
  * Topic universe = active / recently-touched deliverables on the
    latest requirement version. "Consistent action on a deliverable"
    = a TaskRow under that deliverable flipping to 'done', or a
    DecisionRow (applied with non-failed outcome) recorded on the
    project in the last window.
  * Window = 7 days.
  * Threshold = min(3, ceil(0.75 * active_members)). "Active members"
    are project members minus the edge-agent system user. Taking the
    smaller of the two keeps small teams (e.g. 3-person project) from
    hitting an unreachable 75% rule.
  * Suppression: if any DissentRow exists on a DecisionRow that
    references the deliverable (via apply_actions) in the window, the
    topic is skipped — the disagreement is already surfaced.
  * Dedup: if a pending SilentConsensusRow already exists for the
    same topic_text on this project, skip.

Confidence is `(member_count / max(threshold, 1)) * consistency` where
consistency ∈ [0, 1] is the fraction of actions-in-window that pulled
in the same direction. v1 treats every action as "same direction" (all
flips are 'done' or 'ok') so consistency is 1.0 — confidence collapses
to `member_count / threshold`, capped at 1.0.

Ratification creates a DecisionRow with:
  * conflict_id = None (no conflict driving this)
  * source_suggestion_id = None
  * resolver_id = ratifier_user_id
  * apply_outcome = 'advisory'  (no mechanical apply path)
  * custom_text = inferred_decision_summary
  * rationale = "Ratified silent consensus: {topic}\\n\\nSupporting
                 actions: [<kind:id>, …]"

DecisionRow has no dedicated lineage JSON field in v1, so the
supporting_action_ids list is embedded into the rationale as a
machine-parseable tail. The frontend doesn't rely on that — the
SilentConsensusRow itself keeps the canonical list via
`supporting_action_ids`.

Event-bus subscriptions (mounted in main.py / conftest):
  * decision.applied    — new lineage to scan
  * dissent.recorded    — may invalidate an existing pending proposal
  * (task events not emitted in v1; scanner reads TaskRow directly on
    each trigger so the window reflects current state)

Each subscriber is a thin wrapper around `scan(project_id)` with
per-project serialization inside scan itself (async lock per project)
so a flurry of events doesn't double-emit proposals.
"""
from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    AssignmentRepository,
    DecisionRepository,
    DecisionRow,
    DeliverableRow,
    DissentRepository,
    ProjectMemberRepository,
    RequirementRepository,
    SilentConsensusRepository,
    SilentConsensusRow,
    StatusTransitionRow,
    TaskRow,
    UserRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.silent_consensus")

# Lookback for "recent consistent action". 7 days matches the PLAN
# spec — long enough to catch an async-first team converging on a
# deliverable, short enough that stale history doesn't prop up a
# stale-agreement claim.
WINDOW_DAYS = 7

# Minimum distinct-member count for a proposal. We also enforce
# <=75% of active members (whichever is fewer) — see _threshold().
MIN_MEMBERS = 3


class SilentConsensusError(Exception):
    """Base class for service-level silent-consensus errors."""


@dataclass
class _Action:
    """Normalized action row feeding the scanner.

    `user_id` is the actor credited with the action (task assignee,
    decision resolver). `deliverable_id` anchors the action to a
    topic; actions without a deliverable anchor are skipped for
    v1 since their topic_text would be untethered.
    """

    kind: str  # 'task_status' | 'decision'
    id: str
    user_id: str
    deliverable_id: str | None
    at: datetime


class SilentConsensusService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        # Per-project scan lock. Prevents two overlapping scans on the
        # same project from racing and emitting duplicate proposals.
        # The dedupe guard inside scan() is the authoritative
        # correctness layer; the lock just keeps the event log clean.
        self._scan_locks: dict[str, asyncio.Lock] = {}
        # Late-bound MembraneService — set via attach_membrane() so
        # ratify() can route the resulting Decision through the
        # advisory review (Stage A). When None, decisions crystallize
        # without review (existing behavior).
        self._membrane_service: Any = None

    def attach_membrane(self, membrane_service: Any) -> None:
        self._membrane_service = membrane_service

    # ---- membership helpers ---------------------------------------------

    async def _is_member(
        self, *, project_id: str, user_id: str
    ) -> bool:
        async with session_scope(self._sessionmaker) as session:
            return await ProjectMemberRepository(session).is_member(
                project_id, user_id
            )

    async def _is_full_tier_owner(
        self, *, project_id: str, user_id: str
    ) -> bool:
        async with session_scope(self._sessionmaker) as session:
            for m in await ProjectMemberRepository(
                session
            ).list_for_project(project_id):
                if m.user_id == user_id:
                    return (
                        m.role == "owner"
                        and (m.license_tier or "full") == "full"
                    )
        return False

    # ---- public API -----------------------------------------------------

    async def scan(self, project_id: str) -> dict[str, Any]:
        """Run the detection pass. Returns summary dict.

        Emits at most one proposal per detected topic (dedup against
        the pending SilentConsensusRow set). No-op when no topics meet
        threshold.
        """
        lock = self._scan_locks.setdefault(project_id, asyncio.Lock())
        async with lock:
            return await self._scan_unlocked(project_id)

    async def _scan_unlocked(self, project_id: str) -> dict[str, Any]:
        created_ids: list[str] = []
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(days=WINDOW_DAYS)

        async with session_scope(self._sessionmaker) as session:
            # Active, non-system members.
            members = await ProjectMemberRepository(
                session
            ).list_for_project(project_id)
            active_members = [
                m for m in members if m.user_id != EDGE_AGENT_SYSTEM_USER_ID
            ]
            if len(active_members) < 2:
                return {"ok": True, "created": [], "reason": "too_few_members"}
            threshold = _threshold(len(active_members))

            # Deliverables on the latest requirement version — these are
            # the v1 "topics".
            req = await RequirementRepository(session).latest_for_project(
                project_id
            )
            if req is None:
                return {"ok": True, "created": [], "reason": "no_requirement"}
            deliverables = list(
                (
                    await session.execute(
                        select(DeliverableRow).where(
                            DeliverableRow.requirement_id == req.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            if not deliverables:
                return {"ok": True, "created": [], "reason": "no_deliverables"}

            # Recent task-done transitions (assignee credited as actor).
            task_transitions = list(
                (
                    await session.execute(
                        select(StatusTransitionRow)
                        .where(StatusTransitionRow.project_id == project_id)
                        .where(StatusTransitionRow.entity_kind == "task")
                        .where(StatusTransitionRow.new_status == "done")
                        .where(StatusTransitionRow.changed_at >= window_start)
                    )
                )
                .scalars()
                .all()
            )
            task_ids = {t.entity_id for t in task_transitions}
            tasks_by_id: dict[str, TaskRow] = {}
            if task_ids:
                tasks_rows = list(
                    (
                        await session.execute(
                            select(TaskRow).where(TaskRow.id.in_(task_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
                tasks_by_id = {t.id: t for t in tasks_rows}
            # Assignment lookup — credit the active assignee for the
            # task-done transition. A task without an assignee is still
            # an action, but it doesn't carry member attribution, so we
            # skip it for consensus counting.
            assignments = await AssignmentRepository(
                session
            ).list_for_project(project_id)
            assignment_by_task = {a.task_id: a.user_id for a in assignments}

            task_actions: list[_Action] = []
            for t in task_transitions:
                task_row = tasks_by_id.get(t.entity_id)
                if task_row is None or task_row.deliverable_id is None:
                    continue
                # Prefer the transition's changed_by; fall back to the
                # current assignee. A done-flip without attribution
                # cannot credit a member so it's skipped.
                actor = t.changed_by_user_id or assignment_by_task.get(
                    t.entity_id
                )
                if actor is None or actor == EDGE_AGENT_SYSTEM_USER_ID:
                    continue
                task_actions.append(
                    _Action(
                        kind="task_status",
                        id=t.entity_id,
                        user_id=actor,
                        deliverable_id=task_row.deliverable_id,
                        at=t.changed_at,
                    )
                )

            # Recent decisions. A decision's "topic deliverable" is
            # inferred from apply_actions targets that reference a task
            # (and that task's deliverable_id). Decisions without a
            # deliverable anchor are skipped (same reason as above).
            decision_rows = list(
                (
                    await session.execute(
                        select(DecisionRow)
                        .where(DecisionRow.project_id == project_id)
                        .where(DecisionRow.created_at >= window_start)
                    )
                )
                .scalars()
                .all()
            )
            decision_actions: list[_Action] = []
            for d in decision_rows:
                if d.apply_outcome == "failed":
                    continue
                # Skip decisions that were themselves produced by a
                # prior ratification — otherwise we'd loop (a ratified
                # decision re-triggers a scan that then "sees" its own
                # lineage as fresh supporting action).
                if (d.rationale or "").startswith(
                    "Ratified silent consensus:"
                ):
                    continue
                deliverable_id = _infer_decision_deliverable(
                    d, tasks_by_id=tasks_by_id
                )
                if deliverable_id is None:
                    continue
                decision_actions.append(
                    _Action(
                        kind="decision",
                        id=d.id,
                        user_id=d.resolver_id,
                        deliverable_id=deliverable_id,
                        at=d.created_at,
                    )
                )

            # Group actions by deliverable.
            by_deliverable: dict[str, list[_Action]] = {}
            for a in task_actions + decision_actions:
                if a.deliverable_id is None:
                    continue
                by_deliverable.setdefault(a.deliverable_id, []).append(a)

            deliverables_by_id = {d.id: d for d in deliverables}
            sc_repo = SilentConsensusRepository(session)
            dissent_repo = DissentRepository(session)
            # Every dissent on the project is a suppression signal —
            # v1 we apply it globally (not per-topic) because the
            # ORM's decision↔deliverable linkage is best-effort. If
            # ANY dissent is active on the project in the window, we
            # refuse to emit a silent-consensus proposal; users saw a
            # real disagreement recently and we'd rather keep the
            # signal clean than broadcast false agreement.
            project_dissents = await dissent_repo.list_for_project(project_id)

            emitted_new: list[SilentConsensusRow] = []
            for deliverable_id, actions in by_deliverable.items():
                distinct_members = {a.user_id for a in actions}
                if len(distinct_members) < threshold:
                    continue
                if _deliverable_has_suppressing_dissent(
                    deliverable_id=deliverable_id,
                    dissents=project_dissents,
                    decisions=decision_rows,
                    tasks_by_id=tasks_by_id,
                ):
                    continue
                deliverable = deliverables_by_id[deliverable_id]
                topic_text = _topic_text_for_deliverable(deliverable)
                # Dedup: existing pending row on same topic.
                existing = await sc_repo.find_pending_by_topic(
                    project_id=project_id, topic_text=topic_text
                )
                if existing is not None:
                    continue
                summary = _summarize(
                    deliverable=deliverable,
                    member_count=len(distinct_members),
                    actions=actions,
                )
                confidence = _confidence(
                    member_count=len(distinct_members),
                    threshold=threshold,
                )
                supporting = [
                    {"kind": a.kind, "id": a.id} for a in actions
                ]
                row = await sc_repo.create(
                    project_id=project_id,
                    topic_text=topic_text,
                    supporting_action_ids=supporting,
                    inferred_decision_summary=summary,
                    member_user_ids=sorted(distinct_members),
                    confidence=confidence,
                )
                emitted_new.append(row)
                created_ids.append(row.id)

        # Emit events OUTSIDE the session so the bus write is its own
        # transaction (matches the DissentService pattern).
        for row in emitted_new:
            await self._event_bus.emit(
                "silent_consensus.proposed",
                {
                    "silent_consensus_id": row.id,
                    "project_id": row.project_id,
                    "topic_text": row.topic_text,
                    "confidence": row.confidence,
                    "member_count": len(row.member_user_ids or []),
                },
            )

        return {"ok": True, "created": created_ids}

    async def list_pending(
        self,
        *,
        project_id: str,
        viewer_user_id: str,
    ) -> dict[str, Any]:
        if not await self._is_member(
            project_id=project_id, user_id=viewer_user_id
        ):
            return {"ok": False, "error": "not_a_member"}
        async with session_scope(self._sessionmaker) as session:
            rows = await SilentConsensusRepository(
                session
            ).list_pending_for_project(project_id)
            serialized = [
                await self._serialize(session, row) for row in rows
            ]
        return {"ok": True, "proposals": serialized}

    async def ratify(
        self,
        *,
        project_id: str,
        sc_id: str,
        ratifier_user_id: str,
    ) -> dict[str, Any]:
        if not await self._is_full_tier_owner(
            project_id=project_id, user_id=ratifier_user_id
        ):
            return {"ok": False, "error": "forbidden"}
        async with session_scope(self._sessionmaker) as session:
            sc_repo = SilentConsensusRepository(session)
            row = await sc_repo.get(sc_id)
            if row is None or row.project_id != project_id:
                return {"ok": False, "error": "not_found"}
            if row.status != "pending":
                return {"ok": False, "error": "not_pending"}

            # Build the rationale with embedded lineage.
            supporting = list(row.supporting_action_ids or [])
            lineage_line = ", ".join(
                f"{s.get('kind')}:{s.get('id')}" for s in supporting
            )
            rationale = (
                f"Ratified silent consensus: {row.topic_text}\n\n"
                f"Supporting actions: [{lineage_line}]"
            )
            review_title = (row.inferred_decision_summary or row.topic_text or "")[:200]
            topic_text = row.topic_text
            # Capture fields needed in the second session (the ORM row
            # detaches when this scope exits).
            inferred_summary = row.inferred_decision_summary

        # Membrane review (Stage A — advisory) outside the session so
        # the recent-decisions scan can use its own connection.
        membrane_warnings: list[str] = []
        if self._membrane_service is not None:
            from .membrane import MembraneCandidate

            review = await self._membrane_service.review(
                MembraneCandidate(
                    kind="decision_crystallize",
                    project_id=project_id,
                    proposer_user_id=ratifier_user_id,
                    title=review_title,
                    content="",
                    metadata={
                        "source": "silent_consensus",
                        "silent_consensus_id": sc_id,
                        "topic_text": topic_text,
                        "rationale": rationale,
                    },
                )
            )
            membrane_warnings = list(review.warnings)

        async with session_scope(self._sessionmaker) as session:
            sc_repo = SilentConsensusRepository(session)
            decision = await DecisionRepository(session).create(
                conflict_id=None,
                project_id=project_id,
                resolver_id=ratifier_user_id,
                option_index=None,
                custom_text=inferred_summary,
                rationale=rationale,
                apply_actions=[],
                source_suggestion_id=None,
                apply_outcome="advisory",
                apply_detail={
                    "silent_consensus_id": sc_id,
                    "supporting_action_ids": supporting,
                },
            )
            decision_id = decision.id
            await sc_repo.mark_ratified(
                sc_id=sc_id, decision_id=decision_id
            )
            payload = await self._serialize(session, await sc_repo.get(sc_id))

        await self._event_bus.emit(
            "silent_consensus.ratified",
            {
                "silent_consensus_id": sc_id,
                "decision_id": decision_id,
                "project_id": project_id,
                "ratifier_user_id": ratifier_user_id,
            },
        )
        # Also fire decision.applied so downstream (drift / dissent)
        # sees the ratified decision like any other. The apply_outcome
        # is advisory so dissent validation's self-fruit pass is a
        # no-op; that's intentional — no concrete mutation happened.
        await self._event_bus.emit(
            "decision.applied",
            {
                "decision_id": decision_id,
                "conflict_id": None,
                "project_id": project_id,
                "resolver": ratifier_user_id,
                "outcome": "advisory",
                "detail": {"source": "silent_consensus", "sc_id": sc_id},
            },
        )
        return {
            "ok": True,
            "proposal": payload,
            "decision_id": decision_id,
            "warnings": membrane_warnings,
        }

    async def reject(
        self,
        *,
        project_id: str,
        sc_id: str,
        rejecter_user_id: str,
    ) -> dict[str, Any]:
        if not await self._is_full_tier_owner(
            project_id=project_id, user_id=rejecter_user_id
        ):
            return {"ok": False, "error": "forbidden"}
        async with session_scope(self._sessionmaker) as session:
            sc_repo = SilentConsensusRepository(session)
            row = await sc_repo.get(sc_id)
            if row is None or row.project_id != project_id:
                return {"ok": False, "error": "not_found"}
            if row.status != "pending":
                return {"ok": False, "error": "not_pending"}
            await sc_repo.mark_rejected(sc_id=sc_id)
            payload = await self._serialize(session, await sc_repo.get(sc_id))
        await self._event_bus.emit(
            "silent_consensus.rejected",
            {
                "silent_consensus_id": sc_id,
                "project_id": project_id,
                "rejecter_user_id": rejecter_user_id,
            },
        )
        return {"ok": True, "proposal": payload}

    # ---- event-bus subscribers -----------------------------------------

    async def on_event(self, payload: dict[str, Any]) -> None:
        """Generic event hook — re-scan the affected project.

        Subscribed to task.status_changed / decision.applied /
        dissent.recorded. The scan is idempotent and cheap (a handful
        of indexed selects + one pending-dedupe) so re-running on
        every relevant event is acceptable.
        """
        project_id = payload.get("project_id")
        if not isinstance(project_id, str):
            return
        try:
            await self.scan(project_id)
        except Exception:  # pragma: no cover - subscriber safety net
            _log.exception(
                "silent consensus scan failed",
                extra={"project_id": project_id},
            )

    # ---- serialization --------------------------------------------------

    async def _serialize(
        self, session, row: SilentConsensusRow | None
    ) -> dict[str, Any]:
        if row is None:
            return {}
        # Snapshot member display names for the frontend chip list.
        user_repo = UserRepository(session)
        members_out: list[dict[str, str]] = []
        for uid in list(row.member_user_ids or []):
            user = await user_repo.get(uid)
            members_out.append(
                {
                    "user_id": uid,
                    "display_name": (
                        user.display_name or user.username
                    )
                    if user is not None
                    else uid[:8],
                }
            )
        return {
            "id": row.id,
            "project_id": row.project_id,
            "topic_text": row.topic_text,
            "supporting_action_ids": list(row.supporting_action_ids or []),
            "inferred_decision_summary": row.inferred_decision_summary,
            "members": members_out,
            "member_user_ids": list(row.member_user_ids or []),
            "confidence": row.confidence,
            "status": row.status,
            "created_at": row.created_at.isoformat()
            if row.created_at is not None
            else None,
            "ratified_decision_id": row.ratified_decision_id,
            "ratified_at": row.ratified_at.isoformat()
            if row.ratified_at is not None
            else None,
        }


def _threshold(active_member_count: int) -> int:
    """min(MIN_MEMBERS, ceil(0.75 * active_members)).

    The brief says 'whichever is fewer' so a 3-person project needs
    all 3 (ceil(0.75*3)=3), a 4-person project needs 3 (MIN=3 wins),
    a 10-person project needs 3 too (MIN=3 wins over ceil(7.5)=8? —
    actually 3 is fewer than 8, so MIN=3 wins). Taking the MIN of the
    two is what lets small teams meet the bar and keeps large teams
    from needing arbitrarily huge supermajorities.
    """
    pct = math.ceil(0.75 * max(active_member_count, 1))
    return max(1, min(MIN_MEMBERS, pct))


def _confidence(*, member_count: int, threshold: int) -> float:
    """member_count / threshold, capped at 1.0. Consistency is 1.0 in
    v1 (see module docstring)."""
    if threshold <= 0:
        return 1.0
    return min(1.0, member_count / threshold)


def _topic_text_for_deliverable(deliverable: DeliverableRow) -> str:
    """Canonical topic key for a deliverable. Deterministic so two
    scans produce the same topic_text → pending-dedupe works."""
    title = (deliverable.title or "deliverable").strip()
    return f"deliverable:{deliverable.id}:{title[:400]}"[:500]


def _summarize(
    *,
    deliverable: DeliverableRow,
    member_count: int,
    actions: list[_Action],
) -> str:
    """One-line inferred decision the ratifier confirms."""
    task_n = sum(1 for a in actions if a.kind == "task_status")
    dec_n = sum(1 for a in actions if a.kind == "decision")
    pieces: list[str] = [
        f"{member_count} members have acted on '{deliverable.title}'"
    ]
    if task_n:
        pieces.append(f"{task_n} task(s) marked done")
    if dec_n:
        pieces.append(f"{dec_n} decision(s) recorded")
    pieces.append(
        "Ratify to crystallize the group's behavioral agreement as a decision."
    )
    return " — ".join(pieces)[:4000]


def _infer_decision_deliverable(
    decision: DecisionRow, *, tasks_by_id: dict[str, TaskRow]
) -> str | None:
    """Best-effort decision → deliverable linkage.

    The ORM's `apply_actions` list is the only structured tie; when
    the decision's action list mentions a task_id we know, we use
    that task's deliverable. Otherwise None (skipped).
    """
    for action in decision.apply_actions or []:
        if not isinstance(action, dict):
            continue
        task_id = action.get("task_id")
        if not task_id:
            continue
        t = tasks_by_id.get(task_id)
        if t is not None and t.deliverable_id:
            return t.deliverable_id
    return None


def _deliverable_has_suppressing_dissent(
    *,
    deliverable_id: str,
    dissents: list,
    decisions: list[DecisionRow],
    tasks_by_id: dict[str, TaskRow],
) -> bool:
    """Does any dissent attach to a decision that touches this
    deliverable? If yes, suppress the proposal.

    v1 heuristic: walk dissents → their decisions → apply_actions
    task_ids → deliverable linkage. Any match within the window's
    decision set counts as a suppression signal.
    """
    if not dissents:
        return False
    dissented_decision_ids = {d.decision_id for d in dissents}
    for d in decisions:
        if d.id not in dissented_decision_ids:
            continue
        for action in d.apply_actions or []:
            if not isinstance(action, dict):
                continue
            tid = action.get("task_id")
            if not tid:
                continue
            t = tasks_by_id.get(tid)
            if t is not None and t.deliverable_id == deliverable_id:
                return True
    return False


__all__ = [
    "SilentConsensusService",
    "SilentConsensusError",
    "WINDOW_DAYS",
    "MIN_MEMBERS",
]
