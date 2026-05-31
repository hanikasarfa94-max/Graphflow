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

class KbFolderRow(Base):
    """One folder in a project's hierarchical KB.

    Root folders have parent_folder_id = NULL. Migration 0013 backfills
    a single root folder per project and places every pre-existing KB
    item (MembraneSignalRow) there, so the tree is always non-empty
    once the migration has run.

    name is unique within (project_id, parent_folder_id) — no two
    siblings share a label. Enforced in the service (the UniqueConstraint
    would trip with NULL semantics inconsistently across dialects).
    """

    __tablename__ = "kb_folders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    parent_folder_id: Mapped[str | None] = mapped_column(
        ForeignKey("kb_folders.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )



class KbItemRow(_FrecencyColumnsMixin, Base):
    """Migration 0019 — Phase V: first-class user-authored KB note.
    Migration 0022 — absorbs MembraneSignalRow's shape so externally-
    ingested signals can live in the same table (source='ingest').

    Two row families share this table:
      * user-authored: source in {'manual','upload','llm'}; project_id
        and owner_user_id always set; signal-shaped columns NULL.
      * ingested:      source='ingest'; source_kind discriminates the
        ingest sub-type (git-commit/rss/user-drop/webhook); project_id
        and owner_user_id may be NULL (org-level ingests, webhook
        payloads); signal-shaped columns populated.

    Scope semantics (user-authored only — ingests don't have scope).
    Four-tier ladder per new_concepts.md §6.11; legacy `'group'`
    is kept as the Cell-scope value (north-star Correction R locks
    "no schema rename"):
      * 'personal'   — visible only to owner_user_id. Edge LLM uses
        these as private pretext for that user's sub-agent ONLY. Never
        bleeds into other members' contexts. Default scope on create.
      * 'group'      — Cell scope: shared with all project members.
        LLM uses for everyone. Promoted from personal via an explicit
        owner action (Phase V.1) or LLM-mediated route (Phase V.2).
        Group items affect everyone's pretext, so the promotion flow
        gates carefully.
      * 'department' — N-Next: functional subset (Eng / Design /
        Marketing KB). Membership tables land in B1.2; today this
        value is accepted on writes but read access falls back to
        OrganizationMemberRow visibility.
      * 'enterprise' — N-Next: org-wide (HR, brand, compliance).
        Read access gated by OrganizationMemberRow.

    The scope tier is orthogonal to ProjectMemberRow.license_tier
    (full / task_scoped / observer).

    The folder_id link is optional: items without a folder live at root.
    Folder = the existing KbFolderRow; we don't add a second hierarchy.

    `content_md` stores markdown. v1 caps at 64KB (DB column limit) —
    larger uploads get a placeholder body + an external blob ref later.

    `status` lifecycle, user-authored:
      draft → published → archived
    `status` lifecycle, ingested:
      pending-review → approved | routed | rejected
    No DB-level enum; app layer (services/kb_items.py) holds the
    VALID_STATUSES set and the legal transitions.
    """

    __tablename__ = "kb_items"
    __table_args__ = (
        # M6: KB lists filter by (project_id, scope) for group and
        # (project_id, scope, owner_user_id) for personal — the 3-col index
        # serves both via its leading prefix.
        Index("ix_kb_items_project_scope_owner", "project_id", "scope", "owner_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Nullable since 0022 — org-level ingests have no project (mirrors
    # the old MembraneSignalRow.project_id semantics).
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    folder_id: Mapped[str | None] = mapped_column(
        ForeignKey("kb_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Nullable since 0022 — webhook/cron ingests have no human owner.
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scope: Mapped[str] = mapped_column(String(16), default="personal", index=True)
    title: Mapped[str] = mapped_column(String(500))
    content_md: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String(16), default="published")
    # Source tag — 'manual' (typed in the UI), 'upload' (file ingest),
    # 'llm' (created by the user's edge sub-agent on their request),
    # 'ingest' (external content via membrane pipeline; see source_kind
    # for the sub-type).
    source: Mapped[str] = mapped_column(String(16), default="manual")
    # ---- ingest-only columns (added in 0022) ---------------------------
    # Discriminates ingest sub-type when source='ingest'. NULL otherwise.
    # Values: 'git-commit' | 'git-pr' | 'steam-review' | 'steam-forum' |
    # 'rss' | 'user-drop' | 'webhook'.
    source_kind: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    # URL / commit hash / forum post id — paired with project_id for
    # dedup at the app layer (KbItemRepository.upsert_ingest).
    source_identifier: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    # Pre-classification text, trimmed at ingest to the first 4000
    # chars. NULL for non-ingests; their authored content lives in
    # content_md only.
    raw_content: Mapped[str | None] = mapped_column(String, nullable=True)
    # MembraneAgent output (is_relevant, tags, summary, proposed_target_
    # user_ids, proposed_action, confidence, safety_notes). Defaults to
    # an empty dict so non-ingest reads don't need a None-check.
    classification_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # Who dropped the link (user-drop) — null for cron/webhook pulls
    # and for non-ingests.
    ingested_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # ---- Phase B (migration 0020) — file attachment metadata ---------
    # All four populated together when source='upload'; null for
    # manual / llm-authored items. Bytes live on disk at
    # `<KB_UPLOADS_ROOT>/<item_id>/<attachment_filename>` — we don't
    # store the absolute path so the root can move (volume mount,
    # different host) without rewriting rows.
    attachment_filename: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )
    attachment_mime: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    attachment_bytes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )



class KbItemLicenseRow(Base):
    """Per-KB-item license tier override.

    Absence of a row for a given item_id means "inherit the project-level
    tier for the viewing member" (the existing license_context flow).
    Presence means "this specific item is clamped to `license_tier`,
    regardless of how much access the member would otherwise have at
    the project level." Only project owners set/clear overrides; the
    enforcement layer is routers/kb.py + service-side filtering on
    the tree listing.

    Allowed license_tier values mirror ProjectMemberRow.license_tier:
    'full' | 'task_scoped' | 'observer'.
    """

    __tablename__ = "kb_item_licenses"
    __table_args__ = (
        UniqueConstraint("item_id", name="uq_kb_item_license_item"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # item_id points at kb_items.id (post-fold; F5 / migration 0024).
    # Pre-fold this referenced membrane_signals.id; ids are preserved
    # across the F2 backfill so existing override rows still resolve.
    item_id: Mapped[str] = mapped_column(
        ForeignKey("kb_items.id", ondelete="CASCADE"), index=True
    )
    license_tier: Mapped[str] = mapped_column(String(16))
    set_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


# ---- Migration 0017 — Organization (Workspace) tier -----------------------



class MembraneSubscriptionRow(Base):
    """Phase 2.A — per-project external signal subscription.

    Vision §5.12 (active membrane). A subscription is a *recipe* the
    cron agent runs periodically; each run emits MembraneSignalRow
    proposals that still flow through MembraneAgent.classify + the
    status='proposed' human-confirmable gate.

    `kind`:
      * 'rss'          — `url_or_query` is a feed URL; cron fetches new items
      * 'search_query' — `url_or_query` is a fixed Tavily query string; cron
                         fires it on each scan

    The cron itself also invents queries on the fly from project context —
    those writes don't need a subscription row. Subscription rows capture
    owner-configured standing interests (e.g. a competitor's blog).
    """

    __tablename__ = "membrane_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 'rss' | 'search_query'
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    url_or_query: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )



class MeetingTranscriptRow(Base):
    """Phase 2.B — uploaded meeting transcript + its metabolized signals.

    Upload-only; no real-time ASR. Users paste plain text or upload a
    `.txt` / `.md` / `.srt` / `.vtt` file (service strips SRT/VTT
    timestamps client-side before POST). The edge LLM then extracts
    four signal kinds from the raw text:

        * decisions  — explicit choices reached during the meeting
        * tasks      — action items, ideally with a suggested owner
        * risks      — concerns or hazards raised
        * stances    — per-participant positions on unresolved topics

    These are *proposals*: the row is inert until a member clicks
    "Accept" on a specific signal, which routes through the existing
    DecisionRow / TaskRow / RiskRow creation paths. The meeting row
    is never the source of truth for graph state — it's provenance.

    `metabolism_status` lifecycle:
        'pending'  — row just created, background task queued
        'done'     — edge LLM returned structured JSON; signals populated
        'failed'   — LLM output malformed after retries or agent raised;
                     error_message populated, signals left empty. User
                     can hit `remetabolize` (owner-only) to retry.

    `extracted_signals` shape once metabolism completes:
        {
            "decisions": [{"text": str, "rationale"?: str}, ...],
            "tasks":     [{"title": str, "suggested_owner_hint"?: str,
                           "description"?: str}, ...],
            "risks":     [{"title": str, "severity"?: "low"|"medium"|"high",
                           "content"?: str}, ...],
            "stances":   [{"participant_hint": str, "topic": str,
                           "stance": str}, ...],
        }

    `participant_user_ids` is best-effort. v1 expects the uploader to
    pass a list (pulled from a `@mention` parse or manual tagging on the
    upload form). Empty list is fine — the metabolism prompt can still
    infer participant stances by whatever hints the transcript itself
    carries (e.g. speaker labels).

    License tier is inherited from the parent project — transcripts are
    as confidential as the project that owns them, same as KB items.
    """

    __tablename__ = "meeting_transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    uploader_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), default="")
    transcript_text: Mapped[str] = mapped_column(String, default="")
    participant_user_ids: Mapped[list] = mapped_column(JSON, default=list)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    metabolism_status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True
    )
    metabolism_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metabolism_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extracted_signals: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(
        String(2000), nullable=True
    )


# ---- Phase 3.A — hierarchical KB ----------------------------------------
#
# KB was flat (MembraneSignalRow on its own) through V3. V4 turns it
# into a tree so enterprises can express per-folder ACLs and so book
# rendering has a meaningful unit to recurse on. We keep the existing
# MembraneSignalRow as the leaf (audit URLs stable), add a per-project
# folder tree, and layer an optional per-item license override. The
# service layer does cycle detection on reparent; the DB does not (a
# cycle constraint is not enforceable in sqlite and adds complexity
# with no payoff — the service is the only writer).


