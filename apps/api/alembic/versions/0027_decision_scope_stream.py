"""decisions.scope_stream_id — smallest-relevant-vote routing.

Revision ID: 0027_decision_scope_stream
Revises: 0026_member_skill_tags
Create Date: 2026-04-29

Per new_concepts.md §6.11 + north-star Correction R.2: a decision's
vote scope defaults to the smallest relevant group (1:1 DM → 2 voters,
4-person room → 4 voters, cell-wide → all members). The Crystallization
Agent infers the smallest stream that contained the discussion and
stamps it here. NULL means "fall back to cell-wide vote" (legacy /
unscoped decisions).

Nullable + indexed; SET NULL on stream delete so a deleted room
doesn't cascade-destroy its decisions — they fall back to cell-wide.

Reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0027_decision_scope_stream"
down_revision: str | Sequence[str] | None = "0026_member_skill_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("decisions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "scope_stream_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_decisions_scope_stream",
            "streams",
            ["scope_stream_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_decisions_scope_stream_id",
            ["scope_stream_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("decisions") as batch_op:
        batch_op.drop_index("ix_decisions_scope_stream_id")
        batch_op.drop_constraint("fk_decisions_scope_stream", type_="foreignkey")
        batch_op.drop_column("scope_stream_id")
