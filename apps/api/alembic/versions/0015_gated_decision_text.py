"""gated decision_text — capture the user's raw utterance next to the
agent's framing on a gated proposal.

Revision ID: 0015_gated_decision_text
Revises: 0014_gated_decisions
Create Date: 2026-04-24

v0.5 polish. `gated_proposals.proposal_body` already stores the edge
agent's paraphrase of the decision; adding `decision_text` stores the
raw text the proposer actually typed, so the gate-keeper sees what
the human committed to — not just what the LLM heard. Nullable: old
rows + legacy callers that don't supply it read back NULL.

Additive only. Reversible (drop column on downgrade).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0015_gated_decision_text"
down_revision: str | Sequence[str] | None = "0014_gated_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("gated_proposals") as batch:
        batch.add_column(
            sa.Column("decision_text", sa.String(length=4000), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("gated_proposals") as batch:
        batch.drop_column("decision_text")
