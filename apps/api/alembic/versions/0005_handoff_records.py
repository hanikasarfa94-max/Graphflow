"""handoff_records — Stage 3 skill succession.

Revision ID: 0005_handoff_records
Revises: 0004_commitment_sla
Create Date: 2026-04-20

Persists the PII-stripped routine layer transferred from a departing
member to a successor. See packages/persistence/src/workgraph_persistence/
orm.py:HandoffRow for the authoritative column list and the contract
on which columns may/may not reach agent prompts.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_handoff_records"
down_revision: str | Sequence[str] | None = "0004_commitment_sla"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "handoff_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # No FK cascade — a finalized handoff is history and must
        # survive later user removals. Snapshotted display_name columns
        # keep the brief renderable.
        sa.Column(
            "from_user_id", sa.String(length=36), nullable=False, index=True
        ),
        sa.Column(
            "to_user_id", sa.String(length=36), nullable=False, index=True
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
            index=True,
        ),
        sa.Column(
            "role_skills_transferred",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "profile_skill_routines",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "brief_markdown",
            sa.String(length=8000),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "from_display_name",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "to_display_name",
            sa.String(length=200),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "finalized_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("handoff_records")
