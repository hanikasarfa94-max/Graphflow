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


