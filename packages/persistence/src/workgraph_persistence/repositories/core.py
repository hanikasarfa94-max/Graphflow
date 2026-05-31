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


class IntakeRepository:
    """Creates project+requirement+intake_event atomically, deduped by source key."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_existing(
        self, source: str, source_event_id: str
    ) -> IntakeEventRow | None:
        stmt = select(IntakeEventRow).where(
            IntakeEventRow.source == source,
            IntakeEventRow.source_event_id == source_event_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        source: str,
        source_event_id: str,
        title: str,
        raw_text: str,
        payload: dict,
    ) -> tuple[ProjectRow, RequirementRow, IntakeEventRow]:
        existing = await self.find_existing(source, source_event_id)
        if existing is not None:
            raise DuplicateIntakeError(source, source_event_id, existing.project_id)

        project = ProjectRow(id=_new_id(), title=title)
        requirement = RequirementRow(
            id=_new_id(), project_id=project.id, raw_text=raw_text, version=1
        )
        intake = IntakeEventRow(
            id=_new_id(),
            source=source,
            source_event_id=source_event_id,
            project_id=project.id,
            payload=payload,
        )
        self._session.add_all([project, requirement, intake])
        try:
            await self._session.flush()
        except IntegrityError as e:
            await self._session.rollback()
            # Race: another request wrote the same source_event_id between find + flush.
            fresh = await self.find_existing(source, source_event_id)
            if fresh is not None:
                raise DuplicateIntakeError(source, source_event_id, fresh.project_id) from e
            raise
        return project, requirement, intake



class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        username: str,
        password_hash: str,
        password_salt: str,
        display_name: str = "",
    ) -> UserRow:
        row = UserRow(
            id=_new_id(),
            username=username,
            password_hash=password_hash,
            password_salt=password_salt,
            display_name=display_name or username,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, user_id: str) -> UserRow | None:
        return (
            await self._session.execute(select(UserRow).where(UserRow.id == user_id))
        ).scalar_one_or_none()

    async def get_by_username(self, username: str) -> UserRow | None:
        return (
            await self._session.execute(
                select(UserRow).where(UserRow.username == username)
            )
        ).scalar_one_or_none()

    async def list_all(self, limit: int = 50) -> list[UserRow]:
        stmt = select(UserRow).order_by(UserRow.created_at).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_many(self, user_ids: list[str]) -> list[UserRow]:
        """Fetch multiple users in one query. Returns rows in arbitrary
        order; caller indexes by id. Empty / duplicate input lists are
        normalised. Used by projections that need participant lookup
        for a batch of distinct user_ids without N+1.
        """
        unique = list({uid for uid in user_ids if uid})
        if not unique:
            return []
        stmt = select(UserRow).where(UserRow.id.in_(unique))
        return list((await self._session.execute(stmt)).scalars().all())

    async def update_profile(
        self,
        user_id: str,
        *,
        declared_abilities: list[str] | None = None,
        role_hints: list[str] | None = None,
        signal_tally: dict[str, int] | None = None,
        display_language: str | None = None,
    ) -> UserRow | None:
        """Partial update of response-profile fields + display_language.

        None values mean "leave untouched" — the router translates an
        unset key into None. Keys present with empty lists clear that key.
        Per north-star §"Profile as first-class primitive", profile is a
        JSON dict so callers shape their own keys; we merge at the top level.
        """
        row = await self.get(user_id)
        if row is None:
            return None
        profile = dict(row.profile or {})
        if declared_abilities is not None:
            profile["declared_abilities"] = list(declared_abilities)
        if role_hints is not None:
            profile["role_hints"] = list(role_hints)
        if signal_tally is not None:
            profile["signal_tally"] = dict(signal_tally)
        row.profile = profile
        if display_language is not None:
            row.display_language = display_language
        await self._session.flush()
        return row



class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, token: str, user_id: str, expires_at: datetime
    ) -> SessionRow:
        row = SessionRow(token=token, user_id=user_id, expires_at=expires_at)
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, token: str) -> SessionRow | None:
        return (
            await self._session.execute(
                select(SessionRow).where(SessionRow.token == token)
            )
        ).scalar_one_or_none()

    async def delete(self, token: str) -> None:
        row = await self.get(token)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()



class ProjectMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self, *, project_id: str, user_id: str, role: str = "member"
    ) -> ProjectMemberRow:
        existing = (
            await self._session.execute(
                select(ProjectMemberRow).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        row = ProjectMemberRow(
            id=_new_id(), project_id=project_id, user_id=user_id, role=role
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            existing = (
                await self._session.execute(
                    select(ProjectMemberRow).where(
                        ProjectMemberRow.project_id == project_id,
                        ProjectMemberRow.user_id == user_id,
                    )
                )
            ).scalar_one()
            return existing
        return row

    async def list_for_project(self, project_id: str) -> list[ProjectMemberRow]:
        stmt = (
            select(ProjectMemberRow)
            .where(ProjectMemberRow.project_id == project_id)
            .order_by(ProjectMemberRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_user(self, user_id: str) -> list[ProjectMemberRow]:
        stmt = (
            select(ProjectMemberRow)
            .where(ProjectMemberRow.user_id == user_id)
            .order_by(ProjectMemberRow.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def is_member(self, project_id: str, user_id: str) -> bool:
        row = (
            await self._session.execute(
                select(ProjectMemberRow).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        return row is not None

    async def get_role(self, project_id: str, user_id: str) -> str | None:
        row = (
            await self._session.execute(
                select(ProjectMemberRow).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        return row.role if row is not None else None

    async def set_skill_tags(
        self,
        *,
        project_id: str,
        user_id: str,
        skill_tags: list[str],
    ) -> ProjectMemberRow | None:
        """Replace the member's skill tag list. Caller normalizes input
        (lowercase, dedup, drops empties); we only persist."""
        row = (
            await self._session.execute(
                select(ProjectMemberRow).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row.skill_tags = list(skill_tags)
        await self._session.flush()
        return row



class OrganizationRepository:
    """CRUD over OrganizationRow + slug lookups.

    v1 keeps the surface small — create, fetch by id/slug, list by
    owner. Deletion isn't wired because the service layer doesn't
    expose it yet (out of scope: workspace delete).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        name: str,
        slug: str,
        owner_user_id: str,
        description: str | None = None,
    ) -> OrganizationRow:
        row = OrganizationRow(
            id=_new_id(),
            name=name,
            slug=slug,
            owner_user_id=owner_user_id,
            description=description,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, org_id: str) -> OrganizationRow | None:
        return (
            await self._session.execute(
                select(OrganizationRow).where(OrganizationRow.id == org_id)
            )
        ).scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> OrganizationRow | None:
        return (
            await self._session.execute(
                select(OrganizationRow).where(OrganizationRow.slug == slug)
            )
        ).scalar_one_or_none()

    async def list_by_ids(self, ids: list[str]) -> list[OrganizationRow]:
        if not ids:
            return []
        stmt = select(OrganizationRow).where(OrganizationRow.id.in_(ids))
        return list((await self._session.execute(stmt)).scalars().all())



class OrganizationMemberRepository:
    """Membership + role management for workspaces.

    `add` is idempotent on (org_id, user_id) — repeated calls return the
    existing row (matching ProjectMemberRepository's semantics). Role
    mutation is `set_role`; removal is `remove`. `is_member` is a fast
    existence check for the router guard.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        organization_id: str,
        user_id: str,
        role: str,
        invited_by_user_id: str | None = None,
    ) -> OrganizationMemberRow:
        existing = await self.get_member(organization_id, user_id)
        if existing is not None:
            return existing
        row = OrganizationMemberRow(
            id=_new_id(),
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            invited_by_user_id=invited_by_user_id,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            fresh = await self.get_member(organization_id, user_id)
            assert fresh is not None
            return fresh
        return row

    async def get_member(
        self, organization_id: str, user_id: str
    ) -> OrganizationMemberRow | None:
        return (
            await self._session.execute(
                select(OrganizationMemberRow).where(
                    OrganizationMemberRow.organization_id == organization_id,
                    OrganizationMemberRow.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def is_member(self, organization_id: str, user_id: str) -> bool:
        return (await self.get_member(organization_id, user_id)) is not None

    async def is_lead(self, organization_id: str, user_id: str) -> bool:
        """N-Next leader-bypass (north-star Correction R, new_concepts.md
        §6.11): owner / admin of an organization can READ into any cell
        owned by that org without being a direct project member. Writes
        still require explicit cell membership — preserves the single-
        membrane invariant.
        """
        row = await self.get_member(organization_id, user_id)
        return row is not None and row.role in ("owner", "admin")

    async def list_for_organization(
        self, organization_id: str
    ) -> list[OrganizationMemberRow]:
        stmt = (
            select(OrganizationMemberRow)
            .where(OrganizationMemberRow.organization_id == organization_id)
            .order_by(OrganizationMemberRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_user(
        self, user_id: str
    ) -> list[OrganizationMemberRow]:
        stmt = (
            select(OrganizationMemberRow)
            .where(OrganizationMemberRow.user_id == user_id)
            .order_by(OrganizationMemberRow.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_by_role(
        self, organization_id: str, role: str
    ) -> int:
        stmt = select(OrganizationMemberRow.id).where(
            OrganizationMemberRow.organization_id == organization_id,
            OrganizationMemberRow.role == role,
        )
        return len(list((await self._session.execute(stmt)).scalars().all()))

    async def set_role(
        self, *, organization_id: str, user_id: str, new_role: str
    ) -> OrganizationMemberRow | None:
        row = await self.get_member(organization_id, user_id)
        if row is None:
            return None
        row.role = new_role
        await self._session.flush()
        return row

    async def remove(
        self, *, organization_id: str, user_id: str
    ) -> bool:
        row = await self.get_member(organization_id, user_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


class OnboardingStateRepository:
    """Phase 1.B — per (user, project) ambient onboarding state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, *, user_id: str, project_id: str
    ) -> OnboardingStateRow | None:
        stmt = select(OnboardingStateRow).where(
            OnboardingStateRow.user_id == user_id,
            OnboardingStateRow.project_id == project_id,
        )
        return (
            await self._session.execute(stmt)
        ).scalar_one_or_none()

    async def create(
        self, *, user_id: str, project_id: str
    ) -> OnboardingStateRow:
        """Create fresh state on first visit. Idempotent via the
        unique constraint — a second caller racing in sees the
        existing row rather than a duplicate."""
        row = OnboardingStateRow(
            id=str(uuid4()),
            user_id=user_id,
            project_id=project_id,
            last_checkpoint="not_started",
            dismissed=False,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            existing = await self.get(
                user_id=user_id, project_id=project_id
            )
            assert existing is not None
            return existing
        return row

    async def get_or_create(
        self, *, user_id: str, project_id: str
    ) -> tuple[OnboardingStateRow, bool]:
        """Return the row and a created=True|False flag.

        Callers that need the "did we just create this" signal (e.g.
        the GET walkthrough side effect) read the boolean rather
        than re-querying.
        """
        existing = await self.get(
            user_id=user_id, project_id=project_id
        )
        if existing is not None:
            return existing, False
        row = await self.create(
            user_id=user_id, project_id=project_id
        )
        return row, True

    async def set_checkpoint(
        self,
        *,
        user_id: str,
        project_id: str,
        checkpoint: str,
    ) -> OnboardingStateRow | None:
        row = await self.get(
            user_id=user_id, project_id=project_id
        )
        if row is None:
            return None
        row.last_checkpoint = checkpoint
        now = datetime.now(timezone.utc)
        if row.walkthrough_started_at is None and checkpoint != "not_started":
            row.walkthrough_started_at = now
        if checkpoint == "completed":
            row.walkthrough_completed_at = now
        await self._session.flush()
        return row

    async def dismiss(
        self, *, user_id: str, project_id: str
    ) -> OnboardingStateRow | None:
        row = await self.get(
            user_id=user_id, project_id=project_id
        )
        if row is None:
            return None
        row.dismissed = True
        await self._session.flush()
        return row

    async def replay(
        self, *, user_id: str, project_id: str
    ) -> OnboardingStateRow | None:
        """Reset the row so the overlay re-opens on the next visit.
        Clears dismissed + completed; drops the cached walkthrough so
        the narration is fresh against the latest graph state."""
        row = await self.get(
            user_id=user_id, project_id=project_id
        )
        if row is None:
            return None
        row.dismissed = False
        row.walkthrough_completed_at = None
        row.walkthrough_started_at = None
        row.last_checkpoint = "not_started"
        row.walkthrough_json = None
        row.walkthrough_generated_at = None
        await self._session.flush()
        return row

    async def cache_walkthrough(
        self,
        *,
        user_id: str,
        project_id: str,
        walkthrough: dict,
    ) -> OnboardingStateRow | None:
        row = await self.get(
            user_id=user_id, project_id=project_id
        )
        if row is None:
            return None
        row.walkthrough_json = walkthrough
        row.walkthrough_generated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row


# ---- Phase 2.A — membrane subscription repository -----------------------



class EventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self, *, name: str, trace_id: str | None, payload: dict
    ) -> EventRow:
        # Surface project_id onto the column so Phase 7' SSE can filter without
        # JSON queries. Keeps the payload dict unchanged for downstream readers.
        project_id = payload.get("project_id") if isinstance(payload, dict) else None
        row = EventRow(
            id=_new_id(),
            name=name,
            trace_id=trace_id,
            payload=payload,
            project_id=project_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_by_name(self, name: str) -> list[EventRow]:
        stmt = select(EventRow).where(EventRow.name == name).order_by(EventRow.created_at)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_trace(self, trace_id: str) -> list[EventRow]:
        stmt = (
            select(EventRow)
            .where(EventRow.trace_id == trace_id)
            .order_by(EventRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_project_since(
        self, project_id: str, since_id: str | None = None, limit: int = 100
    ) -> list[EventRow]:
        """Ordered by created_at. Cursor via `since_id` (exclusive)."""
        stmt = select(EventRow).where(EventRow.project_id == project_id)
        if since_id is not None:
            since = (
                await self._session.execute(
                    select(EventRow).where(EventRow.id == since_id)
                )
            ).scalar_one_or_none()
            if since is not None:
                stmt = stmt.where(EventRow.created_at > since.created_at)
        stmt = stmt.order_by(EventRow.created_at).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())



class AgentRunLogRepository:
    """Writes one row per LLM agent call — decision 2C2."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        agent: str,
        prompt_version: str,
        outcome: str,
        attempts: int,
        latency_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        cache_read_tokens: int,
        project_id: str | None = None,
        trace_id: str | None = None,
        error: str | None = None,
    ) -> AgentRunLogRow:
        row = AgentRunLogRow(
            id=_new_id(),
            agent=agent,
            prompt_version=prompt_version,
            project_id=project_id,
            trace_id=trace_id,
            outcome=outcome,
            attempts=attempts,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            error=error,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_agent(self, agent: str) -> list[AgentRunLogRow]:
        stmt = (
            select(AgentRunLogRow)
            .where(AgentRunLogRow.agent == agent)
            .order_by(AgentRunLogRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_since(
        self,
        *,
        since: datetime | None = None,
        agent: str | None = None,
        limit: int = 500,
    ) -> list[AgentRunLogRow]:
        """Return rows created at or after `since`, optionally filtered by agent."""
        stmt = select(AgentRunLogRow)
        if since is not None:
            stmt = stmt.where(AgentRunLogRow.created_at >= since)
        if agent is not None:
            stmt = stmt.where(AgentRunLogRow.agent == agent)
        stmt = stmt.order_by(AgentRunLogRow.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_trace(self, trace_id: str) -> list[AgentRunLogRow]:
        stmt = (
            select(AgentRunLogRow)
            .where(AgentRunLogRow.trace_id == trace_id)
            .order_by(AgentRunLogRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())


# ---- Phase 7' auth + Phase 7'' collab repositories ----------------------


