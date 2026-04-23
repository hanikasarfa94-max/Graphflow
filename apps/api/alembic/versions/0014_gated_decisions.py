"""gated_decisions — Scene 2 of routing: decisions requiring a gate-keeper's
sign-off before they can crystallize.

Revision ID: 0014_gated_decisions
Revises: 0013_kb_hierarchy
Create Date: 2026-04-23

Adds three things:

  * `projects.gate_keeper_map` — JSON map of `{decision_class: user_id}`.
    Each class (budget, legal, hire, scope_cut, …) either has a named
    gate-keeper or is absent (no gate applies). Empty map = project
    behaves pre-V4 (all decisions crystallize normally).

  * `decisions.decision_class` + `decisions.gated_via_proposal_id` —
    lineage columns. Non-gated decisions leave both NULL.

  * `gated_proposals` — new table. One row per pending / resolved
    proposal. `status` transitions pending → approved / denied /
    withdrawn. On approve, the service creates a DecisionRow whose
    `gated_via_proposal_id` points back here.

No cross-FK: the gated_proposals row does NOT point at the resolved
decision (avoids circular FK). Query the other direction via
`SELECT * FROM decisions WHERE gated_via_proposal_id = ?`.

Additive only. Chains off 0013_kb_hierarchy.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0014_gated_decisions"
down_revision: str | Sequence[str] | None = "0013_kb_hierarchy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gated_proposals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "proposer_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "gate_keeper_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("decision_class", sa.String(length=32), nullable=False),
        sa.Column("proposal_body", sa.String(length=4000), nullable=False),
        sa.Column("apply_actions", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "resolution_note",
            sa.String(length=2000),
            nullable=True,
        ),
        sa.Column(
            "trace_id",
            sa.String(length=64),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column(
                "gate_keeper_map",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            )
        )

    with op.batch_alter_table("decisions") as batch:
        batch.add_column(
            sa.Column(
                "decision_class",
                sa.String(length=32),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "gated_via_proposal_id",
                sa.String(length=36),
                sa.ForeignKey("gated_proposals.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch.create_index(
            "ix_decisions_gated_via_proposal_id",
            ["gated_via_proposal_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("decisions") as batch:
        batch.drop_index("ix_decisions_gated_via_proposal_id")
        batch.drop_column("gated_via_proposal_id")
        batch.drop_column("decision_class")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("gate_keeper_map")
    op.drop_table("gated_proposals")
