"""scrimmages — Phase 2.B agent-vs-agent debate transcripts.

Revision ID: 0008_scrimmage
Revises: 0007_dissent
Create Date: 2026-04-21

Persists the 2–3 turn debate between two sub-agents that runs before
humans are involved in a routed question. See
packages/persistence/src/workgraph_persistence/orm.py:ScrimmageRow
for the authoritative column list. Additive only — new table, no
renames or drops.

Chains off 0007_dissent which is produced by the parallel Phase 2.A
PR (sibling agent). Order is 0006 → 0007 → 0008 at deploy time.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_scrimmage"
down_revision: str | Sequence[str] | None = "0007_dissent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scrimmages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "routed_signal_id",
            sa.String(length=36),
            sa.ForeignKey("routed_signals.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "source_user_id", sa.String(length=36), nullable=False, index=True
        ),
        sa.Column(
            "target_user_id", sa.String(length=36), nullable=False, index=True
        ),
        sa.Column("question_text", sa.String(length=4000), nullable=False),
        sa.Column(
            "transcript_json", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "outcome",
            sa.String(length=32),
            nullable=False,
            server_default="in_progress",
            index=True,
        ),
        sa.Column("proposal_json", sa.JSON(), nullable=True),
        sa.Column(
            "trace_id", sa.String(length=64), nullable=True, index=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("scrimmages")
