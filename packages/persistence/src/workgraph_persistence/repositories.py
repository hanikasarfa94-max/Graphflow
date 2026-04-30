from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .orm import (
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
from .orm import SilentConsensusRow


class DuplicateIntakeError(Exception):
    """Raised when (source, source_event_id) already exists."""

    def __init__(self, source: str, source_event_id: str, existing_project_id: str) -> None:
        super().__init__(
            f"intake already recorded: source={source} source_event_id={source_event_id}"
        )
        self.source = source
        self.source_event_id = source_event_id
        self.existing_project_id = existing_project_id


def _new_id() -> str:
    return str(uuid4())


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


class RequirementRepository:
    """Reads + appends versioned requirement rows (Phase 4, decision 1E).

    v1 is written by IntakeRepository at intake time. v2+ is written by
    ClarificationService after a clarify-reply merges answers back into the
    requirement. Old versions are never mutated — event history stays intact.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_for_project(self, project_id: str) -> RequirementRow | None:
        stmt = (
            select(RequirementRow)
            .where(RequirementRow.project_id == project_id)
            .order_by(RequirementRow.version.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get(self, requirement_id: str) -> RequirementRow | None:
        return (
            await self._session.execute(
                select(RequirementRow).where(RequirementRow.id == requirement_id)
            )
        ).scalar_one_or_none()

    async def append_version(
        self,
        *,
        project_id: str,
        raw_text: str,
        parsed_json: dict | None = None,
        parse_outcome: str | None = None,
        parsed_at: datetime | None = None,
    ) -> RequirementRow:
        """Write the next version row. Caller sets parsed_* after agent runs."""
        latest = await self.latest_for_project(project_id)
        next_version = (latest.version + 1) if latest else 1
        row = RequirementRow(
            id=_new_id(),
            project_id=project_id,
            version=next_version,
            raw_text=raw_text,
            parsed_json=parsed_json,
            parse_outcome=parse_outcome,
            parsed_at=parsed_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row


class ClarificationQuestionRepository:
    """Append questions generated by the ClarificationAgent; record answers.

    Questions are ordered within a requirement version via `position`. The
    (requirement_id, position) pair is unique, which also makes idempotent
    re-generation safe — callers can write in a single flush.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_batch(
        self, *, requirement_id: str, questions: list[str]
    ) -> list[ClarificationQuestionRow]:
        rows: list[ClarificationQuestionRow] = []
        for idx, q in enumerate(questions):
            row = ClarificationQuestionRow(
                id=_new_id(),
                requirement_id=requirement_id,
                position=idx,
                question=q,
            )
            rows.append(row)
            self._session.add(row)
        await self._session.flush()
        return rows

    async def list_for_requirement(
        self, requirement_id: str
    ) -> list[ClarificationQuestionRow]:
        stmt = (
            select(ClarificationQuestionRow)
            .where(ClarificationQuestionRow.requirement_id == requirement_id)
            .order_by(ClarificationQuestionRow.position)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get(self, question_id: str) -> ClarificationQuestionRow | None:
        stmt = select(ClarificationQuestionRow).where(
            ClarificationQuestionRow.id == question_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def record_answer(
        self, *, question_id: str, answer: str
    ) -> ClarificationQuestionRow | None:
        row = await self.get(question_id)
        if row is None:
            return None
        row.answer = answer
        row.answered_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def unanswered_count(self, requirement_id: str) -> int:
        rows = await self.list_for_requirement(requirement_id)
        return sum(1 for r in rows if r.answer is None)


class ProjectGraphRepository:
    """Reads + appends Goal/Deliverable/Constraint/Risk rows per requirement version.

    Per decision 1E, each requirement version owns its own set of graph entities.
    v2's entities are written alongside v2 (not by mutating v1's rows). The
    "latest graph" for stage derivation is the entities bound to the latest
    requirement version. Old versions stay as history.

    append_for_requirement is idempotent — a second call for the same
    requirement_id is a no-op that returns the existing rows. Callers force
    regeneration by promoting to a new requirement version, not by rewriting.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _list(
        self, model, requirement_id: str
    ) -> list:
        stmt = (
            select(model)
            .where(model.requirement_id == requirement_id)
            .order_by(model.sort_order)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_goals(self, requirement_id: str) -> list[GoalRow]:
        return await self._list(GoalRow, requirement_id)

    async def list_deliverables(self, requirement_id: str) -> list[DeliverableRow]:
        return await self._list(DeliverableRow, requirement_id)

    async def list_constraints(self, requirement_id: str) -> list[ConstraintRow]:
        return await self._list(ConstraintRow, requirement_id)

    async def list_risks(self, requirement_id: str) -> list[RiskRow]:
        return await self._list(RiskRow, requirement_id)

    async def list_all(
        self, requirement_id: str
    ) -> dict[str, list]:
        return {
            "goals": await self.list_goals(requirement_id),
            "deliverables": await self.list_deliverables(requirement_id),
            "constraints": await self.list_constraints(requirement_id),
            "risks": await self.list_risks(requirement_id),
        }

    async def has_entities(self, requirement_id: str) -> bool:
        """Cheap existence check used by stage derivation."""
        for model in (GoalRow, DeliverableRow, ConstraintRow, RiskRow):
            stmt = select(model.id).where(model.requirement_id == requirement_id).limit(1)
            if (await self._session.execute(stmt)).scalar_one_or_none() is not None:
                return True
        return False

    async def append_for_requirement(
        self,
        *,
        project_id: str,
        requirement_id: str,
        goals: list[dict],
        deliverables: list[dict],
        constraints: list[dict],
        risks: list[dict],
    ) -> dict[str, list]:
        """Write the graph for a requirement version. Idempotent per requirement.

        Each entity dict carries type-specific fields:
          goal: {title, description?, success_criteria?}
          deliverable: {title, kind?}
          constraint: {kind, content, severity?}
          risk: {title, content?, severity?}
        """
        if await self.has_entities(requirement_id):
            return await self.list_all(requirement_id)

        created: dict[str, list] = {
            "goals": [],
            "deliverables": [],
            "constraints": [],
            "risks": [],
        }
        for idx, g in enumerate(goals):
            row = GoalRow(
                id=_new_id(),
                project_id=project_id,
                requirement_id=requirement_id,
                sort_order=idx,
                title=g["title"],
                description=g.get("description", ""),
                success_criteria=g.get("success_criteria"),
            )
            self._session.add(row)
            created["goals"].append(row)
        for idx, d in enumerate(deliverables):
            row = DeliverableRow(
                id=_new_id(),
                project_id=project_id,
                requirement_id=requirement_id,
                sort_order=idx,
                title=d["title"],
                kind=d.get("kind", "feature"),
            )
            self._session.add(row)
            created["deliverables"].append(row)
        for idx, c in enumerate(constraints):
            row = ConstraintRow(
                id=_new_id(),
                project_id=project_id,
                requirement_id=requirement_id,
                sort_order=idx,
                kind=c["kind"],
                content=c["content"],
                severity=c.get("severity", "medium"),
            )
            self._session.add(row)
            created["constraints"].append(row)
        for idx, r in enumerate(risks):
            row = RiskRow(
                id=_new_id(),
                project_id=project_id,
                requirement_id=requirement_id,
                sort_order=idx,
                title=r["title"],
                content=r.get("content", ""),
                severity=r.get("severity", "medium"),
            )
            self._session.add(row)
            created["risks"].append(row)
        await self._session.flush()
        return created


class PlanRepository:
    """Append + list Tasks / Dependencies / Milestones for a requirement version.

    Idempotent per requirement_id — a second append call for a requirement
    that already has tasks is a no-op. Callers promote the requirement
    version to force a rebuild.

    DAG invariants (orphan-deliverable detection, cycle detection) live in
    PlanningService — this repository is pure storage. It does own the
    minimal helpers needed to feed detection (task_refs_for_requirement,
    edge_set_for_requirement).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_tasks(self, requirement_id: str) -> list[TaskRow]:
        stmt = (
            select(TaskRow)
            .where(TaskRow.requirement_id == requirement_id)
            .order_by(TaskRow.sort_order)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_dependencies(
        self, requirement_id: str
    ) -> list[TaskDependencyRow]:
        stmt = (
            select(TaskDependencyRow)
            .where(TaskDependencyRow.requirement_id == requirement_id)
            .order_by(TaskDependencyRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_milestones(self, requirement_id: str) -> list[MilestoneRow]:
        stmt = (
            select(MilestoneRow)
            .where(MilestoneRow.requirement_id == requirement_id)
            .order_by(MilestoneRow.sort_order)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_all(self, requirement_id: str) -> dict[str, list]:
        return {
            "tasks": await self.list_tasks(requirement_id),
            "dependencies": await self.list_dependencies(requirement_id),
            "milestones": await self.list_milestones(requirement_id),
        }

    async def has_plan(self, requirement_id: str) -> bool:
        stmt = (
            select(TaskRow.id)
            .where(TaskRow.requirement_id == requirement_id)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def get_task(self, task_id: str) -> TaskRow | None:
        return (
            await self._session.execute(
                select(TaskRow).where(TaskRow.id == task_id)
            )
        ).scalar_one_or_none()

    async def list_personal_for_owner(
        self, *, project_id: str, owner_user_id: str, limit: int = 200
    ) -> list[TaskRow]:
        """Personal-scope tasks belonging to one user in one project.

        Used by the TasksPanel "My drafts" section so the owner can
        see and promote their own self-set tasks. Other members
        cannot see these.
        """
        stmt = (
            select(TaskRow)
            .where(TaskRow.project_id == project_id)
            .where(TaskRow.scope == "personal")
            .where(TaskRow.owner_user_id == owner_user_id)
            .order_by(TaskRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def create_personal_task(
        self,
        *,
        project_id: str,
        owner_user_id: str,
        title: str,
        description: str = "",
        source_message_id: str | None = None,
        estimate_hours: int | None = None,
        assignee_role: str = "unknown",
    ) -> TaskRow:
        """Self-set personal task. requirement_id stays NULL until
        promoted; sort_order is timestamp-based (ms since epoch
        modulo a day's worth) so it stays roughly chronological
        without coordinating with the plan's sort_order space.

        `estimate_hours` and `assignee_role` are optional at create
        time. Passing them lets the membrane's task_promote review
        run a meaningful estimate-overflow check at promote time;
        omitting them keeps the legacy behavior (NULL estimate, role
        defaults to 'unknown' so the missing_owner advisory doesn't
        fire on the candidate itself).
        """
        sort_seed = int(datetime.now(timezone.utc).timestamp() * 1000) % (
            24 * 60 * 60 * 1000
        )
        row = TaskRow(
            id=_new_id(),
            project_id=project_id,
            requirement_id=None,
            sort_order=sort_seed,
            deliverable_id=None,
            title=title,
            description=description or "",
            assignee_role=assignee_role or "unknown",
            estimate_hours=estimate_hours,
            acceptance_criteria=None,
            scope="personal",
            owner_user_id=owner_user_id,
            source_message_id=source_message_id,
            status="open",
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def promote_personal_to_plan(
        self,
        *,
        task_id: str,
        requirement_id: str,
        sort_order: int,
    ) -> TaskRow | None:
        """Personal → plan. Caller (PlanningService / TaskService)
        decides the sort_order to avoid collisions with the existing
        plan layout. Returns None if task wasn't personal.
        """
        row = await self.get_task(task_id)
        if row is None or row.scope != "personal":
            return None
        row.scope = "plan"
        row.requirement_id = requirement_id
        row.sort_order = sort_order
        await self._session.flush()
        return row

    async def append_plan(
        self,
        *,
        project_id: str,
        requirement_id: str,
        tasks: list[dict],
        dependencies: list[dict],
        milestones: list[dict],
    ) -> dict[str, list]:
        """Persist a validated plan. Idempotent per requirement.

        Caller responsibilities (PlanningService enforces):
          - task dicts carry a local `ref` for dependency resolution; this
            repository maps `ref` → generated id internally.
          - dependency dicts use `from_ref`/`to_ref`; cycle detection already
            ran.
          - every task.deliverable_ref is null or a valid deliverable id for
            this requirement (orphan check already ran).
        """
        if await self.has_plan(requirement_id):
            return await self.list_all(requirement_id)

        ref_to_id: dict[str, str] = {}
        task_rows: list[TaskRow] = []
        for idx, t in enumerate(tasks):
            row_id = _new_id()
            ref_to_id[t["ref"]] = row_id
            row = TaskRow(
                id=row_id,
                project_id=project_id,
                requirement_id=requirement_id,
                sort_order=idx,
                deliverable_id=t.get("deliverable_id"),
                title=t["title"],
                description=t.get("description", ""),
                assignee_role=t.get("assignee_role", "unknown"),
                estimate_hours=t.get("estimate_hours"),
                acceptance_criteria=t.get("acceptance_criteria"),
            )
            self._session.add(row)
            task_rows.append(row)

        dep_rows: list[TaskDependencyRow] = []
        for d in dependencies:
            from_id = ref_to_id[d["from_ref"]]
            to_id = ref_to_id[d["to_ref"]]
            row = TaskDependencyRow(
                id=_new_id(),
                requirement_id=requirement_id,
                from_task_id=from_id,
                to_task_id=to_id,
            )
            self._session.add(row)
            dep_rows.append(row)

        milestone_rows: list[MilestoneRow] = []
        for idx, m in enumerate(milestones):
            related_ids = [ref_to_id[r] for r in m.get("related_task_refs", []) if r in ref_to_id]
            row = MilestoneRow(
                id=_new_id(),
                project_id=project_id,
                requirement_id=requirement_id,
                sort_order=idx,
                title=m["title"],
                target_date=m.get("target_date"),
                related_task_ids=related_ids or None,
            )
            self._session.add(row)
            milestone_rows.append(row)

        await self._session.flush()
        return {
            "tasks": task_rows,
            "dependencies": dep_rows,
            "milestones": milestone_rows,
        }


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


class AssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def set_assignment(
        self, *, project_id: str, task_id: str, user_id: str | None
    ) -> AssignmentRow | None:
        """Replace any active assignment for task_id. `user_id=None` unassigns."""
        stmt = select(AssignmentRow).where(
            AssignmentRow.task_id == task_id, AssignmentRow.active == True  # noqa: E712
        )
        active = list((await self._session.execute(stmt)).scalars().all())
        now = datetime.now(timezone.utc)
        for row in active:
            row.active = False
            row.resolved_at = now

        if user_id is None:
            await self._session.flush()
            return None

        row = AssignmentRow(
            id=_new_id(),
            project_id=project_id,
            task_id=task_id,
            user_id=user_id,
            active=True,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def active_for_task(self, task_id: str) -> AssignmentRow | None:
        stmt = select(AssignmentRow).where(
            AssignmentRow.task_id == task_id, AssignmentRow.active == True  # noqa: E712
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_project(self, project_id: str) -> list[AssignmentRow]:
        stmt = (
            select(AssignmentRow)
            .where(
                AssignmentRow.project_id == project_id,
                AssignmentRow.active == True,  # noqa: E712
            )
            .order_by(AssignmentRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())


class CommentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        project_id: str,
        author_id: str,
        target_kind: str,
        target_id: str,
        body: str,
        parent_comment_id: str | None = None,
    ) -> CommentRow:
        row = CommentRow(
            id=_new_id(),
            project_id=project_id,
            author_id=author_id,
            target_kind=target_kind,
            target_id=target_id,
            body=body,
            parent_comment_id=parent_comment_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_target(
        self, target_kind: str, target_id: str
    ) -> list[CommentRow]:
        stmt = (
            select(CommentRow)
            .where(
                CommentRow.target_kind == target_kind,
                CommentRow.target_id == target_id,
            )
            .order_by(CommentRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_project(self, project_id: str) -> list[CommentRow]:
        stmt = (
            select(CommentRow)
            .where(CommentRow.project_id == project_id)
            .order_by(CommentRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, message_id: str) -> MessageRow | None:
        return (
            await self._session.execute(
                select(MessageRow).where(MessageRow.id == message_id)
            )
        ).scalar_one_or_none()

    async def append(
        self,
        *,
        project_id: str | None,
        author_id: str,
        body: str,
        stream_id: str | None = None,
        kind: str = "text",
        linked_id: str | None = None,
    ) -> MessageRow:
        row = MessageRow(
            id=_new_id(),
            project_id=project_id,
            author_id=author_id,
            body=body,
            stream_id=stream_id,
            kind=kind,
            linked_id=linked_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_recent(
        self, project_id: str, limit: int = 100
    ) -> list[MessageRow]:
        stmt = (
            select(MessageRow)
            .where(MessageRow.project_id == project_id)
            .order_by(MessageRow.created_at.desc())
            .limit(limit)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows

    async def list_for_stream(
        self, stream_id: str, limit: int = 100
    ) -> list[MessageRow]:
        stmt = (
            select(MessageRow)
            .where(MessageRow.stream_id == stream_id)
            .order_by(MessageRow.created_at.desc())
            .limit(limit)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        rows.reverse()
        return rows


class IMSuggestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        project_id: str,
        message_id: str,
        kind: str,
        confidence: float,
        targets: list | None,
        proposal: dict | None,
        reasoning: str,
        prompt_version: str | None,
        outcome: str,
        attempts: int,
        counter_of_id: str | None = None,
    ) -> IMSuggestionRow:
        row = IMSuggestionRow(
            id=_new_id(),
            project_id=project_id,
            message_id=message_id,
            kind=kind,
            confidence=confidence,
            targets=targets,
            proposal=proposal,
            reasoning=reasoning,
            prompt_version=prompt_version,
            outcome=outcome,
            attempts=attempts,
            counter_of_id=counter_of_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, suggestion_id: str) -> IMSuggestionRow | None:
        return (
            await self._session.execute(
                select(IMSuggestionRow).where(IMSuggestionRow.id == suggestion_id)
            )
        ).scalar_one_or_none()

    # Alias kept for plan-doc fidelity; callers use either name.
    async def get_by_id(self, suggestion_id: str) -> IMSuggestionRow | None:
        return await self.get(suggestion_id)

    async def get_for_message(self, message_id: str) -> IMSuggestionRow | None:
        return (
            await self._session.execute(
                select(IMSuggestionRow).where(
                    IMSuggestionRow.message_id == message_id
                )
            )
        ).scalar_one_or_none()

    async def list_for_project(
        self,
        *,
        project_id: str,
        stream_id: str | None = None,
        limit: int = 100,
    ) -> list[IMSuggestionRow]:
        """List suggestions for a project, optionally narrowed to a room.

        `stream_id` filter joins through the source MessageRow so a
        room-scoped workbench panel only sees suggestions whose
        originating message landed in that room (pickup #6 + the
        room-stream slice).

        Newest first so the workbench `Requests` panel surfaces fresh
        candidates at the top.
        """
        stmt = (
            select(IMSuggestionRow)
            .where(IMSuggestionRow.project_id == project_id)
            .order_by(IMSuggestionRow.created_at.desc())
            .limit(limit)
        )
        if stream_id is not None:
            stmt = stmt.join(
                MessageRow, IMSuggestionRow.message_id == MessageRow.id
            ).where(MessageRow.stream_id == stream_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def resolve(self, suggestion_id: str, status: str) -> IMSuggestionRow | None:
        row = await self.get(suggestion_id)
        if row is None:
            return None
        row.status = status
        row.resolved_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def mark_countered(self, suggestion_id: str) -> IMSuggestionRow | None:
        """Flip `status` to 'countered' + stamp resolved_at — signal-chain."""
        return await self.resolve(suggestion_id, "countered")

    async def mark_escalated(self, suggestion_id: str) -> IMSuggestionRow | None:
        """Flip `status` to 'escalated', set escalation_state='requested'."""
        row = await self.get(suggestion_id)
        if row is None:
            return None
        row.status = "escalated"
        row.escalation_state = "requested"
        row.resolved_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def set_decision_id(
        self, suggestion_id: str, decision_id: str
    ) -> IMSuggestionRow | None:
        """Link the suggestion to the DecisionRow that crystallized from it."""
        row = await self.get(suggestion_id)
        if row is None:
            return None
        row.decision_id = decision_id
        await self._session.flush()
        return row


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        user_id: str,
        project_id: str,
        kind: str,
        body: str,
        target_kind: str | None = None,
        target_id: str | None = None,
    ) -> NotificationRow:
        row = NotificationRow(
            id=_new_id(),
            user_id=user_id,
            project_id=project_id,
            kind=kind,
            body=body,
            target_kind=target_kind,
            target_id=target_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_user(
        self, user_id: str, *, unread_only: bool = False, limit: int = 50
    ) -> list[NotificationRow]:
        stmt = select(NotificationRow).where(NotificationRow.user_id == user_id)
        if unread_only:
            stmt = stmt.where(NotificationRow.read == False)  # noqa: E712
        stmt = stmt.order_by(NotificationRow.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def unread_count(self, user_id: str) -> int:
        stmt = select(NotificationRow.id).where(
            NotificationRow.user_id == user_id,
            NotificationRow.read == False,  # noqa: E712
        )
        return len(list((await self._session.execute(stmt)).scalars().all()))

    async def mark_read(self, notification_id: str, user_id: str) -> NotificationRow | None:
        row = (
            await self._session.execute(
                select(NotificationRow).where(
                    NotificationRow.id == notification_id,
                    NotificationRow.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row.read = True
        await self._session.flush()
        return row

    async def mark_all_read(self, user_id: str) -> int:
        rows = await self.list_for_user(user_id, unread_only=True, limit=500)
        for r in rows:
            r.read = True
        await self._session.flush()
        return len(rows)


class ConflictRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        project_id: str,
        requirement_id: str | None,
        rule: str,
        severity: str,
        fingerprint: str,
        targets: list,
        detail: dict,
        trace_id: str | None = None,
    ) -> tuple[ConflictRow, bool]:
        """Insert a new conflict or reopen an existing one by fingerprint.

        Returns (row, is_new). A dismissed/resolved conflict that matches on
        fingerprint is NOT reopened — the user's decision stands. Only `open`
        or `stale` rows are refreshed.
        """
        existing = (
            await self._session.execute(
                select(ConflictRow).where(
                    ConflictRow.project_id == project_id,
                    ConflictRow.fingerprint == fingerprint,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status in ("open", "stale"):
                existing.status = "open"
                existing.severity = severity
                existing.targets = targets
                existing.detail = detail
                existing.requirement_id = requirement_id
                if trace_id:
                    existing.trace_id = trace_id
                await self._session.flush()
            return existing, False

        row = ConflictRow(
            id=_new_id(),
            project_id=project_id,
            requirement_id=requirement_id,
            rule=rule,
            severity=severity,
            fingerprint=fingerprint,
            targets=targets,
            detail=detail,
            trace_id=trace_id,
            status="open",
            explanation_outcome="pending",
        )
        self._session.add(row)
        await self._session.flush()
        return row, True

    async def attach_explanation(
        self,
        conflict_id: str,
        *,
        summary: str,
        options: list,
        prompt_version: str,
        outcome: str,
    ) -> ConflictRow | None:
        row = await self.get(conflict_id)
        if row is None:
            return None
        row.summary = summary
        row.options = options
        row.explanation_prompt_version = prompt_version
        row.explanation_outcome = outcome
        await self._session.flush()
        return row

    async def get(self, conflict_id: str) -> ConflictRow | None:
        return (
            await self._session.execute(
                select(ConflictRow).where(ConflictRow.id == conflict_id)
            )
        ).scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: str,
        *,
        include_closed: bool = False,
    ) -> list[ConflictRow]:
        stmt = select(ConflictRow).where(ConflictRow.project_id == project_id)
        if not include_closed:
            stmt = stmt.where(ConflictRow.status == "open")
        stmt = stmt.order_by(
            ConflictRow.severity.desc(),  # "high" > "medium" > "low" alphabetically? see service for ordering map
            ConflictRow.created_at.desc(),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_open_fingerprints(self, project_id: str) -> set[str]:
        stmt = select(ConflictRow.fingerprint).where(
            ConflictRow.project_id == project_id,
            ConflictRow.status == "open",
        )
        return set((await self._session.execute(stmt)).scalars().all())

    async def mark_stale(self, project_id: str, keep: set[str]) -> int:
        """Flip any open conflict whose fingerprint isn't in `keep` to stale.

        Called at the end of a detection pass so the UI can gray out conflicts
        that the current rules no longer fire on, without losing the history.
        """
        rows = list(
            (
                await self._session.execute(
                    select(ConflictRow).where(
                        ConflictRow.project_id == project_id,
                        ConflictRow.status == "open",
                    )
                )
            )
            .scalars()
            .all()
        )
        n = 0
        for r in rows:
            if r.fingerprint not in keep:
                r.status = "stale"
                n += 1
        if n:
            await self._session.flush()
        return n

    async def resolve(
        self,
        conflict_id: str,
        *,
        user_id: str,
        option_index: int | None,
    ) -> ConflictRow | None:
        row = await self.get(conflict_id)
        if row is None:
            return None
        row.status = "resolved"
        row.resolved_by = user_id
        row.resolved_option_index = option_index
        row.resolved_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def dismiss(
        self, conflict_id: str, *, user_id: str
    ) -> ConflictRow | None:
        row = await self.get(conflict_id)
        if row is None:
            return None
        row.status = "dismissed"
        row.resolved_by = user_id
        row.resolved_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row


class DecisionRepository:
    """Phase 9 — audit history for human decisions on conflicts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        conflict_id: str | None,
        project_id: str,
        resolver_id: str,
        option_index: int | None,
        custom_text: str | None,
        rationale: str,
        apply_actions: list,
        trace_id: str | None = None,
        source_suggestion_id: str | None = None,
        apply_outcome: str = "pending",
        apply_detail: dict | None = None,
        decision_class: str | None = None,
        gated_via_proposal_id: str | None = None,
        scope_stream_id: str | None = None,
    ) -> DecisionRow:
        """Persist a decision.

        `conflict_id` is now optional because IM-originated decisions crystallize
        from a suggestion directly (vision §6, signal-chain). In that case the
        caller passes `source_suggestion_id` instead. `apply_outcome`/`apply_detail`
        can be set at create-time for synchronous crystallization.

        `decision_class` + `gated_via_proposal_id` are Scene-2 gated-decision
        lineage (migration 0014). Non-gated decisions leave both NULL; the
        `GatedProposalService.approve` path sets both on approve. v0 does not
        enforce "gated-class decisions must have a proposal id" at this layer —
        that hardening is Option 2 (see GatedProposalService docstring).

        `scope_stream_id` (N-Next, migration 0027) is the smallest-relevant
        vote scope per new_concepts.md §6.11 + north-star Correction R.2.
        Caller passes the stream id whose membership defines the vote
        quorum (DM = 2 voters, 4-person room = 4, etc.). NULL leaves the
        decision cell-wide — current behavior for callers that haven't
        wired stream lineage yet (IM / silent-consensus / scrimmage / etc.
        will populate as N.4 lands).
        """
        row = DecisionRow(
            id=_new_id(),
            conflict_id=conflict_id,
            project_id=project_id,
            resolver_id=resolver_id,
            option_index=option_index,
            custom_text=custom_text,
            rationale=rationale,
            apply_actions=apply_actions,
            apply_outcome=apply_outcome,
            apply_detail=apply_detail or {},
            trace_id=trace_id,
            source_suggestion_id=source_suggestion_id,
            decision_class=decision_class,
            gated_via_proposal_id=gated_via_proposal_id,
            scope_stream_id=scope_stream_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def mark_applied(
        self,
        decision_id: str,
        *,
        outcome: str,
        detail: dict,
    ) -> DecisionRow | None:
        row = await self.get(decision_id)
        if row is None:
            return None
        row.apply_outcome = outcome
        row.apply_detail = detail
        row.applied_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def get(self, decision_id: str) -> DecisionRow | None:
        return (
            await self._session.execute(
                select(DecisionRow).where(DecisionRow.id == decision_id)
            )
        ).scalar_one_or_none()

    async def list_for_conflict(self, conflict_id: str) -> list[DecisionRow]:
        stmt = (
            select(DecisionRow)
            .where(DecisionRow.conflict_id == conflict_id)
            .order_by(DecisionRow.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_project(
        self, project_id: str, *, limit: int = 100
    ) -> list[DecisionRow]:
        stmt = (
            select(DecisionRow)
            .where(DecisionRow.project_id == project_id)
            .order_by(DecisionRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def latest_for_conflict(self, conflict_id: str) -> DecisionRow | None:
        stmt = (
            select(DecisionRow)
            .where(DecisionRow.conflict_id == conflict_id)
            .order_by(DecisionRow.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()


class GatedProposalRepository:
    """Migration 0014 — Scene 2 routing transport.

    State machine enforced at the repository layer (service layer
    double-checks but this is the safety net):
        pending → approved | denied | withdrawn     (terminal)
    Terminal → anything is rejected with InvalidProposalStateError.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: str,
        proposer_user_id: str,
        gate_keeper_user_id: str,
        decision_class: str,
        proposal_body: str,
        apply_actions: list,
        decision_text: str | None = None,
        trace_id: str | None = None,
    ) -> GatedProposalRow:
        row = GatedProposalRow(
            id=_new_id(),
            project_id=project_id,
            proposer_user_id=proposer_user_id,
            gate_keeper_user_id=gate_keeper_user_id,
            decision_class=decision_class,
            proposal_body=proposal_body,
            decision_text=decision_text,
            apply_actions=apply_actions,
            status="pending",
            trace_id=trace_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, proposal_id: str) -> GatedProposalRow | None:
        return (
            await self._session.execute(
                select(GatedProposalRow).where(
                    GatedProposalRow.id == proposal_id
                )
            )
        ).scalar_one_or_none()

    async def list_for_gate_keeper(
        self,
        gate_keeper_user_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[GatedProposalRow]:
        stmt = select(GatedProposalRow).where(
            GatedProposalRow.gate_keeper_user_id == gate_keeper_user_id
        )
        if status is not None:
            stmt = stmt.where(GatedProposalRow.status == status)
        stmt = stmt.order_by(GatedProposalRow.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_project(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[GatedProposalRow]:
        stmt = select(GatedProposalRow).where(
            GatedProposalRow.project_id == project_id
        )
        if status is not None:
            stmt = stmt.where(GatedProposalRow.status == status)
        stmt = stmt.order_by(GatedProposalRow.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def resolve(
        self,
        proposal_id: str,
        *,
        status: str,
        resolution_note: str | None = None,
    ) -> GatedProposalRow | None:
        """Transition {pending, in_vote} → {approved, denied, withdrawn}.

        Returns None if the row doesn't exist; raises
        InvalidProposalStateError if the row is already in a terminal
        state (approved / denied / withdrawn). `in_vote` was added in
        Phase S — accepting it here means cast_vote's threshold-driven
        resolution uses the same atomic transition as approve/deny.
        """
        if status not in {"approved", "denied", "withdrawn"}:
            raise ValueError(f"invalid resolve status: {status}")
        row = await self.get(proposal_id)
        if row is None:
            return None
        if row.status not in ("pending", "in_vote"):
            raise InvalidProposalStateError(
                f"proposal {proposal_id} is already {row.status}"
            )
        row.status = status
        row.resolution_note = resolution_note
        row.resolved_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row


class InvalidProposalStateError(Exception):
    """GatedProposalRepository.resolve called on a non-pending row."""


class VoteRepository:
    """Migration 0016 — votes as first-class graph nodes.

    Verdict lifecycle: verdicts are writes (never "pending"); the
    absence of a row means the voter hasn't weighed in. Re-voting
    UPDATEs the existing row rather than inserting a second row —
    the `(subject_kind, subject_id, voter_user_id)` unique index
    enforces this. `upsert` is the only write path.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        voter_user_id: str,
        verdict: str,
        rationale: str | None = None,
        trace_id: str | None = None,
    ) -> tuple[VoteRow, bool]:
        """Insert a new vote or update the existing one.

        Returns (row, created) — created=True means a new vote was
        inserted (first time voter weighs in on this subject);
        created=False means verdict/rationale was changed.
        """
        existing = (
            await self._session.execute(
                select(VoteRow)
                .where(VoteRow.subject_kind == subject_kind)
                .where(VoteRow.subject_id == subject_id)
                .where(VoteRow.voter_user_id == voter_user_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.verdict = verdict
            existing.rationale = rationale
            existing.updated_at = datetime.now(timezone.utc)
            if trace_id is not None:
                existing.trace_id = trace_id
            await self._session.flush()
            return existing, False

        row = VoteRow(
            id=_new_id(),
            subject_kind=subject_kind,
            subject_id=subject_id,
            voter_user_id=voter_user_id,
            verdict=verdict,
            rationale=rationale,
            trace_id=trace_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row, True

    async def get_for_voter(
        self,
        *,
        subject_kind: str,
        subject_id: str,
        voter_user_id: str,
    ) -> VoteRow | None:
        return (
            await self._session.execute(
                select(VoteRow)
                .where(VoteRow.subject_kind == subject_kind)
                .where(VoteRow.subject_id == subject_id)
                .where(VoteRow.voter_user_id == voter_user_id)
            )
        ).scalar_one_or_none()

    async def list_for_subject(
        self,
        *,
        subject_kind: str,
        subject_id: str,
    ) -> list[VoteRow]:
        result = await self._session.execute(
            select(VoteRow)
            .where(VoteRow.subject_kind == subject_kind)
            .where(VoteRow.subject_id == subject_id)
            .order_by(VoteRow.created_at.asc())
        )
        return list(result.scalars().all())

    async def list_for_voter(
        self, voter_user_id: str, *, limit: int = 100
    ) -> list[VoteRow]:
        result = await self._session.execute(
            select(VoteRow)
            .where(VoteRow.voter_user_id == voter_user_id)
            .order_by(VoteRow.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class DeliverySummaryRepository:
    """Phase 10 — append-only history of generated delivery summaries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: str,
        requirement_version: int,
        content_json: dict,
        parse_outcome: str,
        qa_report: dict,
        prompt_version: str | None,
        trace_id: str | None,
        created_by: str | None,
    ) -> DeliverySummaryRow:
        row = DeliverySummaryRow(
            id=_new_id(),
            project_id=project_id,
            requirement_version=requirement_version,
            content_json=content_json,
            parse_outcome=parse_outcome,
            qa_report=qa_report,
            prompt_version=prompt_version,
            trace_id=trace_id,
            created_by=created_by,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, delivery_id: str) -> DeliverySummaryRow | None:
        return (
            await self._session.execute(
                select(DeliverySummaryRow).where(DeliverySummaryRow.id == delivery_id)
            )
        ).scalar_one_or_none()

    async def latest_for_project(
        self, project_id: str
    ) -> DeliverySummaryRow | None:
        stmt = (
            select(DeliverySummaryRow)
            .where(DeliverySummaryRow.project_id == project_id)
            .order_by(DeliverySummaryRow.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_project(
        self, project_id: str, *, limit: int = 50
    ) -> list[DeliverySummaryRow]:
        stmt = (
            select(DeliverySummaryRow)
            .where(DeliverySummaryRow.project_id == project_id)
            .order_by(DeliverySummaryRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())


# ---- Task progress (Phase U) — status updates + leader scoring ----------


class TaskStatusUpdateRepository:
    """Append-only audit log. No update / delete — every status flip
    writes a fresh row. The TaskRow itself carries the current status;
    this gives the timeline."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        task_id: str,
        actor_user_id: str,
        old_status: str | None,
        new_status: str,
        note: str | None = None,
    ) -> TaskStatusUpdateRow:
        row = TaskStatusUpdateRow(
            id=_new_id(),
            task_id=task_id,
            actor_user_id=actor_user_id,
            old_status=old_status,
            new_status=new_status,
            note=note,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_task(
        self, task_id: str, *, limit: int = 50
    ) -> list[TaskStatusUpdateRow]:
        stmt = (
            select(TaskStatusUpdateRow)
            .where(TaskStatusUpdateRow.task_id == task_id)
            .order_by(TaskStatusUpdateRow.created_at.asc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())


class TaskScoreRepository:
    """One score per (task, assignee). Re-scoring updates in place."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        task_id: str,
        reviewer_user_id: str,
        assignee_user_id: str,
        quality: str,
        feedback: str | None = None,
    ) -> tuple[TaskScoreRow, bool]:
        """Returns (row, created). created=True if this is a new score."""
        existing = (
            await self._session.execute(
                select(TaskScoreRow)
                .where(TaskScoreRow.task_id == task_id)
                .where(TaskScoreRow.assignee_user_id == assignee_user_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.reviewer_user_id = reviewer_user_id
            existing.quality = quality
            existing.feedback = feedback
            existing.updated_at = datetime.now(timezone.utc)
            await self._session.flush()
            return existing, False
        row = TaskScoreRow(
            id=_new_id(),
            task_id=task_id,
            reviewer_user_id=reviewer_user_id,
            assignee_user_id=assignee_user_id,
            quality=quality,
            feedback=feedback,
        )
        self._session.add(row)
        await self._session.flush()
        return row, True

    async def get_for_task(self, task_id: str) -> TaskScoreRow | None:
        return (
            await self._session.execute(
                select(TaskScoreRow).where(TaskScoreRow.task_id == task_id)
            )
        ).scalar_one_or_none()

    async def list_for_assignee_in_window(
        self,
        *,
        assignee_user_id: str,
        project_id: str | None = None,
        since: datetime | None = None,
    ) -> list[TaskScoreRow]:
        """Used by perf_aggregation. If project_id is set, joins through
        TaskRow to filter."""
        stmt = select(TaskScoreRow).where(
            TaskScoreRow.assignee_user_id == assignee_user_id
        )
        if since is not None:
            stmt = stmt.where(TaskScoreRow.updated_at >= since)
        if project_id is not None:
            stmt = stmt.join(TaskRow, TaskScoreRow.task_id == TaskRow.id).where(
                TaskRow.project_id == project_id
            )
        return list((await self._session.execute(stmt)).scalars().all())


class KbItemRepository:
    """Phase V — first-class KB notes (separate from membrane signals)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: str,
        owner_user_id: str,
        title: str,
        content_md: str,
        scope: str = "personal",
        folder_id: str | None = None,
        source: str = "manual",
        status: str = "published",
    ) -> KbItemRow:
        row = KbItemRow(
            id=_new_id(),
            project_id=project_id,
            owner_user_id=owner_user_id,
            folder_id=folder_id,
            scope=scope,
            title=title,
            content_md=content_md,
            source=source,
            status=status,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, item_id: str) -> KbItemRow | None:
        return (
            await self._session.execute(
                select(KbItemRow).where(KbItemRow.id == item_id)
            )
        ).scalar_one_or_none()

    async def list_group_for_project(
        self,
        *,
        project_id: str,
        limit: int = 500,
    ) -> list[KbItemRow]:
        """All group-scope items in the project. Used by the membrane
        review pre-write check to scan for near-duplicate titles
        without leaking personal-scope items into the comparison."""
        stmt = (
            select(KbItemRow)
            .where(KbItemRow.project_id == project_id)
            .where(KbItemRow.scope == "group")
            .order_by(KbItemRow.updated_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_visible_for_user(
        self,
        *,
        project_id: str,
        viewer_user_id: str,
        limit: int = 200,
    ) -> list[KbItemRow]:
        """Personal items the viewer owns + every group item in the
        project. Order: most-recent updated first."""
        stmt = (
            select(KbItemRow)
            .where(KbItemRow.project_id == project_id)
            .where(
                # OR clause: scope=group OR (scope=personal AND owner=me).
                # SQLAlchemy via sa.or_ would be cleaner but we already
                # avoid the import in this module.
                (KbItemRow.scope == "group")
                | (
                    (KbItemRow.scope == "personal")
                    & (KbItemRow.owner_user_id == viewer_user_id)
                )
            )
            .order_by(KbItemRow.updated_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def update(
        self,
        *,
        item_id: str,
        title: str | None = None,
        content_md: str | None = None,
        status: str | None = None,
        folder_id: str | None = None,
    ) -> KbItemRow | None:
        row = await self.get(item_id)
        if row is None:
            return None
        if title is not None:
            row.title = title
        if content_md is not None:
            row.content_md = content_md
        if status is not None:
            row.status = status
        if folder_id is not None:
            row.folder_id = folder_id or None
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def set_scope(self, *, item_id: str, scope: str) -> KbItemRow | None:
        """Promotion / demotion. Service-layer enforces who can call."""
        row = await self.get(item_id)
        if row is None:
            return None
        row.scope = scope
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def delete(self, item_id: str) -> bool:
        row = await self.get(item_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


# ---- Phase B (v2) — stream repositories ---------------------------------


class StreamRepository:
    """Stream CRUD. Project streams are created once per project via boot
    backfill; DM streams are created on-demand with 1:1 dedup.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        type: str,
        project_id: str | None = None,
        owner_user_id: str | None = None,
        name: str | None = None,
    ) -> StreamRow:
        """Create a new stream row.

        `name` is optional and only meaningful for type='room' (display
        name shown in the room nav + header). Other stream types derive
        their display from the project / owner / DM partner.
        """
        row = StreamRow(
            id=_new_id(),
            type=type,
            project_id=project_id,
            owner_user_id=owner_user_id,
            name=name,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, stream_id: str) -> StreamRow | None:
        return (
            await self._session.execute(
                select(StreamRow).where(StreamRow.id == stream_id)
            )
        ).scalar_one_or_none()

    async def get_for_project(self, project_id: str) -> StreamRow | None:
        stmt = select(StreamRow).where(
            StreamRow.project_id == project_id,
            StreamRow.type == "project",
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_rooms_for_project(
        self, project_id: str
    ) -> list[StreamRow]:
        """N-Next: every 'room' stream nested in this cell.

        Per new_concepts.md §6.11, a cell hosts multiple team-room
        streams (sub-team / topical / ad-hoc). The main 'project'
        stream is excluded — `get_for_project` returns that one.
        Sorted by created_at so newest rooms surface last; UI can
        re-sort by activity if it wants to.
        """
        stmt = (
            select(StreamRow)
            .where(
                StreamRow.project_id == project_id,
                StreamRow.type == "room",
            )
            .order_by(StreamRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_personal_for_user_in_project(
        self, *, user_id: str, project_id: str
    ) -> StreamRow | None:
        """Phase L — the one personal stream a user has inside a project.

        Expected unique in (project_id, owner_user_id, type='personal'), but
        no DB-level UNIQUE constraint enforces it yet and race conditions
        during seeding have produced duplicates in the wild. Use `.first()`
        instead of `scalar_one_or_none()` so the API can't throw
        `MultipleResultsFound` on degraded data — prefer the oldest row for
        stability.
        """
        stmt = (
            select(StreamRow)
            .where(
                StreamRow.project_id == project_id,
                StreamRow.owner_user_id == user_id,
                StreamRow.type == "personal",
            )
            .order_by(StreamRow.created_at)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalars().first()

    async def find_dm_between(
        self, user_a: str, user_b: str
    ) -> StreamRow | None:
        """Find the canonical DM stream between two users.

        Dedup key is the set of member user_ids — any DM stream whose
        members == {user_a, user_b} counts. We scan via StreamMemberRow
        rather than storing a composite key because 1:1 DMs are the only
        case in v1 (group streams are v2).
        """
        a_streams = (
            await self._session.execute(
                select(StreamMemberRow.stream_id).where(
                    StreamMemberRow.user_id == user_a
                )
            )
        ).scalars().all()
        if not a_streams:
            return None
        stmt = select(StreamRow).where(
            StreamRow.id.in_(list(a_streams)),
            StreamRow.type == "dm",
        )
        candidates = list((await self._session.execute(stmt)).scalars().all())
        for stream in candidates:
            members = (
                await self._session.execute(
                    select(StreamMemberRow.user_id).where(
                        StreamMemberRow.stream_id == stream.id
                    )
                )
            ).scalars().all()
            if set(members) == {user_a, user_b}:
                return stream
        return None

    async def list_for_user(self, user_id: str) -> list[StreamRow]:
        """Streams the user belongs to, sorted by last_activity_at desc."""
        stmt = (
            select(StreamRow)
            .join(StreamMemberRow, StreamMemberRow.stream_id == StreamRow.id)
            .where(StreamMemberRow.user_id == user_id)
            .order_by(StreamRow.last_activity_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def touch_activity(self, stream_id: str) -> StreamRow | None:
        row = await self.get(stream_id)
        if row is None:
            return None
        row.last_activity_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row


class StreamMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        stream_id: str,
        user_id: str,
        role_in_stream: str = "member",
    ) -> StreamMemberRow:
        existing = (
            await self._session.execute(
                select(StreamMemberRow).where(
                    StreamMemberRow.stream_id == stream_id,
                    StreamMemberRow.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        row = StreamMemberRow(
            id=_new_id(),
            stream_id=stream_id,
            user_id=user_id,
            role_in_stream=role_in_stream,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            return (
                await self._session.execute(
                    select(StreamMemberRow).where(
                        StreamMemberRow.stream_id == stream_id,
                        StreamMemberRow.user_id == user_id,
                    )
                )
            ).scalar_one()
        return row

    async def list_for_stream(self, stream_id: str) -> list[StreamMemberRow]:
        stmt = (
            select(StreamMemberRow)
            .where(StreamMemberRow.stream_id == stream_id)
            .order_by(StreamMemberRow.joined_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def is_member(self, stream_id: str, user_id: str) -> bool:
        row = (
            await self._session.execute(
                select(StreamMemberRow).where(
                    StreamMemberRow.stream_id == stream_id,
                    StreamMemberRow.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        return row is not None

    async def get_member(
        self, stream_id: str, user_id: str
    ) -> StreamMemberRow | None:
        return (
            await self._session.execute(
                select(StreamMemberRow).where(
                    StreamMemberRow.stream_id == stream_id,
                    StreamMemberRow.user_id == user_id,
                )
            )
        ).scalar_one_or_none()

    async def mark_read(
        self, *, stream_id: str, user_id: str
    ) -> StreamMemberRow | None:
        row = await self.get_member(stream_id, user_id)
        if row is None:
            return None
        row.last_read_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def unread_count(
        self, *, stream_id: str, user_id: str
    ) -> int:
        """Count messages in the stream authored strictly after my
        last_read_at. If last_read_at is null (never read), every message
        counts; but we don't count my own messages as unread-to-me.
        """
        member = await self.get_member(stream_id, user_id)
        if member is None:
            return 0
        stmt = select(MessageRow.id).where(MessageRow.stream_id == stream_id)
        if member.last_read_at is not None:
            stmt = stmt.where(MessageRow.created_at > member.last_read_at)
        stmt = stmt.where(MessageRow.author_id != user_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return len(list(rows))


# ---- Phase L — routed signal repository ---------------------------------


class RoutedSignalRepository:
    """Phase L — persistence for cross-user sub-agent routed signals.

    North-star §"Routing primitive (data model)". A signal is created when
    RoutingService.dispatch runs; it stores the source's framing, the
    background snippets, the rich option set the target's edge-agent will
    render, and ultimately the target's reply. Status transitions:
      pending → replied → (accepted | declined | expired)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        source_user_id: str,
        target_user_id: str,
        source_stream_id: str,
        target_stream_id: str,
        framing: str,
        background: list,
        options: list,
        project_id: str | None = None,
        trace_id: str | None = None,
    ) -> RoutedSignalRow:
        row = RoutedSignalRow(
            id=_new_id(),
            trace_id=trace_id,
            source_user_id=source_user_id,
            target_user_id=target_user_id,
            source_stream_id=source_stream_id,
            target_stream_id=target_stream_id,
            project_id=project_id,
            framing=framing,
            background_json=list(background or []),
            options_json=list(options or []),
            status="pending",
            reply_json=None,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, signal_id: str) -> RoutedSignalRow | None:
        return (
            await self._session.execute(
                select(RoutedSignalRow).where(RoutedSignalRow.id == signal_id)
            )
        ).scalar_one_or_none()

    async def list_for_user(
        self,
        user_id: str,
        *,
        kind: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[RoutedSignalRow]:
        """`kind` in {'inbound', 'outbound'}. Optional `status` filter."""
        if kind == "inbound":
            stmt = select(RoutedSignalRow).where(
                RoutedSignalRow.target_user_id == user_id
            )
        elif kind == "outbound":
            stmt = select(RoutedSignalRow).where(
                RoutedSignalRow.source_user_id == user_id
            )
        else:
            raise ValueError(f"kind must be 'inbound' or 'outbound', got {kind!r}")
        if status is not None:
            stmt = stmt.where(RoutedSignalRow.status == status)
        stmt = stmt.order_by(RoutedSignalRow.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_dm(
        self, user_a_id: str, user_b_id: str, *, limit: int = 100
    ) -> list[RoutedSignalRow]:
        """Routed signals in either direction between two users."""
        stmt = (
            select(RoutedSignalRow)
            .where(
                (
                    (RoutedSignalRow.source_user_id == user_a_id)
                    & (RoutedSignalRow.target_user_id == user_b_id)
                )
                | (
                    (RoutedSignalRow.source_user_id == user_b_id)
                    & (RoutedSignalRow.target_user_id == user_a_id)
                )
            )
            .order_by(RoutedSignalRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def mark_replied(
        self,
        signal_id: str,
        *,
        option_id: str | None,
        custom_text: str | None,
    ) -> RoutedSignalRow | None:
        """Record target's reply + flip status to 'replied'. Idempotent: a
        second reply overwrites the first — v1 routing is not a multi-turn
        conversation, so latest-reply-wins is acceptable.
        """
        row = await self.get(signal_id)
        if row is None:
            return None
        now = datetime.now(timezone.utc)
        row.status = "replied"
        row.reply_json = {
            "option_id": option_id,
            "custom_text": custom_text,
            "responded_at": now.isoformat(),
        }
        row.responded_at = now
        await self._session.flush()
        return row

    async def mark_accepted(self, signal_id: str) -> RoutedSignalRow | None:
        """Source closes the loop on a signal that's already been replied
        to. Status transitions: replied → accepted. Idempotent: re-accept
        is a no-op so a refresh after the click never reopens the buttons.
        """
        row = await self.get(signal_id)
        if row is None:
            return None
        if row.status not in ("replied", "accepted"):
            return row
        row.status = "accepted"
        await self._session.flush()
        return row


# ---- Phase D — membrane signal repository -------------------------------


class KbIngestRepository:
    """Externally-ingested KB items (membrane source).

    Operates on `kb_items` rows with `source='ingest'`. The class
    encapsulates the dedup-by-source-identifier and review-lifecycle
    semantics that external ingests need (URLs, RSS, webhooks,
    git commits) — separate from the manual / upload / llm write paths
    that go through `KbItemRepository.create` directly.

    Renamed from `MembraneSignalRepository` after the fold completed
    (docs/membrane-reorg.md F1-F5, 2026-04-26). Pre-fold the class
    operated on a separate `membrane_signals` table; post-fold it
    operates on a discriminated subset of `kb_items`. The old name
    survives as a deprecated alias in `__init__.py`.

    Vision §5.12 (Membranes). Dedup key is (project_id, source_identifier).
    Re-ingesting the same URL / commit hash / forum post returns the
    existing row; the caller never double-classifies.

    Status transitions: pending-review → (approved | rejected | routed).
    `rejected` rows stay as audit history, never routed.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_source(
        self, *, project_id: str | None, source_identifier: str
    ) -> KbItemRow | None:
        stmt = (
            select(KbItemRow)
            .where(KbItemRow.source == "ingest")
            .where(KbItemRow.source_identifier == source_identifier)
        )
        # NULL-safe project scope match — project-scoped dedup only collides
        # with rows from the same project_id value (including null↔null).
        if project_id is None:
            stmt = stmt.where(KbItemRow.project_id.is_(None))
        else:
            stmt = stmt.where(KbItemRow.project_id == project_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        project_id: str | None,
        source_kind: str,
        source_identifier: str,
        raw_content: str,
        ingested_by_user_id: str | None = None,
        trace_id: str | None = None,
    ) -> KbItemRow:
        # Title fallback chain mirrors the F2 backfill exactly so old
        # backfilled rows and new ingest writes pick the same title.
        # Caps at 500 (KbItemRow.title column limit).
        title = (
            (raw_content or "")[:80]
            or (source_identifier or "")[:500]
            or "Untitled signal"
        )
        row = KbItemRow(
            id=_new_id(),
            project_id=project_id,
            owner_user_id=ingested_by_user_id,
            folder_id=None,
            scope="group",
            title=title,
            content_md="",
            source="ingest",
            source_kind=source_kind,
            source_identifier=source_identifier,
            raw_content=raw_content,
            classification_json={},
            status="pending-review",
            ingested_by_user_id=ingested_by_user_id,
            trace_id=trace_id,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            # Race: another request wrote the same (project_id, source_identifier)
            # between find + flush. Return the existing row instead of exploding.
            # NOTE: F1 didn't add a UNIQUE constraint on (project_id,
            # source_identifier) at the DB level (SQLite portability); the
            # find+create pattern + this rollback path is the dedup mechanism.
            # Concurrent writes can still produce duplicates briefly until the
            # next find_by_source coalesces them; acceptable for the ingest
            # cadence (cron polls + occasional user pastes).
            await self._session.rollback()
            fresh = await self.find_by_source(
                project_id=project_id, source_identifier=source_identifier
            )
            if fresh is not None:
                return fresh
            raise
        return row

    async def get(self, signal_id: str) -> KbItemRow | None:
        # No source='ingest' filter: callers may pass an id that was
        # written before the fold (back when membrane_signals was the
        # only store). Post-F2 backfill, every such id has a kb_items
        # mirror, so plain id lookup is correct. After F5 the legacy
        # table is gone and this is the only path.
        return (
            await self._session.execute(
                select(KbItemRow).where(KbItemRow.id == signal_id)
            )
        ).scalar_one_or_none()

    async def set_classification(
        self,
        signal_id: str,
        *,
        classification: dict,
        status: str,
    ) -> KbItemRow | None:
        row = await self.get(signal_id)
        if row is None:
            return None
        row.classification_json = dict(classification)
        row.status = status
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def mark_status(
        self,
        signal_id: str,
        *,
        status: str,
        approved_by_user_id: str | None = None,
    ) -> KbItemRow | None:
        row = await self.get(signal_id)
        if row is None:
            return None
        row.status = status
        if approved_by_user_id is not None:
            row.approved_by_user_id = approved_by_user_id
            row.approved_at = datetime.now(timezone.utc)
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def list_for_project(
        self,
        project_id: str,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[KbItemRow]:
        stmt = (
            select(KbItemRow)
            .where(KbItemRow.source == "ingest")
            .where(KbItemRow.project_id == project_id)
        )
        if status is not None:
            stmt = stmt.where(KbItemRow.status == status)
        stmt = stmt.order_by(KbItemRow.created_at.desc()).limit(limit)
        return list((await self._session.execute(stmt)).scalars().all())


# ---- Sprint 1b — status transition log (time-cursor replay) -------------


class StatusTransitionRepository:
    """Append-only log of graph-entity status mutations.

    Every status flip on a task / risk / deliverable / goal / milestone /
    constraint / decision writes a row here. `GET /projects/{id}/graph-at`
    replays the log to reconstruct the status of each entity at a past
    timestamp. Writes are cheap (one INSERT per mutation) and the replay
    query is `project_id + changed_at <= ts` — both indexed.

    `record` is a helper that services call after they flip a status. It
    accepts `old_status` explicitly rather than reading it back from the
    row because most service call sites already have the previous value in
    hand (they just read it before writing), and a separate read would
    double the query count on the hot path.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        project_id: str,
        entity_kind: str,
        entity_id: str,
        old_status: str | None,
        new_status: str,
        changed_by_user_id: str | None = None,
        trace_id: str | None = None,
        changed_at: datetime | None = None,
    ) -> StatusTransitionRow:
        row = StatusTransitionRow(
            id=_new_id(),
            project_id=project_id,
            entity_kind=entity_kind,
            entity_id=entity_id,
            old_status=old_status,
            new_status=new_status,
            changed_by_user_id=changed_by_user_id,
            trace_id=trace_id,
            changed_at=changed_at or datetime.now(timezone.utc),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_project_up_to(
        self, project_id: str, *, upto: datetime
    ) -> list[StatusTransitionRow]:
        """All transitions on or before `upto`, ordered oldest → newest.

        Ordering matters for replay: the LATEST transition wins per entity.
        A consumer iterates forwards and overwrites a running map so the
        final map carries the most recent status per entity.
        """
        stmt = (
            select(StatusTransitionRow)
            .where(
                StatusTransitionRow.project_id == project_id,
                StatusTransitionRow.changed_at <= upto,
            )
            .order_by(StatusTransitionRow.changed_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_project_since(
        self, project_id: str, *, since: datetime, limit: int = 500
    ) -> list[StatusTransitionRow]:
        """Recent transitions after `since`, oldest → newest, capped.

        Used by the web timeline strip to render event markers.
        """
        stmt = (
            select(StatusTransitionRow)
            .where(
                StatusTransitionRow.project_id == project_id,
                StatusTransitionRow.changed_at > since,
            )
            .order_by(StatusTransitionRow.changed_at)
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())


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


class ScrimmageRepository:
    """Phase 2.B — agent-vs-agent scrimmage transcripts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: str,
        source_user_id: str,
        target_user_id: str,
        question_text: str,
        routed_signal_id: str | None = None,
        trace_id: str | None = None,
    ) -> ScrimmageRow:
        row = ScrimmageRow(
            id=_new_id(),
            project_id=project_id,
            routed_signal_id=routed_signal_id,
            source_user_id=source_user_id,
            target_user_id=target_user_id,
            question_text=question_text,
            transcript_json=[],
            outcome="in_progress",
            proposal_json=None,
            trace_id=trace_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def finalize(
        self,
        scrimmage_id: str,
        *,
        transcript: list,
        outcome: str,
        proposal: dict | None,
    ) -> ScrimmageRow | None:
        row = await self.get(scrimmage_id)
        if row is None:
            return None
        row.transcript_json = list(transcript)
        row.outcome = outcome
        row.proposal_json = proposal
        row.completed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def get(self, scrimmage_id: str) -> ScrimmageRow | None:
        return (
            await self._session.execute(
                select(ScrimmageRow).where(ScrimmageRow.id == scrimmage_id)
            )
        ).scalar_one_or_none()

    async def list_for_project(
        self, project_id: str, *, limit: int = 50
    ) -> list[ScrimmageRow]:
        stmt = (
            select(ScrimmageRow)
            .where(ScrimmageRow.project_id == project_id)
            .order_by(ScrimmageRow.created_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())


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


class DissentRepository:
    """Phase 2.A — dissent rows + judgment-accuracy validation surface."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        decision_id: str,
        dissenter_user_id: str,
        stance_text: str,
    ) -> DissentRow:
        """Create or replace the dissenter's stance on this decision.

        The replace semantics (rather than append) match the PLAN-v3
        contract: one dissent per (decision, dissenter). A second
        POST overwrites the text AND clears the validation state so a
        fresh stance starts fresh — previous outcome evidence no
        longer applies to the new wording.
        """
        existing = await self.get_by_decision_and_user(
            decision_id=decision_id, dissenter_user_id=dissenter_user_id
        )
        if existing is not None:
            existing.stance_text = stance_text
            existing.validated_by_outcome = None
            existing.outcome_evidence_ids = []
            # created_at stays — the dissent's age is about when the
            # disagreement first surfaced, not when the wording last
            # shifted. UI sorts by created_at.
            await self._session.flush()
            return existing
        row = DissentRow(
            id=_new_id(),
            decision_id=decision_id,
            dissenter_user_id=dissenter_user_id,
            stance_text=stance_text,
            validated_by_outcome=None,
            outcome_evidence_ids=[],
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, dissent_id: str) -> DissentRow | None:
        return (
            await self._session.execute(
                select(DissentRow).where(DissentRow.id == dissent_id)
            )
        ).scalar_one_or_none()

    async def get_by_decision_and_user(
        self, *, decision_id: str, dissenter_user_id: str
    ) -> DissentRow | None:
        return (
            await self._session.execute(
                select(DissentRow)
                .where(DissentRow.decision_id == decision_id)
                .where(DissentRow.dissenter_user_id == dissenter_user_id)
            )
        ).scalar_one_or_none()

    async def list_for_decision(
        self, decision_id: str
    ) -> list[DissentRow]:
        stmt = (
            select(DissentRow)
            .where(DissentRow.decision_id == decision_id)
            .order_by(DissentRow.created_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_user_in_project(
        self, *, project_id: str, user_id: str
    ) -> list[DissentRow]:
        """Dissents the user recorded across this project.

        Joins through DecisionRow to filter by project_id — DissentRow
        itself has no project column to keep the schema aligned with
        the decision lineage (a dissent attaches to a decision, which
        already has a project).
        """
        stmt = (
            select(DissentRow)
            .join(DecisionRow, DecisionRow.id == DissentRow.decision_id)
            .where(DecisionRow.project_id == project_id)
            .where(DissentRow.dissenter_user_id == user_id)
            .order_by(DissentRow.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_for_project(
        self, project_id: str
    ) -> list[DissentRow]:
        stmt = (
            select(DissentRow)
            .join(DecisionRow, DecisionRow.id == DissentRow.decision_id)
            .where(DecisionRow.project_id == project_id)
            .order_by(DissentRow.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def set_outcome(
        self,
        *,
        dissent_id: str,
        outcome: str,
        evidence_id: str | None,
    ) -> DissentRow | None:
        row = await self.get(dissent_id)
        if row is None:
            return None
        row.validated_by_outcome = outcome
        if evidence_id:
            evidence = list(row.outcome_evidence_ids or [])
            if evidence_id not in evidence:
                evidence.append(evidence_id)
                row.outcome_evidence_ids = evidence
        await self._session.flush()
        return row


class SilentConsensusRepository:
    """Phase 1.A — silent-consensus proposal CRUD.

    A silent-consensus proposal is derived state: the scanner in
    services/silent_consensus.py emits a row when N members act
    consistently on a topic. Persisted as pending until a human
    ratifies (→ DecisionRow) or rejects.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: str,
        topic_text: str,
        supporting_action_ids: list[dict],
        inferred_decision_summary: str,
        member_user_ids: list[str],
        confidence: float,
    ) -> SilentConsensusRow:
        row = SilentConsensusRow(
            id=_new_id(),
            project_id=project_id,
            topic_text=topic_text,
            supporting_action_ids=list(supporting_action_ids),
            inferred_decision_summary=inferred_decision_summary,
            member_user_ids=list(member_user_ids),
            confidence=float(confidence),
            status="pending",
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, sc_id: str) -> SilentConsensusRow | None:
        return (
            await self._session.execute(
                select(SilentConsensusRow).where(SilentConsensusRow.id == sc_id)
            )
        ).scalar_one_or_none()

    async def list_pending_for_project(
        self, project_id: str
    ) -> list[SilentConsensusRow]:
        stmt = (
            select(SilentConsensusRow)
            .where(SilentConsensusRow.project_id == project_id)
            .where(SilentConsensusRow.status == "pending")
            .order_by(SilentConsensusRow.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_all_for_project(
        self, project_id: str
    ) -> list[SilentConsensusRow]:
        stmt = (
            select(SilentConsensusRow)
            .where(SilentConsensusRow.project_id == project_id)
            .order_by(SilentConsensusRow.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def find_pending_by_topic(
        self, *, project_id: str, topic_text: str
    ) -> SilentConsensusRow | None:
        """Used by the scanner dedupe guard: if a pending row already
        exists for the same topic we skip emitting a duplicate."""
        stmt = (
            select(SilentConsensusRow)
            .where(SilentConsensusRow.project_id == project_id)
            .where(SilentConsensusRow.topic_text == topic_text)
            .where(SilentConsensusRow.status == "pending")
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def mark_ratified(
        self,
        *,
        sc_id: str,
        decision_id: str,
    ) -> SilentConsensusRow | None:
        row = await self.get(sc_id)
        if row is None:
            return None
        row.status = "ratified"
        row.ratified_decision_id = decision_id
        row.ratified_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def mark_rejected(
        self, *, sc_id: str
    ) -> SilentConsensusRow | None:
        row = await self.get(sc_id)
        if row is None:
            return None
        row.status = "rejected"
        await self._session.flush()
        return row

    async def count_ratified_by_user_in_project(
        self, *, project_id: str, user_id: str
    ) -> tuple[int, list[str]]:
        """Count of silent-consensus rows ratified by this user and the
        up-to-10 most recent ratified decision ids. Used by perf
        aggregation to surface the "silent_consensus_ratified" column.

        Ratifier identity is stored indirectly: the ratified DecisionRow
        has resolver_id == ratifier. We join through decisions.
        """
        stmt = (
            select(SilentConsensusRow.id, SilentConsensusRow.ratified_decision_id)
            .join(
                DecisionRow,
                DecisionRow.id == SilentConsensusRow.ratified_decision_id,
            )
            .where(SilentConsensusRow.project_id == project_id)
            .where(SilentConsensusRow.status == "ratified")
            .where(DecisionRow.resolver_id == user_id)
            .order_by(SilentConsensusRow.ratified_at.desc())
        )
        rows = list((await self._session.execute(stmt)).all())
        count = len(rows)
        recent = [r[0] for r in rows[:10]]
        return count, recent


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


class MembraneSubscriptionRepository:
    """Phase 2.A — persistence for owner-configured external signal feeds.

    Rows are soft-deactivated (active=False) rather than physically deleted,
    so the audit log ("this feed was active from X to Y and produced these
    signals") stays queryable via the MembraneSignalRow trail.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: str,
        kind: str,
        url_or_query: str,
        created_by_user_id: str | None,
    ) -> MembraneSubscriptionRow:
        row = MembraneSubscriptionRow(
            id=_new_id(),
            project_id=project_id,
            kind=kind,
            url_or_query=url_or_query,
            created_by_user_id=created_by_user_id,
            active=True,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, sub_id: str) -> MembraneSubscriptionRow | None:
        return (
            await self._session.execute(
                select(MembraneSubscriptionRow).where(
                    MembraneSubscriptionRow.id == sub_id
                )
            )
        ).scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: str,
        *,
        active_only: bool = True,
    ) -> list[MembraneSubscriptionRow]:
        stmt = select(MembraneSubscriptionRow).where(
            MembraneSubscriptionRow.project_id == project_id
        )
        if active_only:
            stmt = stmt.where(MembraneSubscriptionRow.active.is_(True))
        stmt = stmt.order_by(MembraneSubscriptionRow.created_at.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def deactivate(self, sub_id: str) -> MembraneSubscriptionRow | None:
        row = await self.get(sub_id)
        if row is None:
            return None
        row.active = False
        await self._session.flush()
        return row

    async def mark_polled(
        self, sub_id: str, *, when: datetime | None = None
    ) -> MembraneSubscriptionRow | None:
        row = await self.get(sub_id)
        if row is None:
            return None
        row.last_polled_at = when or datetime.now(timezone.utc)
        await self._session.flush()
        return row


# ---- Phase 2.B — meeting transcript repository --------------------------


class MeetingTranscriptRepository:
    """Phase 2.B — uploaded meeting transcripts + extracted signals."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: str,
        uploader_user_id: str,
        title: str,
        transcript_text: str,
        participant_user_ids: list[str],
    ) -> MeetingTranscriptRow:
        row = MeetingTranscriptRow(
            id=_new_id(),
            project_id=project_id,
            uploader_user_id=uploader_user_id,
            title=title,
            transcript_text=transcript_text,
            participant_user_ids=list(participant_user_ids or []),
            metabolism_status="pending",
            extracted_signals={},
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, transcript_id: str) -> MeetingTranscriptRow | None:
        return (
            await self._session.execute(
                select(MeetingTranscriptRow).where(
                    MeetingTranscriptRow.id == transcript_id
                )
            )
        ).scalar_one_or_none()

    async def list_for_project(
        self, project_id: str, *, limit: int = 100
    ) -> list[MeetingTranscriptRow]:
        stmt = (
            select(MeetingTranscriptRow)
            .where(MeetingTranscriptRow.project_id == project_id)
            .order_by(MeetingTranscriptRow.uploaded_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def mark_metabolism_started(
        self, transcript_id: str
    ) -> MeetingTranscriptRow | None:
        row = await self.get(transcript_id)
        if row is None:
            return None
        row.metabolism_started_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def finalize_metabolism(
        self,
        transcript_id: str,
        *,
        status: str,
        extracted_signals: dict,
        error_message: str | None = None,
    ) -> MeetingTranscriptRow | None:
        row = await self.get(transcript_id)
        if row is None:
            return None
        row.metabolism_status = status
        row.extracted_signals = extracted_signals or {}
        row.metabolism_completed_at = datetime.now(timezone.utc)
        row.error_message = error_message
        await self._session.flush()
        return row

    async def reset_for_remetabolism(
        self, transcript_id: str
    ) -> MeetingTranscriptRow | None:
        """Clear extracted_signals + status so a fresh metabolism run
        can repopulate them. Used by the owner-only `remetabolize`
        endpoint when the original run failed or returned nothing useful.
        """
        row = await self.get(transcript_id)
        if row is None:
            return None
        row.metabolism_status = "pending"
        row.metabolism_started_at = None
        row.metabolism_completed_at = None
        row.extracted_signals = {}
        row.error_message = None
        await self._session.flush()
        return row


# ---- Phase 3.A — hierarchical KB folders + per-item license overrides ---
#
# Why two dedicated repos rather than inlining SQL in the service: the
# tree / listing code has to run three separate table reads (folders,
# items, licenses) and join the results in Python; centralising each
# table's fetch here keeps the service readable and makes tests target
# the right layer (repo tests prove CRUD; service tests prove cycle
# detection + inherit/override).


class KbFolderRepository:
    """Phase 3.A — CRUD for KB folder tree nodes.

    Cycle detection is NOT in this layer — the service does it before
    calling `set_parent`, since detecting a cycle requires walking the
    current tree and comparing the candidate edge. If the service ever
    grows a second writer, that writer must also cycle-check.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: str,
        name: str,
        parent_folder_id: str | None,
        created_by_user_id: str | None,
    ) -> KbFolderRow:
        row = KbFolderRow(
            id=_new_id(),
            project_id=project_id,
            parent_folder_id=parent_folder_id,
            name=name,
            created_by_user_id=created_by_user_id,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, folder_id: str) -> KbFolderRow | None:
        return (
            await self._session.execute(
                select(KbFolderRow).where(KbFolderRow.id == folder_id)
            )
        ).scalar_one_or_none()

    async def list_for_project(
        self, project_id: str
    ) -> list[KbFolderRow]:
        stmt = (
            select(KbFolderRow)
            .where(KbFolderRow.project_id == project_id)
            .order_by(KbFolderRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def find_root(
        self, project_id: str
    ) -> KbFolderRow | None:
        """The project's first NULL-parent folder, if any.

        Migration 0013 creates a root per project named "/"; this
        helper lets subsequent code find it without remembering the
        name. Ordering matches `list_for_project` (by created_at) so
        the oldest root wins in the degenerate case of multiple roots.
        """
        stmt = (
            select(KbFolderRow)
            .where(KbFolderRow.project_id == project_id)
            .where(KbFolderRow.parent_folder_id.is_(None))
            .order_by(KbFolderRow.created_at)
            .limit(1)
        )
        return (
            await self._session.execute(stmt)
        ).scalar_one_or_none()

    async def find_by_name(
        self,
        *,
        project_id: str,
        parent_folder_id: str | None,
        name: str,
    ) -> KbFolderRow | None:
        stmt = (
            select(KbFolderRow)
            .where(KbFolderRow.project_id == project_id)
            .where(KbFolderRow.name == name)
        )
        if parent_folder_id is None:
            stmt = stmt.where(KbFolderRow.parent_folder_id.is_(None))
        else:
            stmt = stmt.where(
                KbFolderRow.parent_folder_id == parent_folder_id
            )
        return (
            await self._session.execute(stmt)
        ).scalar_one_or_none()

    async def set_parent(
        self,
        folder_id: str,
        *,
        parent_folder_id: str | None,
    ) -> KbFolderRow | None:
        row = await self.get(folder_id)
        if row is None:
            return None
        row.parent_folder_id = parent_folder_id
        row.updated_at = datetime.now(timezone.utc)
        await self._session.flush()
        return row

    async def delete(self, folder_id: str) -> bool:
        row = await self.get(folder_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    async def count_children(self, folder_id: str) -> int:
        stmt = select(KbFolderRow).where(
            KbFolderRow.parent_folder_id == folder_id
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return len(list(rows))

    async def count_items(self, folder_id: str) -> int:
        # Post-fold (F3): all KB items — user-authored AND ingested —
        # live in kb_items. Counting both kinds ensures the "is this
        # folder empty?" gate stays correct regardless of source.
        stmt = select(KbItemRow).where(KbItemRow.folder_id == folder_id)
        rows = (await self._session.execute(stmt)).scalars().all()
        return len(list(rows))

    async def set_item_folder(
        self, item_id: str, *, folder_id: str | None
    ) -> KbItemRow | None:
        """Move an existing KB item to a new folder.

        Operates on `kb_items` rows (any source). Pre-fold this mutated
        MembraneSignalRow; post-fold all KB items — user-authored AND
        ingested — live in kb_items, so the move is uniform regardless
        of the row's source.

        Lives on the folder repo rather than KbItemRepository because
        moving items is tree-management; keeping the call co-located
        with the rest of the hierarchy API is less confusing.
        """
        row = (
            await self._session.execute(
                select(KbItemRow).where(KbItemRow.id == item_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        row.folder_id = folder_id
        await self._session.flush()
        return row


class KbItemLicenseRepository:
    """Phase 3.A — per-item license tier override CRUD.

    No row = inherit the project-level tier (the existing
    LicenseContextService flow). Presence clamps the item to a
    specific tier. Only owners write through this layer; readers
    consume via `get_map_for_items` to bulk-attach overrides to a
    list payload without N+1 reads.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, item_id: str) -> KbItemLicenseRow | None:
        stmt = select(KbItemLicenseRow).where(
            KbItemLicenseRow.item_id == item_id
        )
        return (
            await self._session.execute(stmt)
        ).scalar_one_or_none()

    async def get_map_for_items(
        self, item_ids: list[str]
    ) -> dict[str, str]:
        """Bulk fetch of {item_id: license_tier} for a list of item_ids.

        Used by the tree/listing endpoint to paint per-item license
        badges without re-querying per row. Missing items are simply
        absent from the returned map (caller falls back to inherit).
        """
        if not item_ids:
            return {}
        stmt = select(KbItemLicenseRow).where(
            KbItemLicenseRow.item_id.in_(item_ids)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        return {r.item_id: r.license_tier for r in rows}

    async def upsert(
        self,
        *,
        item_id: str,
        license_tier: str,
        set_by_user_id: str | None,
    ) -> KbItemLicenseRow:
        existing = await self.get(item_id)
        if existing is not None:
            existing.license_tier = license_tier
            existing.set_by_user_id = set_by_user_id
            existing.updated_at = datetime.now(timezone.utc)
            await self._session.flush()
            return existing
        row = KbItemLicenseRow(
            id=_new_id(),
            item_id=item_id,
            license_tier=license_tier,
            set_by_user_id=set_by_user_id,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            # Race: another request wrote the same item_id between
            # get + flush. Return the existing row (now with the
            # losing write's values — the winner's view becomes the
            # source of truth).
            await self._session.rollback()
            fresh = await self.get(item_id)
            assert fresh is not None
            return fresh
        return row

    async def clear(self, item_id: str) -> bool:
        row = await self.get(item_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True


# ---- Migration 0017 — Organization (Workspace) tier -----------------------


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

