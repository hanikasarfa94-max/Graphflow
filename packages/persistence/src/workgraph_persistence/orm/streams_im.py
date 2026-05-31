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

class StreamRow(Base):
    """Unifying conversation container.

    Types in v1 (post-Phase L):
      * 'project'  — main team room, exactly one per project, all
                     project members. Created at project boot.
      * 'personal' — private (user ↔ their edge-agent), project-anchored,
                     owner_user_id set; primary surface per north-star
                     §"Sub-agent and routing architecture"
      * 'dm'       — 1:1 between two users, no project anchor

    Types added in N-Next (per new_concepts.md §6.11 + north-star
    Correction R.2):
      * 'room'     — sub-team / topical / ad-hoc room INSIDE a cell
                     (project_id set; member subset of cell members).
                     Multiple rooms per project allowed. Decision votes
                     crystallized inside a room default to that room's
                     member quorum (smallest-relevant-vote rule).

    `last_activity_at` is bumped on every new message so GET /api/streams
    can order by recency without scanning messages.

    `owner_user_id` is populated only for personal streams (the human who
    owns the sub-agent conversation). Null for project / dm / room.
    """

    __tablename__ = "streams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # v1: 'project' | 'personal' | 'dm'. N-Next adds 'room'.
    # v2 reserves 'group' (3-10 ad-hoc) + 'rehearsal'.
    type: Mapped[str] = mapped_column(String(16))
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Phase L: owner of a personal stream (user whose sub-agent converses
    # here). Null for type in {'project', 'dm'}.
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Room-stream slice: persisted display name for type='room' streams
    # (e.g. "design-sync", "auth-redesign"). Nullable because
    # project/personal/dm streams don't carry a name — they derive their
    # display from the project / owner / DM partner. Surfaced via
    # GET /api/projects/{id}/rooms so the room nav and DecisionCard
    # vote-scope explainer can render real names.
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )



class StreamMemberRow(Base):
    """Stream ↔ user join. For project streams, mirrors ProjectMemberRow at
    boot-time backfill; for DM streams, holds exactly two rows.

    `last_read_at` powers the unread_count computation on GET /api/streams
    (messages authored after my last_read_at == unread for me).
    """

    __tablename__ = "stream_members"
    __table_args__ = (
        UniqueConstraint("stream_id", "user_id", name="uq_stream_member"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stream_id: Mapped[str] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 'member' | 'admin' | 'observer'. Mirrors ProjectMemberRow.license_tier
    # shape but scoped to stream capability (e.g., observer cannot post).
    role_in_stream: Mapped[str] = mapped_column(String(16), default="member")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---- Phase L — sub-agent routing primitive ------------------------------
#
# North-star §"Sub-agent and routing architecture": Maya's edge-agent routes
# a framed signal to Raj's edge-agent via the parent-agent hub. The signal
# carries Maya's framing, background snippets, and a rich option set Raj
# picks from. One row per routed flow; status transitions pending →
# replied → (accepted | declined | expired).


# MembraneSignalRow was deleted in migration 0024 (Stage F5 of the
# fold). External-signal ingests now live in `kb_items` with
# source='ingest'; KbItemRow carries every field MembraneSignalRow
# used to carry. See docs/membrane-reorg.md follow-up for the
# rationale and the full F1–F5 migration trail.



class MessageRow(_FrecencyColumnsMixin, Base):
    """Per-stream IM message. Plain text or markdown, no attachments.

    Phase B (v2): messages attach to a `stream_id`; `project_id` stays populated
    for project streams (denormalized for fast queries) and is null for DM
    streams. The dev-boot backfill helper fills `stream_id` on any re-seeded
    messages by project_id lookup.

    Phase L: `kind` + `linked_id` let the frontend render sub-agent routing
    cards without parsing the body. Chosen over a body-marker string
    (`[[routed-signal:id]]`) because structured columns are cheaper to
    filter (e.g. inbox queries) and don't break when body is localized.
    `kind` values in v1:
      * 'text'                     — default human / edge turn
      * 'routed-inbound'           — target's personal stream received a routing ask
      * 'routed-reply'             — source's personal stream received the reply
      * 'routed-dm-log'            — DM mirror summary of a routed flow
      * 'gated-proposal-pending'   — gate-keeper's stream: a new gated
                                     decision is awaiting their sign-off
                                     (linked_id → gated_proposals.id)
      * 'gated-proposal-resolved'  — proposer's stream: the gate-keeper
                                     approved / denied / (rare) the
                                     proposer withdrew the proposal
                                     (linked_id → gated_proposals.id)
    `linked_id` points at `routed_signals.id` when kind starts with
    'routed-', or `gated_proposals.id` when kind starts with 'gated-'.
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    stream_id: Mapped[str | None] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), index=True, nullable=True
    )
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(String)
    # Phase L — see class docstring for allowed values.
    kind: Mapped[str] = mapped_column(String(16), default="text")
    # Phase L — opaque FK-shape id linking to the driver row; for 'routed-*'
    # kinds this references routed_signals.id. Kept as plain String so the
    # column generalizes to other card kinds without a table-specific FK.
    linked_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)



class IMSuggestionRow(Base):
    """AI-IM pre-processor output bound to a source message.

    kind ∈ {none, tag, decision, blocker}. `status` transitions from
    "pending" → "accepted" / "dismissed" / "countered" / "escalated".
    Accepting a decision-kind triggers a graph mutation; blocker-kind
    opens a RiskRow; countered spawns a new suggestion whose
    `counter_of_id` points back; escalated flips `escalation_state`.
    """

    __tablename__ = "im_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), unique=True, index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(default=0.0)
    targets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    proposal: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reasoning: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")
    prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), default="ok")
    attempts: Mapped[int] = mapped_column(default=1)
    # Signal-chain primitives (vision §6). All nullable so existing rows keep
    # validating and the counter/escalate/crystallize flows stay opt-in.
    counter_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("im_suggestions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decision_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "decisions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_im_suggestion_decision",
        ),
        nullable=True,
        index=True,
    )
    # "requested" or null. v0 is just a flag — no meeting scheduled.
    escalation_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )



class CommentRow(Base):
    """Threaded comment on a Task / Deliverable / Risk.

    `target_kind` + `target_id` give the anchor. `parent_comment_id` enables
    threading; null = top-level.
    """

    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    target_kind: Mapped[str] = mapped_column(String(32))  # task | deliverable | risk
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    parent_comment_id: Mapped[str | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True
    )
    body: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)



class NotificationRow(Base):
    """In-app notification queue. Read state + trigger metadata."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # assigned | mentioned | message | suggestion | conflict
    body: Mapped[str] = mapped_column(String)
    target_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ---- Phase 8 — conflict detection ---------------------------------------



class RoutedSignalRow(Base):
    """Sub-agent-mediated cross-user signal.

    Created when source's edge-agent dispatches an ask to target's edge-agent.
    The source and target both have personal streams in the same project;
    dispatch posts a 'routed-inbound' message into target's personal stream
    and mirrors a summary into their DM. On reply, a 'routed-reply' message
    lands in source's personal stream.

    `background_json` shape:
      list of {source: 'graph'|'kb'|'history', snippet: str, reference_id?: str}
    `options_json` shape (post-Phase-L option design):
      list of {id, label, kind, background, reason, tradeoff, weight(0-1)}
    `reply_json` shape (once target replies):
      {option_id?: str, custom_text?: str, responded_at: iso8601}
    """

    __tablename__ = "routed_signals"
    __table_args__ = (
        # M6: inbox/outbox lists filter by (target_user_id, status) and
        # (source_user_id, status).
        Index("ix_routed_signals_target_status", "target_user_id", "status"),
        Index("ix_routed_signals_source_status", "source_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    target_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_stream_id: Mapped[str] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), index=True
    )
    target_stream_id: Mapped[str] = mapped_column(
        ForeignKey("streams.id", ondelete="CASCADE"), index=True
    )
    # Null allowed in theory (cross-project routing is a v2 thought); in v1
    # callers always pass a project_id and service enforces same-project.
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    framing: Mapped[str] = mapped_column(String(4000))
    background_json: Mapped[list] = mapped_column(JSON, default=list)
    options_json: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    reply_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


