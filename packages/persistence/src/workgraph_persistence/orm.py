from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
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
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(256))
    password_salt: Mapped[str] = mapped_column(String(64))
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
    """Explicit project ↔ user join. Creator auto-joins at project create."""

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
    """Per-project IM message. Plain text or markdown, no attachments."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class IMSuggestionRow(Base):
    """AI-IM pre-processor output bound to a source message.

    kind ∈ {none, tag, decision, blocker}. `status` transitions from
    "pending" → "accepted" / "dismissed". Accepting a decision-kind triggers
    a graph mutation; blocker-kind opens a RiskRow.
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
    conflict_id: Mapped[str] = mapped_column(
        ForeignKey("conflicts.id", ondelete="CASCADE"), index=True
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
