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


