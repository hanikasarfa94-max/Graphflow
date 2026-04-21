"""dissent — Phase 2.A dissent rows + judgment-accuracy validation.

Revision ID: 0007_dissent
Revises: 0006_license_audit
Create Date: 2026-04-21

See packages/persistence/src/workgraph_persistence/orm.py:DissentRow
for the authoritative column list. Additive only — no table drops or
renames. One dissent per (decision_id, dissenter_user_id); a second
write replaces the first (service layer upsert, not DB constraint, so
replays of the old row remain in EventRow history).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_dissent"
down_revision: str | Sequence[str] | None = "0006_license_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dissents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "decision_id",
            sa.String(length=36),
            sa.ForeignKey("decisions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "dissenter_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("stance_text", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        # Null until validated. 'supported' | 'refuted' | 'still_open'.
        sa.Column(
            "validated_by_outcome",
            sa.String(length=16),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "outcome_evidence_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.UniqueConstraint(
            "decision_id",
            "dissenter_user_id",
            name="uq_dissent_decision_user",
        ),
    )


def downgrade() -> None:
    op.drop_table("dissents")
