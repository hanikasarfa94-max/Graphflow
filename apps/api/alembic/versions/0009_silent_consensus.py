"""silent_consensus — Phase 1.A behavioral-agreement proposals.

Revision ID: 0009_silent_consensus
Revises: 0008_scrimmage
Create Date: 2026-04-22

See packages/persistence/src/workgraph_persistence/orm.py:SilentConsensusRow
for the authoritative column list. Additive only — new table, no renames
or drops. Chains off 0008_scrimmage.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_silent_consensus"
down_revision: str | Sequence[str] | None = "0008_scrimmage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "silent_consensus",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("topic_text", sa.String(length=500), nullable=False),
        sa.Column(
            "supporting_action_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "inferred_decision_summary",
            sa.String(length=4000),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "member_user_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
            index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ratified_decision_id",
            sa.String(length=36),
            sa.ForeignKey("decisions.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "ratified_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_table("silent_consensus")
