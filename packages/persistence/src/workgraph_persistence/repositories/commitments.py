from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..orm import (
    AgentRunLogRow,
    AssignmentRow,
    ClarificationQuestionRow,
    CommentRow,
    CommitmentRow,
    ConflictRow,
    ConstraintRow,
    DecisionRow,
    DeliverableRow,
    DeliverySummaryRow,
    DissentRow,
    EventRow,
    GatedProposalRow,
    HandoffRow,
    GoalRow,
    IMSuggestionRow,
    IntakeEventRow,
    KbFolderRow,
    KbItemLicenseRow,
    KbItemRow,
    LicenseAuditRow,
    MeetingTranscriptRow,
    MembraneSubscriptionRow,
    MessageRow,
    MilestoneRow,
    NotificationRow,
    OnboardingStateRow,
    OrganizationMemberRow,
    OrganizationRow,
    ProjectMemberRow,
    ProjectRow,
    RequirementRow,
    RiskRow,
    RoutedSignalRow,
    ScrimmageRow,
    SessionRow,
    StatusTransitionRow,
    StreamMemberRow,
    StreamRow,
    TaskDependencyRow,
    TaskRow,
    TaskScoreRow,
    TaskStatusUpdateRow,
    UserRow,
    VoteRow,
)
from ..orm import SilentConsensusRow


from ._base import DuplicateIntakeError, InvalidProposalStateError, _new_id


class CommitmentRepository:
    """CRUD + listing for CommitmentRow (Sprint 2a).

    Invariants the service layer relies on:
      * `headline` is effectively immutable — callers mark a commitment
        `withdrawn` and create a new row instead of editing. This
        keeps the timeline of promises legible.
      * Only terminal-state transitions touch `resolved_at`. Non-
        terminal updates (re-anchoring scope_ref) do not — the create
        timestamp remains the canonical "when was this promised."
    """

    _TERMINAL_STATUSES = frozenset({"met", "missed", "withdrawn"})

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: str,
        created_by_user_id: str,
        headline: str,
        owner_user_id: str | None = None,
        target_date: datetime | None = None,
        metric: str | None = None,
        scope_ref_kind: str | None = None,
        scope_ref_id: str | None = None,
        source_message_id: str | None = None,
        sla_window_seconds: int | None = None,
    ) -> CommitmentRow:
        row = CommitmentRow(
            id=_new_id(),
            project_id=project_id,
            created_by_user_id=created_by_user_id,
            owner_user_id=owner_user_id or created_by_user_id,
            headline=headline,
            target_date=target_date,
            metric=metric,
            scope_ref_kind=scope_ref_kind,
            scope_ref_id=scope_ref_id,
            source_message_id=source_message_id,
            sla_window_seconds=sla_window_seconds,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def mark_escalated(
        self,
        commitment_id: str,
        *,
        at: datetime | None = None,
    ) -> CommitmentRow | None:
        """Stamp sla_last_escalated_at. Called by the SlaService after
        a ladder fan-out fires so subsequent event-triggered sweeps
        don't re-page the owner within the throttle window."""
        row = await self.get(commitment_id)
        if row is None:
            return None
        row.sla_last_escalated_at = at or datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def list_open_for_project(
        self, project_id: str, *, limit: int = 200
    ) -> list[CommitmentRow]:
        """Scoped helper for SlaService sweeps — skip resolved rows
        cheaply without building a general list-filter API."""
        stmt = (
            select(CommitmentRow)
            .where(
                CommitmentRow.project_id == project_id,
                CommitmentRow.status == "open",
            )
            .order_by(CommitmentRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get(self, commitment_id: str) -> CommitmentRow | None:
        return (
            await self._session.execute(
                select(CommitmentRow).where(CommitmentRow.id == commitment_id)
            )
        ).scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[CommitmentRow]:
        stmt = select(CommitmentRow).where(CommitmentRow.project_id == project_id)
        if status is not None:
            stmt = stmt.where(CommitmentRow.status == status)
        stmt = stmt.order_by(CommitmentRow.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def set_status(
        self,
        commitment_id: str,
        *,
        status: str,
    ) -> CommitmentRow | None:
        """Update the commitment's status. Setting a terminal state
        (met/missed/withdrawn) stamps `resolved_at`; reverting to open
        clears it. Unknown status strings raise ValueError at the
        service boundary — this layer stays permissive so seed/migration
        data doesn't get rejected."""
        row = await self.get(commitment_id)
        if row is None:
            return None
        row.status = status
        if status in self._TERMINAL_STATUSES:
            row.resolved_at = datetime.now(timezone.utc)
        else:
            row.resolved_at = None
        await self._session.flush()
        return row



class HandoffRepository:
    """Persist Stage 3 skill-succession records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: str,
        from_user_id: str,
        to_user_id: str,
        role_skills_transferred: list[str],
        profile_skill_routines: list[dict],
        brief_markdown: str,
        from_display_name: str,
        to_display_name: str,
    ) -> HandoffRow:
        row = HandoffRow(
            id=str(uuid4()),
            project_id=project_id,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            status="draft",
            role_skills_transferred=list(role_skills_transferred),
            profile_skill_routines=list(profile_skill_routines),
            brief_markdown=brief_markdown,
            from_display_name=from_display_name,
            to_display_name=to_display_name,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, handoff_id: str) -> HandoffRow | None:
        return (
            await self._session.execute(
                select(HandoffRow).where(HandoffRow.id == handoff_id)
            )
        ).scalar_one_or_none()

    async def list_for_project(
        self, project_id: str, *, limit: int = 100
    ) -> list[HandoffRow]:
        stmt = (
            select(HandoffRow)
            .where(HandoffRow.project_id == project_id)
            .order_by(HandoffRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_finalized_for_successor(
        self, *, project_id: str, to_user_id: str
    ) -> list[HandoffRow]:
        """Return the successor's inherited routines.

        A successor may inherit from multiple predecessors — each gives
        their own row; the service merges them per-skill."""
        stmt = (
            select(HandoffRow)
            .where(HandoffRow.project_id == project_id)
            .where(HandoffRow.to_user_id == to_user_id)
            .where(HandoffRow.status == "finalized")
            .order_by(HandoffRow.finalized_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def finalize(self, handoff_id: str) -> HandoffRow | None:
        row = await self.get(handoff_id)
        if row is None:
            return None
        row.status = "finalized"
        row.finalized_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row



class LicenseAuditRepository:
    """Phase 1.A — append-only audit log for cross-license replies."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        project_id: str,
        source_user_id: str,
        target_user_id: str,
        signal_id: str | None,
        referenced_node_ids: list[str],
        out_of_view_node_ids: list[str],
        outcome: str,
        effective_tier: str,
    ) -> LicenseAuditRow:
        row = LicenseAuditRow(
            id=_new_id(),
            project_id=project_id,
            source_user_id=source_user_id,
            target_user_id=target_user_id,
            signal_id=signal_id,
            referenced_node_ids=list(referenced_node_ids or []),
            out_of_view_node_ids=list(out_of_view_node_ids or []),
            outcome=outcome,
            effective_tier=effective_tier,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_project(
        self, project_id: str, *, limit: int = 200
    ) -> list[LicenseAuditRow]:
        stmt = (
            select(LicenseAuditRow)
            .where(LicenseAuditRow.project_id == project_id)
            .order_by(LicenseAuditRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())


