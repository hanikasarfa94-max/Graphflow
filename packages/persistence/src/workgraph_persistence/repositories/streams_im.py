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

    async def get_personal_global_for_user(
        self, *, user_id: str
    ) -> StreamRow | None:
        """v-Next — the user's single 通用 (global) personal stream.

        StreamRow with type='personal', owner_user_id=user, project_id=NULL.
        Distinct from per-project personal streams; the user's
        cross-project agent surface. Same '.first() prefers oldest' guard
        as get_personal_for_user_in_project for race-condition tolerance.
        """
        stmt = (
            select(StreamRow)
            .where(
                StreamRow.project_id.is_(None),
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
        # COUNT(*) in the DB, not fetch-all-ids-then-len() in Python.
        stmt = select(func.count()).select_from(NotificationRow).where(
            NotificationRow.user_id == user_id,
            NotificationRow.read == False,  # noqa: E712
        )
        return int((await self._session.execute(stmt)).scalar_one())

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

    # ---- C.1 — atomic conditional helpers for the flow action surface ----
    #
    # The legacy `mark_accepted` / `mark_replied` methods do SELECT-then-
    # mutate, which has a check-then-act race. The new flow-action endpoint
    # (FlowActionService → RoutingService.source_*) is the first mutation
    # surface that requires hard atomicity guarantees, so it gets the
    # proper conditional-update primitive. Legacy paths stay as-is for now;
    # C.2 is the moment to converge if target-side actions also need it.

    async def update_status_if(
        self, signal_id: str, *, expect: str, set_to: str,
    ) -> bool:
        """Atomic conditional update. Returns True iff exactly one row
        was updated (signal existed AND was in `expect` status).

        Caller maps False → not_ready_for_source_action.
        """
        result = await self._session.execute(
            update(RoutedSignalRow)
            .where(RoutedSignalRow.id == signal_id)
            .where(RoutedSignalRow.status == expect)
            .values(status=set_to)
        )
        return result.rowcount == 1

    async def append_source_action_note(
        self,
        signal_id: str,
        *,
        action: str,
        note: str | None,
        at: str,
    ) -> None:
        """Append a {action, note, at} record to
        reply_json["source_action_notes"]. Caller has already verified
        the row exists (typically right after a successful
        `update_status_if`).

        The reply_json blob is mutated in-place rather than via a
        conditional UPDATE because only the source ever appends here,
        and the source's own actions are serialized through the HTTP
        endpoint. Concurrency concern is the status flip — already
        handled by `update_status_if`.
        """
        row = await self.get(signal_id)
        if row is None:
            return
        rj = dict(row.reply_json or {})
        notes = list(rj.get("source_action_notes") or [])
        notes.append({"action": action, "note": note or "", "at": at})
        rj["source_action_notes"] = notes
        row.reply_json = rj
        await self._session.flush()

    async def delete(self, signal_id: str) -> None:
        """Remove a signal row by id. Used for compensating rollback in
        the source_counter flow (spawn-first; if the conditional update
        on the original fails, the just-spawned row is deleted to avoid
        leaving a phantom counter packet).
        """
        await self._session.execute(
            delete(RoutedSignalRow).where(RoutedSignalRow.id == signal_id)
        )


# ---- Phase D — membrane signal repository -------------------------------


