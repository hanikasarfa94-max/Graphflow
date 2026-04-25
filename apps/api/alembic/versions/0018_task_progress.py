"""task progress — Phase U: status audit + leader scoring.

Revision ID: 0018_task_progress
Revises: 0017_organizations
Create Date: 2026-04-25

Two new tables. Both additive; no changes to existing rows.

  * task_status_updates — append-only log. Every owner-initiated
    status transition writes one row. Used by perf aggregation
    ("tasks completed in 30d") + the task detail timeline.

  * task_scores — leader's quality verdict on a completed task. One
    score per (task, assignee). `quality ∈ {good, ok, needs_work}`.
    Reviewer can update their verdict (upsert keyed on the unique
    constraint).

The TaskRow itself keeps carrying the *current* status field; this
migration doesn't touch it. The new tables are pure history + scoring.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0018_task_progress"
down_revision: str | Sequence[str] | None = "0017_organizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_status_updates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(length=36),
            sa.ForeignKey("plan_tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "actor_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("old_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "task_scores",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(length=36),
            sa.ForeignKey("plan_tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "reviewer_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "assignee_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("quality", sa.String(length=16), nullable=False),
        sa.Column("feedback", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "task_id", "assignee_user_id", name="uq_task_score_assignee"
        ),
    )


def downgrade() -> None:
    op.drop_table("task_scores")
    op.drop_table("task_status_updates")
