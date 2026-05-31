from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship



from ._base import (
    Base,
    _FrecencyColumnsMixin,
    _GraphEntityBase,
    _utcnow,
)

class ConflictRow(Base):
    """Rule-detected conflict with LLM-generated explanation + options.

    `fingerprint` makes detection idempotent: identical rule + targets yields
    the same row via upsert, so re-running detection doesn't flood the
    project with duplicates. `explanation_outcome` mirrors the agent ladder
    (ok | retry | manual_review) so dashboards can spot degraded runs.
    """

    __tablename__ = "conflicts"
    __table_args__ = (
        UniqueConstraint("project_id", "fingerprint", name="uq_conflict_fingerprint"),
        # M6: conflict lists filter by (project_id, status).
        Index("ix_conflicts_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Snapshot the requirement version that surfaced the conflict so the UI
    # can tell the user "this was detected on v3; your plan has moved on."
    requirement_id: Mapped[str | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rule: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium", index=True)
    # open | resolved | dismissed | stale. A conflict goes `stale` when the
    # next detection pass no longer surfaces its fingerprint.
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    fingerprint: Mapped[str] = mapped_column(String(128), index=True)
    # ids referenced by the rule match (tasks, deliverables, risks, milestones)
    targets: Mapped[list] = mapped_column(JSON, default=list)
    # Raw rule output for debugging — before the LLM explains it.
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    # LLM-written human summary. Empty until explanation runs.
    summary: Mapped[str] = mapped_column(String, default="")
    # list[{label, detail, impact}] — at least 2 per critical conflict.
    options: Mapped[list] = mapped_column(JSON, default=list)
    explanation_prompt_version: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    explanation_outcome: Mapped[str] = mapped_column(String(32), default="pending")
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resolved_option_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )



class DecisionRow(_FrecencyColumnsMixin, Base):
    """Phase 9 — audit row for a human decision on a conflict.

    A conflict can have multiple decisions over time (currently we don't
    reopen resolved conflicts, but the schema is designed so history
    survives). The most recent row represents current state; the
    conflict's `resolved_by` / `resolved_option_index` mirror the latest
    row for fast reads.

    `apply_actions` is the structured list we asked the service to apply
    (e.g., `[{"kind": "close_risk", "risk_id": "..."}]`); `apply_outcome`
    is "ok" | "partial" | "skipped" | "failed" so the UI can flag
    decisions whose follow-through didn't complete.
    """

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Nullable because signal-chain crystallization creates decisions from
    # IM suggestions without a pre-existing conflict (vision §6).
    conflict_id: Mapped[str | None] = mapped_column(
        ForeignKey("conflicts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Back-pointer for IM-originated decisions. Nullable because
    # conflict-originated decisions have no source suggestion.
    source_suggestion_id: Mapped[str | None] = mapped_column(
        ForeignKey("im_suggestions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    resolver_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Exactly one of (option_index, custom_text) is set — service enforces.
    option_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    custom_text: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    rationale: Mapped[str] = mapped_column(String(4000), default="")
    apply_actions: Mapped[list] = mapped_column(JSON, default=list)
    apply_outcome: Mapped[str] = mapped_column(String(32), default="pending")
    apply_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Migration 0014 — Scene 2 routing gate. `decision_class` is the
    # taxonomy bucket (budget / legal / hire / scope_cut …); copied from
    # the source GatedProposalRow on approve. Non-gated decisions leave
    # both NULL. `gated_via_proposal_id` points at the GatedProposalRow
    # that produced this decision; SET NULL on delete so audit history
    # survives proposal cleanup.
    decision_class: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    gated_via_proposal_id: Mapped[str | None] = mapped_column(
        ForeignKey("gated_proposals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Migration 0027 — smallest-relevant-vote routing (new_concepts.md
    # §6.11 + north-star Correction R.2). Crystallization Agent stamps
    # the smallest stream that contained the discussion (DM / room /
    # cell-wide stream); vote quorum derives from that stream's member
    # list. NULL means fall back to cell-wide (project-level) vote.
    # SET NULL on stream delete so a deleted room doesn't cascade-
    # destroy its decisions.
    scope_stream_id: Mapped[str | None] = mapped_column(
        ForeignKey("streams.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )



class GatedProposalRow(Base):
    """Migration 0014 — Scene 2 routing: a decision proposal sitting in
    front of a gate-keeper's sign-off.

    When the edge agent classifies a user utterance as a decision of a
    gated class (budget, legal, hire, scope_cut, …) AND the project has
    a named gate-keeper for that class in `projects.gate_keeper_map`,
    the source user's sub-agent offers a `route_kind='gated'` proposal.
    On "send for sign-off", a GatedProposalRow is created and a routed
    signal lands in the gate-keeper's sidebar with approve/deny/edit.

    Crystallization contract: `status` transitions
        pending → approved | denied | withdrawn
    On `approved`, `GatedProposalService.approve` creates a DecisionRow
    whose `gated_via_proposal_id` points back here and runs
    `apply_actions` exactly once. On `denied` or `withdrawn`, no
    DecisionRow is created — the project's graph state never moves on
    this proposal.

    Non-goals:
      * NOT a transport primitive for every routed signal — reuse
        RoutedSignalRow for discovery / handoff / leader-escalation.
      * NOT a denial-of-service guard: rate-limiting lives in the
        service layer, not the schema.

    Lineage: the reverse direction (decision → proposal) lives on
    DecisionRow.gated_via_proposal_id to avoid a circular FK.
    """

    __tablename__ = "gated_proposals"
    __table_args__ = (
        # M6: gate-keeper inbox filters by (gate_keeper_user_id, status);
        # project listing by (project_id, status). status was unindexed.
        Index("ix_gated_proposals_gatekeeper_status", "gate_keeper_user_id", "status"),
        Index("ix_gated_proposals_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    proposer_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    gate_keeper_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    decision_class: Mapped[str] = mapped_column(String(32))
    proposal_body: Mapped[str] = mapped_column(String(4000))
    # v0.5 polish — the user's raw utterance that triggered the
    # gated route. `proposal_body` is the edge agent's framing
    # ("Scope cut — Maya gates scope decisions…") which is useful
    # context for the gate-keeper, but the gate-keeper is actually
    # approving what the PROPOSER committed to, not the agent's
    # paraphrase. Rendering both preserves attribution + avoids the
    # "LLM put words in my mouth" failure mode. Nullable because
    # pre-0015 rows have no captured raw text and older callers may
    # omit it.
    decision_text: Mapped[str | None] = mapped_column(
        String(4000), nullable=True
    )
    # Same shape as DecisionRow.apply_actions — a list of
    # structured mutation ops the service replays on approve.
    apply_actions: Mapped[list] = mapped_column(JSON, default=list)
    # Status lifecycle:
    #   pending  — single-approver path: waiting on gate_keeper
    #   in_vote  — multi-voter path (Phase S): opened to a voter pool,
    #              waiting for threshold on approve or deny_unreachable
    #   approved — DecisionRow created, apply_actions run (advisory in v0)
    #   denied   — no DecisionRow; proposal shelved
    #   withdrawn— proposer pulled it back before resolution
    status: Mapped[str] = mapped_column(String(16), default="pending")
    resolution_note: Mapped[str | None] = mapped_column(
        String(2000), nullable=True
    )
    # Phase S voting — populated when status transitions to 'in_vote'.
    # Each entry is a user_id eligible to cast a verdict on this
    # proposal. Threshold is ceil(len(voter_pool)/2) (simple majority).
    # NULL on pre-vote proposals + on proposals that resolve via the
    # single-approver path without ever entering vote mode.
    voter_pool: Mapped[list | None] = mapped_column(JSON, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )



class VoteRow(Base):
    """Migration 0016 — Phase S: votes as first-class graph nodes.

    A vote is not a transient tally — it is a persisted node on the
    graph. Each row captures one voter's verdict on one subject, plus
    the rationale they offered. The shape is deliberately polymorphic
    via (subject_kind, subject_id) so voting can extend beyond gated
    proposals later (votes on decisions, commitments, drift alerts)
    without another migration.

    Contract:
      * One row per (subject_kind, subject_id, voter_user_id) —
        enforced by the composite unique index. Voters can change
        their verdict until the subject resolves; that UPDATEs the
        existing row (setting updated_at) rather than inserting a
        second row.
      * `verdict ∈ {approve, deny, abstain}`. Pending state is
        represented by the *absence* of a row — we don't seed pending
        rows on open, so query counts reflect actual participation.
      * Votes feed the voter's observed profile: every cast bumps
        the `votes_cast` key in UserRow.profile.signal_tally and
        contributes to the `voting_profile` slice in compute_profile.

    Non-goals:
      * NOT a transport primitive. The voter's inbox card is backed
        by RoutedSignalRow (reuses the existing fan-out plumbing);
        VoteRow only stores the verdict.
      * NOT the threshold-resolution state. Resolution lives on the
        subject row (e.g. GatedProposalRow.status goes 'in_vote' →
        'approved' | 'denied'); VoteRow is the raw input.
    """

    __tablename__ = "votes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Polymorphic reference. No FK because it crosses tables; integrity
    # is maintained at the service layer (the subject must exist +
    # be in a vote-open state before a row can be created).
    subject_kind: Mapped[str] = mapped_column(String(32), index=True)
    subject_id: Mapped[str] = mapped_column(String(36), index=True)
    voter_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    verdict: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str | None] = mapped_column(
        String(2000), nullable=True
    )
    trace_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "subject_kind",
            "subject_id",
            "voter_user_id",
            name="uq_votes_subject_voter",
        ),
    )



class DissentRow(Base):
    """Phase 2.A — recorded disagreement on a crystallized decision.

    Members who disagree with a DecisionRow record their stance. When
    downstream events vindicate or refute the dissent, the row flips
    `validated_by_outcome` and appends the supporting event id to
    `outcome_evidence_ids`. Rolled-up per-member accuracy feeds the
    team perf panel — see services.perf_aggregation.

    Uniqueness is enforced at (decision_id, dissenter_user_id): a
    member can only hold one active dissent per decision. The service
    upserts — a second POST replaces the stance_text and resets the
    validation state — so historical stances are NOT preserved across
    edits. EventRow writes on each upsert carry the before/after so
    audit replay still works if anyone needs to reconstruct the
    timeline.

    `validated_by_outcome` values:
      * None         — not yet validated (recent dissent, no triggering
                        event observed)
      * 'supported'  — a downstream event vindicated the dissent (e.g.
                        the decision was superseded by a new decision on
                        the same conflict)
      * 'refuted'    — the decision's chosen direction bore fruit (e.g.
                        the decision's apply_actions produced a concrete
                        downstream status flip)
      * 'still_open' — explicit "inconclusive" state for dissents whose
                        decision hasn't yielded enough signal. Reserved
                        for a v2 time-window sweep; v1 writes this only
                        on explicit request.
    """

    __tablename__ = "dissents"
    __table_args__ = (
        UniqueConstraint(
            "decision_id",
            "dissenter_user_id",
            name="uq_dissent_decision_user",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"), index=True
    )
    dissenter_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    stance_text: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    validated_by_outcome: Mapped[str | None] = mapped_column(
        String(16), nullable=True, index=True
    )
    outcome_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)



class ScrimmageRow(Base):
    """Phase 2.B — agent-vs-agent debate transcript.

    Two sub-agents (source's and target's) exchange 2–3 turns before any
    human sees the question. On convergence we propose a pending decision
    for the leader to approve; on non-convergence we surface both final
    stances to humans as a debate summary card.

    `transcript_json` shape:
        list[{turn: int, speaker: 'source'|'target', text: str,
              stance: 'agree_with_other'|'propose_compromise'|'hold_position',
              proposal_summary: str | None,
              citations: list[dict]}]

    `outcome` values:
        'converged_proposal' — both agents landed on the same proposal
        'unresolved_crux'    — 3 turns without convergence
        'in_progress'        — transient (should never persist on return)

    `proposal_json` carries the converged proposal text + both final
    stances when outcome == 'converged_proposal'. Null otherwise.

    `routed_signal_id` is nullable: scrimmage can fire without a
    pre-existing routing (pre-commit rehearsal path) OR as a pre-step
    to a route that may never land if convergence succeeds.
    """

    __tablename__ = "scrimmages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    routed_signal_id: Mapped[str | None] = mapped_column(
        ForeignKey("routed_signals.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_user_id: Mapped[str] = mapped_column(String(36), index=True)
    target_user_id: Mapped[str] = mapped_column(String(36), index=True)
    question_text: Mapped[str] = mapped_column(String(4000))
    transcript_json: Mapped[list] = mapped_column(JSON, default=list)
    outcome: Mapped[str] = mapped_column(
        String(32), default="in_progress", index=True
    )
    proposal_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )



class SilentConsensusRow(Base):
    """Phase 1.A — behavioral-agreement proposal.

    When N members act consistently on a topic within a short window AND
    no dissent / counter-decision is recorded, the scanner emits a pending
    SilentConsensusRow. A project owner / full-tier reader ratifies it →
    DecisionRow is created with lineage pointing back to the supporting
    actions, and the row flips to 'ratified'. Rejection flips 'rejected'
    without producing a decision.

    `supporting_action_ids` shape:
        list[{kind: 'task_status'|'decision'|'commit', id: str}]

    `member_user_ids` is the set of distinct members whose actions
    underpinned the proposal. `confidence` is a float 0–1 keyed off
    member-count × action-consistency.

    Topic identity: v1 uses `topic_text` string match — two scans on the
    same deliverable produce the same topic_text, so the "no existing
    pending" guard works as a dedupe key. Not a DB uniqueness constraint
    because rejected / ratified rows on the same topic remain valid
    history (someone may ratify a similar shape later).
    """

    __tablename__ = "silent_consensus"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    topic_text: Mapped[str] = mapped_column(String(500))
    supporting_action_ids: Mapped[list] = mapped_column(JSON, default=list)
    inferred_decision_summary: Mapped[str] = mapped_column(String(4000), default="")
    member_user_ids: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    ratified_decision_id: Mapped[str | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ratified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )



class DeliverySummaryRow(Base):
    """Phase 10 — generated delivery summary.

    One project can regenerate the summary many times. Each row is an
    immutable snapshot of graph-derived state + the agent's synthesis.
    `parse_outcome` uses the same enum as other agents (ok | retry |
    manual_review). `qa_report` captures the pre-check: which scope items
    were covered, deferred, or uncovered. `uncovered_items` being
    non-empty means the row was produced in `manual_review` mode and
    the UI should flag it.
    """

    __tablename__ = "delivery_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    requirement_version: Mapped[int] = mapped_column(Integer, default=0)
    content_json: Mapped[dict] = mapped_column(JSON, default=dict)
    parse_outcome: Mapped[str] = mapped_column(String(32), default="ok")
    qa_report: Mapped[dict] = mapped_column(JSON, default=dict)
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


# ---- Phase B (v2) — stream primitive ------------------------------------
#
# North-star §"Streams as the unifying primitive": one renderer, everywhere.
# A stream has membership, an optional project anchor, and a type. Project
# streams mirror existing ProjectRow membership (backfilled on boot); DM
# streams are 1:1 ad-hoc, deduped by sorted member pair.


