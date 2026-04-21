"""license_audit — Phase 1.A cross-license reply audit log.

Revision ID: 0006_license_audit
Revises: 0005_handoff_records
Create Date: 2026-04-21

See packages/persistence/src/workgraph_persistence/orm.py:LicenseAuditRow
for the authoritative column list. Additive only — no table drops or
renames. Old rows from pre-v2 don't exist (new table); the dev bootstrap
creates the table via create_all before stamp on greenfield DBs.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_license_audit"
down_revision: str | Sequence[str] | None = "0005_handoff_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "license_audit",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source_user_id", sa.String(length=36), nullable=False, index=True
        ),
        sa.Column(
            "target_user_id", sa.String(length=36), nullable=False, index=True
        ),
        sa.Column(
            "signal_id", sa.String(length=36), nullable=True, index=True
        ),
        sa.Column(
            "referenced_node_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "out_of_view_node_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "outcome",
            sa.String(length=16),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "effective_tier",
            sa.String(length=16),
            nullable=False,
            server_default="full",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("license_audit")
