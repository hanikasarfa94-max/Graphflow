from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


class RequirementRow(Base):
    """Versioned requirement. v1 from intake; each clarify-reply yields v2+.

    Versions are additive — old rows are never mutated, so event history
    stays intact.
    """

    __tablename__ = "requirements"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_requirement_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    raw_text: Mapped[str] = mapped_column(String)
    parsed_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parse_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Migration 0025 — declared budget for the requirement, in hours.
    # Nullable because most v1 intakes don't carry an explicit budget;
    # when set, MembraneService._review_task_promote uses it for the
    # estimate-overflow advisory check during personal→plan promotion.
    # Surfaced via the requirement-edit UI; LLM intake never writes it
    # (intake parses scope, not capacity — that's a separate decision).
    budget_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    parsed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    project: Mapped[ProjectRow] = relationship(back_populates="requirements")
    clarifications: Mapped[list[ClarificationQuestionRow]] = relationship(
        back_populates="requirement",
        cascade="all, delete-orphan",
        order_by="ClarificationQuestionRow.position",
    )


class ClarificationQuestionRow(Base):
    """One focused clarification question attached to a requirement version.

    `answer` is null until the user replies. The transition away from the
    Clarification stage is driven by a graph query (all answers present)
    per decision 1E — there is no `current_stage` write.
    """

    __tablename__ = "clarification_questions"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id", "position", name="uq_clarification_position"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(String)
    answer: Mapped[str | None] = mapped_column(String, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    requirement: Mapped[RequirementRow] = relationship(back_populates="clarifications")


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


class _GraphEntityBase:
    """Shared column shape for Goal/Deliverable/Constraint/Risk rows.

    Every graph entity is:
      - scoped to a project (CASCADE with project)
      - bound to a specific requirement version (CASCADE with requirement)
      - ordered within its kind via sort_order
      - carries a status string (default "open") so later phases (planning,
        QA, delivery) can mutate lifecycle without creating parallel tables

    Per decision 1E: there is no stage column. The presence of these rows
    and their status IS the project stage. See stage.project_stage().
    """

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class GoalRow(_GraphEntityBase, Base):
    __tablename__ = "graph_goals"
    __table_args__ = (
        UniqueConstraint("requirement_id", "sort_order", name="uq_goal_order"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(String, default="")
    success_criteria: Mapped[list | None] = mapped_column(JSON, nullable=True)


class DeliverableRow(_GraphEntityBase, Base):
    __tablename__ = "graph_deliverables"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id", "sort_order", name="uq_deliverable_order"
        ),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    # feature | api | doc | report | other — see prompt-contracts §6.3.
    kind: Mapped[str] = mapped_column(String(32), default="feature")


class ConstraintRow(_GraphEntityBase, Base):
    __tablename__ = "graph_constraints"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id", "sort_order", name="uq_constraint_order"
        ),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    # deadline | scope | resource | technical | permission | other.
    kind: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String(16), default="medium")


class RiskRow(_GraphEntityBase, Base):
    __tablename__ = "graph_risks"
    __table_args__ = (
        UniqueConstraint("requirement_id", "sort_order", name="uq_risk_order"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(String, default="")
    severity: Mapped[str] = mapped_column(String(16), default="medium")


class TaskRow(_GraphEntityBase, Base):
    """Planning-produced task on the latest requirement version.

    Shares _GraphEntityBase with Phase-5 entities so status/sort_order/created_at
    live in one place. `deliverable_id` is nullable because cross-cutting tasks
    (e.g. "set up OTP service") may not map cleanly to a single Deliverable.

    Per decision 1E, a project's `stage` becomes "planned" when any TaskRow
    exists for the latest requirement version — no column flip.
    """

    __tablename__ = "plan_tasks"
    __table_args__ = (
        UniqueConstraint("requirement_id", "sort_order", name="uq_task_order"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Migration 0021 — nullable for personal-scope tasks (self-set
    # to-dos that don't hang off a Requirement until promoted).
    requirement_id: Mapped[str | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    deliverable_id: Mapped[str | None] = mapped_column(
        ForeignKey("graph_deliverables.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(String, default="")
    # pm | frontend | backend | qa | design | business | approver | unknown —
    # matches ClarificationQuestion.target_role so a later auto-routing layer
    # can reuse the enum.
    assignee_role: Mapped[str] = mapped_column(String(32), default="unknown")
    estimate_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acceptance_criteria: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Migration 0021 — personal vs plan. Mirrors the kb_items split.
    # 'personal' = self-set to-do, owner_user_id-only visibility,
    # not in the canonical group plan. 'plan' = LLM-produced or
    # promoted, visible to all members. Default 'plan' preserves
    # backward compatibility for existing rows.
    scope: Mapped[str] = mapped_column(
        String(16), default="plan", server_default="plan"
    )
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class TaskDependencyRow(Base):
    """Directed edge in the task DAG: from_task must complete before to_task.

    Scoped to `requirement_id` so v+1 rebuilds get their own fresh edge set
    instead of colliding with v1's. PlanningService rejects cycles at persist
    time — there is no auto-breaking.
    """

    __tablename__ = "plan_task_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id",
            "from_task_id",
            "to_task_id",
            name="uq_task_dep_edge",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    from_task_id: Mapped[str] = mapped_column(
        ForeignKey("plan_tasks.id", ondelete="CASCADE"), index=True
    )
    to_task_id: Mapped[str] = mapped_column(
        ForeignKey("plan_tasks.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MilestoneRow(_GraphEntityBase, Base):
    __tablename__ = "plan_milestones"
    __table_args__ = (
        UniqueConstraint("requirement_id", "sort_order", name="uq_milestone_order"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    # Same free-form format as Requirement.deadline; the Planning Agent is
    # not responsible for calendar normalization.
    target_date: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # JSON list[str] of related TaskRow.id — kept denormalized so planning
    # consumers don't need a join table for a read-mostly view.
    related_task_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)


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


class AssignmentRow(Base):
    """Task ↔ User assignment. Unassign writes active=False + resolved_at."""

    __tablename__ = "assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("plan_tasks.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class TaskStatusUpdateRow(Base):
    """Migration 0018 — append-only audit log for task status changes.

    The TaskRow itself carries the *current* status; this table is the
    history. Every owner-initiated `update_status` call writes one row.
    Used by the perf surface to compute "tasks completed in 30d" and
    by the task detail UI to show progress narrative ("set to
    in_progress 3d ago, marked done 1h ago").

    `actor_user_id` is the assignee or project-owner who made the
    transition. `note` is the optional progress text the user typed
    when transitioning (especially useful on done — "shipped to staging,
    waiting on QA").
    """

    __tablename__ = "task_status_updates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("plan_tasks.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    old_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class TaskScoreRow(Base):
    """Migration 0018 — leader's quality score on a completed task.

    For off-platform work (Unity edits, design reviews, code commits)
    the platform can't auto-detect quality. Owner marks task done →
    project owner scores it → the score feeds perf_aggregation.

    Unique on (task_id, assignee_user_id): one score per
    (task, person-who-did-it). The reviewer can edit their verdict
    until the project moves on (no re-score after task is canceled).
    """

    __tablename__ = "task_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("plan_tasks.id", ondelete="CASCADE"), index=True
    )
    reviewer_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    assignee_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    quality: Mapped[str] = mapped_column(String(16))
    feedback: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "task_id", "assignee_user_id", name="uq_task_score_assignee"
        ),
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


class MessageRow(Base):
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


class DecisionRow(Base):
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


class StreamRow(Base):
    """Unifying conversation container.

    Types in v1 (post-Phase L):
      * 'project'  — team room, one per project, all project members
      * 'personal' — private (user ↔ their edge-agent), project-anchored,
                     owner_user_id set; primary surface per north-star
                     §"Sub-agent and routing architecture"
      * 'dm'       — 1:1 between two users, no project anchor

    `last_activity_at` is bumped on every new message so GET /api/streams
    can order by recency without scanning messages.

    `owner_user_id` is populated only for personal streams (the human who
    owns the sub-agent conversation). Null for project / dm.
    """

    __tablename__ = "streams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # 'project' | 'personal' | 'dm' in v1. 'group' + 'rehearsal' come in v2.
    type: Mapped[str] = mapped_column(String(16))
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Phase L: owner of a personal stream (user whose sub-agent converses
    # here). Null for type in {'project', 'dm'}.
    owner_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
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


class StatusTransitionRow(Base):
    """Graph-entity status mutation log — Sprint 1b time-cursor.

    Every status flip on a graph entity (task / risk / deliverable / goal /
    milestone / constraint / decision) writes one row here. The graph-at-ts
    endpoint replays the log to reconstruct historical status: for each
    entity, the last transition with `changed_at <= ts` determines its
    status at `ts`; if no transition exists, the entity's `created_at`
    status (usually "open") is assumed.

    Why a dedicated table rather than repurposing EventRow:
      * EventRow payloads are JSON — filtering by (entity_id, changed_at)
        requires a JSON-path scan that's slow on SQLite and brittle across
        the many event names we already emit.
      * A typed, indexed table matches the replay query shape exactly
        (project_id + changed_at range) and keeps the hot path cheap.

    v1 has no backfill of historical transitions — we record from this
    commit forward only. For seeded demo data, entities appear in the
    graph at their `created_at`; their status just won't change until the
    first real transition happens (which is fine for the "scrub back to
    BEFORE Legal flagged compliance" demo story).

    `old_status` may be null if the caller can't cheaply read the prior
    value (or if this is a creation-style transition). `new_status` is
    always populated. `changed_by_user_id` is null for system-driven
    transitions (agent-applied decisions, IM auto-apply).
    """

    __tablename__ = "status_transitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # 'task' | 'risk' | 'deliverable' | 'goal' | 'milestone' | 'constraint'
    # | 'decision' — matches the NodeKind enum on the web side plus the
    # extras (milestone, constraint) that live only in the tabular views.
    entity_kind: Mapped[str] = mapped_column(String(16), index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    old_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_status: Mapped[str] = mapped_column(String(32))
    changed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Indexed because the replay query filters by (project_id, changed_at)
    # range. Defaults to _utcnow so callers can omit it.
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


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


class KbItemRow(Base):
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

    Scope semantics (user-authored only — ingests don't have scope):
      * 'personal' — visible only to owner_user_id. The edge LLM uses
        these as private pretext for that user's sub-agent ONLY. Never
        bleeds into other members' contexts. Default scope on create.
      * 'group'    — shared with all project members. LLM uses for
        everyone. Promoted from personal via an explicit owner action
        (Phase V.1) or LLM-mediated route (Phase V.2). Group items
        affect everyone's pretext, so the promotion flow gates carefully.

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
