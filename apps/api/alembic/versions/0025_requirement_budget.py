"""requirements.budget_hours — Stage 6 budget overflow check.

Revision ID: 0025_requirement_budget
Revises: 0024_drop_membrane_signals
Create Date: 2026-04-26

Adds a nullable `budget_hours` column on requirements so the membrane's
task_promote review can do an advisory estimate-overflow check during
personal→plan promotion.

Reads of the column are null-safe — pre-existing requirements have
NULL and the membrane skips the check for them. New requirements can
set the budget through the requirement edit UI; LLM intake never writes
this field (intake parses scope, not capacity).

Reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0025_requirement_budget"
down_revision: str | Sequence[str] | None = "0024_drop_membrane_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "requirements",
        sa.Column("budget_hours", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("requirements", "budget_hours")
