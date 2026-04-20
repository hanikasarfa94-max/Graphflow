"""status_transitions — Sprint 1b (time-cursor).

Revision ID: 0002_status_transitions
Revises: 0001_baseline
Create Date: 2026-04-20

Adds the `status_transitions` table. Every status mutation on task /
deliverable / risk / goal / milestone / decision writes a row here so
the time-cursor endpoint can reconstruct graph state at any past
timestamp via `select(...) where changed_at <= ts`.

See packages/persistence/src/workgraph_persistence/orm.py:StatusTransitionRow
for the authoritative column list.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_status_transitions"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "status_transitions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("entity_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("entity_kind", sa.String(length=32), nullable=False),
        sa.Column("old_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column(
            "changed_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column("trace_id", sa.String(length=64), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_table("status_transitions")
