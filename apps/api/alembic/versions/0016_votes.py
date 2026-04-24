"""voting — Phase S: votes as first-class graph nodes + gated_proposals.voter_pool.

Revision ID: 0016_votes
Revises: 0015_gated_decision_text
Create Date: 2026-04-24

Two additions, scoped to one feature:

1. `votes` table — polymorphic via (subject_kind, subject_id) so the
   primitive can extend to future vote targets without another
   migration. For now the only caller is GatedProposalService when a
   proposal is opened to multi-voter resolution; future work may let
   decisions, commitments, or drift alerts carry votes too.

   Contract highlights enforced by the schema:
     * One row per (subject_kind, subject_id, voter_user_id) — uniq index.
     * Absence of a row means the voter hasn't weighed in; verdict is
       never "pending" in the row itself.
     * No FK on subject_id — it's polymorphic; integrity is service-layer.

2. `gated_proposals.voter_pool` — nullable JSON list of voter user_ids,
   populated when a proposal transitions to 'in_vote' status. Threshold
   is derived on the fly: ceil(len(voter_pool)/2). NULL on all pre-
   Phase-S rows and on proposals that resolve single-approver without
   ever entering vote mode.

Additive only. Reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0016_votes"
down_revision: str | Sequence[str] | None = "0015_gated_decision_text"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("gated_proposals") as batch:
        batch.add_column(
            sa.Column("voter_pool", sa.JSON(), nullable=True)
        )
    op.create_table(
        "votes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("subject_kind", sa.String(length=32), nullable=False, index=True),
        sa.Column("subject_id", sa.String(length=36), nullable=False, index=True),
        sa.Column(
            "voter_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("rationale", sa.String(length=2000), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "subject_kind",
            "subject_id",
            "voter_user_id",
            name="uq_votes_subject_voter",
        ),
    )


def downgrade() -> None:
    op.drop_table("votes")
    with op.batch_alter_table("gated_proposals") as batch:
        batch.drop_column("voter_pool")
