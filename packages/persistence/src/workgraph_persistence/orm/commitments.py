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

class CommitmentRow(Base):
    """A thesis-commit — a human-authored promise of a future state,
    distinct from a DecisionRow.

    Decisions pick between options and resolve a conflict. Commitments
    bind an owner to an outcome. Drift detection measures current graph
    state vs commitments; the "delivery is behind April 30 commitment"
    card we want in-product reads from this table.

    Schema choices:
      * `headline` is the human-authored short form ("Ship Stellar
        Drift by Apr 30"). Immutable once created — if the commitment
        changes, mark this one `withdrawn` and create a new row so
        the timeline of promises stays legible.
      * `target_date` is optional. Commitments can be date-less
        ("ship with crossplay" — a quality promise, not a deadline).
      * `metric` is free-form text in v1. v2 structures it
        ({op, field, value}) so drift can evaluate quantitatively.
      * `scope_ref_{kind,id}` anchors the commitment to a graph
        entity. Unanchored commitments are allowed (v1 auto-derives
        drift by text match); anchored ones are cheaper to compare.
      * `status` lifecycle: open → met | missed | withdrawn.
        Terminal states set `resolved_at`.
      * `source_message_id` links back to the chat turn that spawned
        the commitment (for lineage + forensic replay).

    v2 additions parked for Sprint 2b (SLA): add `sla_window_seconds`
    and `sla_last_poke_at` fields. Current shape is forward-compat.
    """

    __tablename__ = "commitments"
    __table_args__ = (
        # M6: commitment lists filter by (project_id, status).
        Index("ix_commitments_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    headline: Mapped[str] = mapped_column(String(500))
    target_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    metric: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scope_ref_kind: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    scope_ref_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="open", index=True
    )
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    # SLA window (seconds). When set, the commitment is considered
    # "due-soon" during the final `sla_window_seconds` before
    # `target_date`, and "overdue" after. Escalation fans out signals
    # when the commitment enters either band. Null = no SLA tracking;
    # the commitment still exists but doesn't page anyone.
    sla_window_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # Last time the escalation ladder fired on this commitment, across
    # any band. Used to throttle: we don't re-page the owner every time
    # a graph event lands if we already paged them within the window.
    sla_last_escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )



class HandoffRow(Base):
    """A skill-succession record between two project members.

    Stage 3 of the skill atlas: when a member departs or transitions out
    of a project, the OWNER prepares a handoff from {from_user_id} to
    {to_user_id}. The role skill bundle transfers automatically (role
    skills are role-derived, so whoever holds the role gets them).
    What this row captures is the **profile-skill routine layer** — the
    non-PII working patterns the departing member's tenure produced
    that help the successor's sub-agent pick up where they left off.

    Two-step lifecycle:
      * status='draft'     — service prepared routines from the
        departing member's recent emissions; the owner reviews the
        brief in the UI before accepting.
      * status='finalized' — routines are live; successor's edge may
        consult them for skill-keyed context.

    PII-stripping contract:
      * `profile_skill_routines` stores role-level context only. No
        user_ids, no raw message bodies. Stakeholders are referenced by
        role_hint ("the eng-lead", "the qa-lead"), never by name. The
        derivation layer in services/handoff.py enforces this.
      * `brief_markdown` is the human-readable preview the owner sees
        in the dialog — it may include the from/to user's display name
        for clarity, but this column is never shipped into agent
        prompts.

    Why no foreign key cascade on delete for users: a finalized handoff
    is history. We keep the row even if a user is later removed — the
    string IDs are enough, and snapshotted display_name columns let the
    brief still render.
    """

    __tablename__ = "handoff_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    from_user_id: Mapped[str] = mapped_column(String(36), index=True)
    to_user_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="draft", index=True
    )
    role_skills_transferred: Mapped[list] = mapped_column(
        JSON, default=list
    )
    profile_skill_routines: Mapped[list] = mapped_column(
        JSON, default=list
    )
    brief_markdown: Mapped[str] = mapped_column(String(8000), default="")
    from_display_name: Mapped[str] = mapped_column(String(200), default="")
    to_display_name: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )



class LicenseAuditRow(Base):
    """Phase 1.A — cross-license reply audit row.

    One row per outbound-reply-lint evaluation: whether the reply was
    shipped clean, edited before ship, denied outright, or bumped to
    manual answer. Referenced node ids (citation targets found in the
    reply body) are persisted so compliance queries can later ask
    "which replies leaked D#42" without replaying the source messages.

    Never deletes — this is audit history. `source_user_id` is the
    reply author (typically the leader or sub-agent source); `target_
    user_id` is the recipient whose license scoped the lint.
    """

    __tablename__ = "license_audit"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_user_id: Mapped[str] = mapped_column(String(36), index=True)
    target_user_id: Mapped[str] = mapped_column(String(36), index=True)
    # Signal or context this audit row pertains to (RoutedSignalRow.id
    # for outbound-reply lint, null for preview-only evaluations).
    signal_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    # Node ids found cited in the reply body. Always a flat list[str].
    referenced_node_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Subset of referenced_node_ids that fell outside the recipient's
    # license view. Empty list == clean lint.
    out_of_view_node_ids: Mapped[list] = mapped_column(JSON, default=list)
    # 'clean' | 'edited' | 'denied' | 'manual'
    outcome: Mapped[str] = mapped_column(String(16), index=True)
    # Effective license tier used by the lint (the tighter of viewer
    # and audience). Kept for forensic replay — a later audit needs
    # to reproduce which ruleset applied.
    effective_tier: Mapped[str] = mapped_column(String(16), default="full")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


