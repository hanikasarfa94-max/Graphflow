"""Drop membrane_signals — Stage F5 of the fold.

Revision ID: 0024_drop_membrane_signals
Revises: 0023_backfill_signals_to_kb
Create Date: 2026-04-26

Final stage of the fold. Pre-conditions (must hold before applying):
  * F2 backfill (0023) ran — every membrane_signals row has a kb_items
    mirror at the same id. Verified by SELECT count parity in prod
    smoke test before deploy.
  * F3 write cutover landed — MembraneSignalRepository's surface now
    operates on kb_items rows; nothing writes to membrane_signals.
  * F4 read cutover landed — KbHierarchyService.get_tree and
    SkillsService._kb_search read kb_items only; no live readers
    touch the legacy table.

Effect: drop the index, drop the table. The MembraneSignalRow ORM class
is removed in the same change-set so create_all (dev/test bootstrap)
no longer recreates the table.

Reversible: downgrade recreates the empty table + index. The data is
NOT restored — the kb_items rows that mirror it remain authoritative.
A downgrade past F5 is therefore a schema-shape rollback, not a data
rollback. To restore data: re-run F2 backfill in reverse direction
(custom script — not provided since post-F3 the legacy table is
empty by definition).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0024_drop_membrane_signals"
down_revision: str | Sequence[str] | None = "0023_backfill_signals_to_kb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Repoint the kb_item_licenses.item_id FK from membrane_signals →
    # kb_items BEFORE dropping the source table. Ids are preserved
    # across the F2 backfill so every existing override row still
    # resolves to a real kb_items row.
    #
    # The original FK in 0013 was created without an explicit name, so
    # neither SQLite nor PostgreSQL has a stable handle to drop. We
    # rebuild kb_item_licenses by hand: stash the rows, drop, recreate
    # with the new FK target, restore. Cheap — the table holds at
    # most one row per overridden item, never bulk data.
    op.execute(
        "CREATE TEMPORARY TABLE _kb_item_licenses_stash AS "
        "SELECT * FROM kb_item_licenses"
    )
    op.drop_table("kb_item_licenses")
    op.create_table(
        "kb_item_licenses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "item_id",
            sa.String(length=36),
            sa.ForeignKey("kb_items.id", ondelete="CASCADE"),
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
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("item_id", name="uq_kb_item_license_item"),
    )
    op.execute(
        "INSERT INTO kb_item_licenses "
        "SELECT * FROM _kb_item_licenses_stash"
    )
    op.execute("DROP TABLE _kb_item_licenses_stash")

    # Drop the folder_id index added in 0013, then the table.
    op.drop_index("ix_membrane_signals_folder_id", table_name="membrane_signals")
    op.drop_table("membrane_signals")


def downgrade() -> None:
    # Recreate the table shape so anyone rolling back can re-apply the
    # historical migrations cleanly. Schema mirrors the v1 + 0011 +
    # 0013 shape this fold inherited.
    op.create_table(
        "membrane_signals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("source_kind", sa.String(length=32), nullable=False, index=True),
        sa.Column("source_identifier", sa.String(length=512), nullable=False),
        sa.Column("raw_content", sa.String(), nullable=False),
        sa.Column(
            "ingested_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "classification_json",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="pending-review",
            index=True,
        ),
        sa.Column(
            "approved_by_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("trace_id", sa.String(length=64), nullable=True, index=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "folder_id",
            sa.String(length=36),
            sa.ForeignKey("kb_folders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "project_id", "source_identifier", name="uq_membrane_signal_source"
        ),
    )
    op.create_index(
        "ix_membrane_signals_folder_id", "membrane_signals", ["folder_id"]
    )
    # Repoint kb_item_licenses.item_id back at membrane_signals via the
    # same stash-and-rebuild path used in upgrade().
    op.execute(
        "CREATE TEMPORARY TABLE _kb_item_licenses_stash AS "
        "SELECT * FROM kb_item_licenses"
    )
    op.drop_table("kb_item_licenses")
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
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("item_id", name="uq_kb_item_license_item"),
    )
    op.execute(
        "INSERT INTO kb_item_licenses "
        "SELECT * FROM _kb_item_licenses_stash"
    )
    op.execute("DROP TABLE _kb_item_licenses_stash")
