"""onboarding_state — Phase 1.B ambient onboarding per (user, project).

Revision ID: 0010_onboarding_state
Revises: 0009_silent_consensus
Create Date: 2026-04-22

One row per (user, project) tracking whether the new-hire walkthrough
has been seen / completed / dismissed. `walkthrough_json` caches the
structured script so re-visits inside a 24h window skip the slice +
narration cost. See
packages/persistence/src/workgraph_persistence/orm.py:OnboardingStateRow
for the authoritative column list. Additive only — new table, no
renames or drops.

Chains off 0009_silent_consensus (the parallel Phase 1.A sibling).
Deploy order is 0008 → 0009 → 0010.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_onboarding_state"
down_revision: str | Sequence[str] | None = "0009_silent_consensus"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "onboarding_state",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "walkthrough_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "walkthrough_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_checkpoint",
            sa.String(length=24),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column(
            "dismissed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "walkthrough_json",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "walkthrough_generated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "user_id",
            "project_id",
            name="uq_onboarding_user_project",
        ),
    )


def downgrade() -> None:
    op.drop_table("onboarding_state")
