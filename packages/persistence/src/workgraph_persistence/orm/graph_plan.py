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



class RiskRow(_GraphEntityBase, _FrecencyColumnsMixin, Base):
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



class TaskRow(_GraphEntityBase, _FrecencyColumnsMixin, Base):
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
        # M6: personal-task list filters by (project_id, scope, owner_user_id).
        Index("ix_plan_tasks_project_scope_owner", "project_id", "scope", "owner_user_id"),
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
    __table_args__ = (
        # M6: graph-at-timestamp replay filters by (project_id, changed_at) range.
        Index("ix_status_transitions_project_changed", "project_id", "changed_at"),
    )

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


