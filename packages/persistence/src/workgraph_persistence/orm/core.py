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

class ProjectRow(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    # Per decision 1E: no current_stage denormalization. The graph (latest
    # requirement version + unanswered clarifications + downstream rows) IS
    # the stage. See workgraph_persistence.stage.project_stage().
    requirements: Mapped[list[RequirementRow]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="RequirementRow.version",
    )

    # Migration 0014 — Scene 2 routing gate. Per-project map
    # `{decision_class: user_id}` naming the gate-keeper whose sign-off is
    # required before a decision of that class crystallizes. Empty map =
    # no gates apply. Managed via project settings UI + the
    # `GatedProposalService` flow. NOT NULL server-default '{}' so
    # existing projects stamp clean on migration.
    gate_keeper_map: Mapped[dict] = mapped_column(JSON, default=dict)

    # Migration 0017 — Organization (Workspace) tier. Nullable because
    # existing projects predate the tier and stay unassigned until the
    # owner explicitly nests them. SET NULL on org delete so a deleted
    # workspace doesn't cascade-destroy its projects — they fall back to
    # standalone until reassigned.
    organization_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )



class UserRow(Base):
    """Demo-only user row. username + bcrypt-equivalent password hash.

    Phase 7' ships without SSO / email verification / password reset. The
    hash is pbkdf2-sha256 with a per-user salt — stdlib-only, strong enough
    for the competition demo surface.

    Phase B (v2): `profile` carries response-profile fields (declared_abilities,
    role_hints, signal_tally) per north-star "Profile as first-class
    primitive". `display_language` drives per-user UI chrome localization.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(256))
    password_salt: Mapped[str] = mapped_column(String(64))
    # Response profile (north-star §"Profile as first-class primitive"). Keys:
    #   declared_abilities: list[str] — self-declared at onboarding
    #   role_hints: list[str] — nudges from assigned role / management
    #   signal_tally: dict[str, int] — rolling-window counts of observed emissions
    # v1 stores the shape; signal_tally wire-up is v2.
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    # ISO-639-1 code; 'en' | 'zh' in v1. Per-user chrome language.
    display_language: Mapped[str] = mapped_column(String(8), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)



class SessionRow(Base):
    """Server-side session. Cookie carries only the opaque token."""

    __tablename__ = "auth_sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# ---- Phase 7'' — collab primitives --------------------------------------



class ProjectMemberRow(Base):
    """Explicit project ↔ user join. Creator auto-joins at project create.

    Phase B (v2): `license_tier` scopes member capability per north-star §"Scoped
    license model". `observer` cannot mutate project state (message post,
    accept/counter/escalate). `task_scoped` is stored in v1 but enforcement
    (restrict writes to assigned tasks only) lands in v2.
    """

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(32), default="member")
    # 'full' | 'task_scoped' | 'observer'. v1 enforces 'observer' only.
    license_tier: Mapped[str] = mapped_column(String(16), default="full")
    # Migration 0026 — per-project functional skill tags. Free-form
    # strings drawn from the same vocabulary as TaskRow.assignee_role
    # (pm/frontend/backend/qa/design/business/approver). Used by the
    # membrane's task_promote review for assignee-coverage checks: a
    # task tagged role='backend' with no project member carrying that
    # tag emits an advisory warning. Self-editable per member; owners
    # can also edit any member's tags.
    skill_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)



class OrganizationRow(Base):
    """A Workspace (Studio / Enterprise) — the tier above ProjectRow.

    User-facing label is "Workspace" (EN) / "工作空间" (ZH); internally we
    keep the neutral "Organization" name so code stays readable for both
    studio and enterprise deployments.

    v1 is intentionally minimal:
      * One owner (the creator) captured directly on the row for fast
        lookup. Full role info lives in OrganizationMemberRow — the owner
        also has a member row with role='owner'.
      * `slug` is globally unique and URL-safe — this is the only lookup
        key beyond id. Surfaced in `/workspaces/{slug}` URLs.
      * `description` is optional freeform. Not rendered in index yet;
        only shown on the detail page.

    Out of scope for v1 (flag at service layer):
      * Authority delegation to members (viewer tier scoping).
      * Workspace-scoped KB or routing.
      * SSO, billing, email verification.
      * Cross-org project moves.
    """

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )



class OrganizationMemberRow(Base):
    """Explicit workspace ↔ user join.

    Role taxonomy (v1):
      * `owner`  — created the workspace, or promoted later. Can manage
                   members, update roles, and attach projects. At least
                   one owner must always remain.
      * `admin`  — can invite members and attach projects. Cannot alter
                   ownership or remove owners.
      * `member` — default tier for invitees. Can see the workspace and
                   attached projects; cannot invite.
      * `viewer` — read-only observer. v1 stores the role but
                   workspace-scoped read-only enforcement lands in v2
                   (flagged as out of scope).

    Uniqueness: one role row per (org_id, user_id) so promotions mutate
    the existing row rather than stacking.
    """

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", name="uq_organization_member"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    invited_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

class OnboardingStateRow(Base):
    """Phase 1.B — ambient onboarding per (user, project).

    One row is created the first time a member visits `/projects/[id]`.
    The sub-agent-narrated walkthrough is rendered as a full-viewport
    overlay until the user either completes the 5-step sequence or
    dismisses it. Both outcomes persist so we never re-show it.

    `last_checkpoint` values track the 5 narrated sections (in order)
    plus the terminal states:
        'not_started' — row just created, overlay will open at step 1
        'vision'      — user advanced past the vision section
        'decisions'   — past the recent-decisions section
        'teammates'   — past the adjacent-teammates section
        'your_tasks'  — past the active-tasks section
        'open_risks'  — past the open-risks section (final step)
        'completed'   — user hit 'Done' — sets walkthrough_completed_at

    `dismissed=True` with completed_at still null is the 'Skip for now'
    outcome — the user doesn't want the overlay, but we didn't pretend
    they finished it. `/settings/profile > Replay onboarding` resets
    `last_checkpoint='not_started'` + `dismissed=False` so the overlay
    reopens on the next `/projects/[id]` visit.

    `walkthrough_json` caches the structured script produced by
    OnboardingService.build_walkthrough(). Cached per-row; regenerated
    on replay or when the cached copy is older than 24h. This lets
    re-visits during a single session skip the slice-build + narration
    cost.
    """

    __tablename__ = "onboarding_state"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "project_id", name="uq_onboarding_user_project"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    walkthrough_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    walkthrough_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_checkpoint: Mapped[str] = mapped_column(
        String(24), default="not_started"
    )
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    walkthrough_json: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )
    walkthrough_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )



class EventRow(Base):
    """Internal domain event audit log.

    This is the staging ground for Inngest adoption at Phase 12 (decision 1A):
    every row here becomes an Inngest event when the adapter is swapped in.
    """

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    # Denormalized so the SSE stream can filter without JSON path queries.
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ---- Phase 7' — mock auth ------------------------------------------------



class AgentRunLogRow(Base):
    """Per-LLM-call observability row (decision 2C2).

    One row per agent invocation, regardless of outcome (ok | retry |
    manual_review). Powers eval drift dashboards, cost tracing, and
    prompt-version comparisons.
    """

    __tablename__ = "agent_run_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent: Mapped[str] = mapped_column(String(64), index=True)
    prompt_version: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    attempts: Mapped[int] = mapped_column(default=1)
    latency_ms: Mapped[int] = mapped_column(default=0)
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    cache_read_tokens: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)



class IntakeEventRow(Base):
    __tablename__ = "intake_events"
    __table_args__ = (
        UniqueConstraint("source", "source_event_id", name="uq_intake_source_event"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    source_event_id: Mapped[str] = mapped_column(String(128))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


