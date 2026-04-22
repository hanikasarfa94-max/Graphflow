"""kb_hierarchy — Phase 3.A hierarchical KB (folders + per-item license).

Revision ID: 0013_kb_hierarchy
Revises: 0012_meeting_transcripts
Create Date: 2026-04-23

Flat KB → tree. Adds two tables and a nullable column on
`membrane_signals`:

  * `kb_folders` — one row per folder node. Roots have parent_folder_id
    NULL. Name uniqueness among siblings is enforced at the service
    layer (SQLite + NULL semantics make a partial UniqueConstraint
    unreliable across dialects).
  * `kb_item_licenses` — per-item tier override (one row per item_id).
    Missing row = inherit project tier via LicenseContextService.
  * `membrane_signals.folder_id` — nullable FK to kb_folders, filled
    during backfill.

Backfill plan (see services/kb_hierarchy.py ensure_backfill): create
a single root folder per existing project and sweep every existing
MembraneSignalRow into it. Idempotent — the service re-runs cheaply
and skips already-placed items. We deliberately keep backfill in the
service layer, not in this migration, so it stays safe on the prod
database where millions of signals could otherwise stall the deploy.

Additive only. Chains off 0012_meeting_transcripts.
Deploy order is 0011 → 0012 → 0013.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013_kb_hierarchy"
down_revision: str | Sequence[str] | None = "0012_meeting_transcripts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_folders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "parent_folder_id",
            sa.String(length=36),
            sa.ForeignKey("kb_folders.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    op.create_table(
        "kb_item_licenses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "item_id",
            sa.String(length=36),
            sa.ForeignKey("membrane_signals.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("license_tier", sa.String(length=16), nullable=False),
        sa.Column(
            "set_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.UniqueConstraint("item_id", name="uq_kb_item_license_item"),
    )
    # Batch-op so SQLite (no direct ALTER TABLE ADD COLUMN FK) works.
    with op.batch_alter_table("membrane_signals") as batch:
        batch.add_column(
            sa.Column(
                "folder_id",
                sa.String(length=36),
                sa.ForeignKey("kb_folders.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch.create_index(
            "ix_membrane_signals_folder_id",
            ["folder_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("membrane_signals") as batch:
        batch.drop_index("ix_membrane_signals_folder_id")
        batch.drop_column("folder_id")
    op.drop_table("kb_item_licenses")
    op.drop_table("kb_folders")
