"""membrane_active — Phase 2.A active membrane ingestion subscriptions.

Revision ID: 0011_membrane_active
Revises: 0010_onboarding_state
Create Date: 2026-04-21

Adds `membrane_subscriptions` for per-project RSS feeds + standing search
queries the active-scan cron uses. Signals still land in the existing
`membrane_signals` table via MembraneAgent.classify → status='proposed'
gate — nothing about this migration relaxes the vision §5.12 security
boundary. See
packages/persistence/src/workgraph_persistence/orm.py:MembraneSubscriptionRow
for the authoritative column list.

Additive only: one new table, no renames / drops. Chains off
0010_onboarding_state.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011_membrane_active"
down_revision: str | Sequence[str] | None = "0010_onboarding_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "membrane_subscriptions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("url_or_query", sa.String(length=1000), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "last_polled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("membrane_subscriptions")
