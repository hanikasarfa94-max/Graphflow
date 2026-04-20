"""commitment SLA columns — Sprint 2b (escalation ladder).

Revision ID: 0004_commitment_sla
Revises: 0003_commitments
Create Date: 2026-04-20

Adds `sla_window_seconds` + `sla_last_escalated_at` to commitments.
SlaService uses these to decide DUE-SOON / OVERDUE bands on every
graph event and to throttle re-escalation.

Additive, nullable — safe to apply on prod with existing rows.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_commitment_sla"
down_revision: str | Sequence[str] | None = "0003_commitments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite needs batch mode to add columns. render_as_batch is on in
    # env.py for the sqlite dialect; on postgres ALTER TABLE works
    # directly and batch falls through to a no-op wrapper.
    with op.batch_alter_table("commitments") as batch:
        batch.add_column(
            sa.Column("sla_window_seconds", sa.Integer(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "sla_last_escalated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("commitments") as batch:
        batch.drop_column("sla_last_escalated_at")
        batch.drop_column("sla_window_seconds")
