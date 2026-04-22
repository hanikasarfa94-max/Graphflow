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
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("requirements.id", ondelete="CASCADE"), index=True
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
      * 'text'            — default human / edge turn (body is the payload)
      * 'routed-inbound'  — target's personal stream received a routing ask
      * 'routed-reply'    — source's personal stream received the reply
      * 'routed-dm-log'   — DM mirror summary of a routed flow
    `linked_id` points at `routed_signals.id` when kind starts with 'routed-'.
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


class MembraneSignalRow(Base):
    """Phase D — external signal ingested through a project's membrane.

    Vision §5.12 (Membranes): external content (git commits/PRs, steam
    reviews, rss posts, webhooks, user-dropped links) flows through a
    security-gated classification pipeline before it can influence routing
    or trigger any graph activity.

    `status` lifecycle:
      * `pending-review` — default on ingest; MembraneAgent hasn't written
        its classification yet, or the classifier flagged the content for
        human review.
      * `approved` — human approver cleared a flagged signal.
      * `rejected` — human approver rejected the signal. It stays on the
        audit log but is never routed.
      * `routed` — auto-approved (confidence ≥ 0.7, no injection flag) and
        the service has posted membrane-signal messages into each proposed
        target's personal stream.

    Dedup key is (project_id, source_identifier). Re-ingesting the same
    URL / commit hash / forum post returns the existing row. `raw_content`
    is trimmed at ingest to the first 4000 chars — the LLM prompt never
    sees unbounded external text, which is the first injection guardrail.
    """

    __tablename__ = "membrane_signals"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "source_identifier", name="uq_membrane_signal_source"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Nullable because vision §5.12 allows org-level signals that don't
    # attach to a single project. v1 always sets project_id; the nullable
    # schema keeps v2 org-level ingestion non-breaking.
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # 'git-commit' | 'git-pr' | 'steam-review' | 'steam-forum' | 'rss'
    # | 'user-drop' | 'webhook'
    source_kind: Mapped[str] = mapped_column(String(32), index=True)
    # URL, commit hash, forum post id — whatever the source uses to
    # uniquely identify the artifact. Paired with project_id for dedup.
    source_identifier: Mapped[str] = mapped_column(String(512))
    # Trimmed to first 4000 chars at ingest — keeps prompt cost bounded
    # AND limits the surface area for prompt-injection. See vision §5.12.
    raw_content: Mapped[str] = mapped_column(String)
    # Set when a project member drops a link; null for agent pulls /
    # webhook payloads. v1 only ingests via user-drop or simulated
    # webhook, so this is usually populated.
    ingested_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # MembraneAgent output shape (Pydantic dumps into here). Keys:
    #   is_relevant: bool
    #   tags: list[str]
    #   summary: str  (<=200 chars)
    #   proposed_target_user_ids: list[str]
    #   proposed_action: "route-to-members" | "ambient-log" | "flag-for-review"
    #   confidence: float (0-1)
    #   safety_notes: str
    classification_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # See class docstring for allowed values. Defaults to 'pending-review'
    # per vision §5.12 security boundary — NOTHING is routed until either
    # auto-approval (confidence threshold + no injection flag) or a human
    # admin approves it explicitly.
    status: Mapped[str] = mapped_column(
        String(16), default="pending-review", index=True
    )
    approved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


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
