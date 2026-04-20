"""commitments — Sprint 2a (thesis-commit primitive).

Revision ID: 0003_commitments
Revises: 0002_status_transitions
Create Date: 2026-04-20

First-class promise-to-a-future-state, distinct from DecisionRow.
See packages/persistence/src/workgraph_persistence/orm.py:CommitmentRow
for the authoritative column list. SLA columns land in 0004.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_commitments"
down_revision: str | Sequence[str] | None = "0002_status_transitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commitments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "owner_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("headline", sa.String(length=500), nullable=False),
        sa.Column(
            "target_date",
            sa.DateTime(timezone=True),
            nullable=True,
            index=True,
        ),
        sa.Column("metric", sa.String(length=500), nullable=True),
        sa.Column("scope_ref_kind", sa.String(length=32), nullable=True),
        sa.Column(
            "scope_ref_id",
            sa.String(length=36),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="open",
            index=True,
        ),
        sa.Column(
            "source_message_id",
            sa.String(length=36),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("commitments")
