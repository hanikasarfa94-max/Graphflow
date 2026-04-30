"""kb_items absorbs membrane_signals — Stage F1 of the fold.

Revision ID: 0022_kb_items_absorb_signals
Revises: 0021_personal_tasks
Create Date: 2026-04-26

The fold (docs/membrane-reorg.md follow-up): kb_items becomes the
single storage for both user-authored notes AND externally-ingested
signals, discriminated by `source` / `source_kind`. This migration is
purely additive — it widens kb_items to fit the signal shape without
touching membrane_signals or any read/write path. F2 backfills, F3
cuts writes, F4 cuts reads, F5 drops the old table.

Columns added (all nullable, all signal-shaped):
  * source_kind          — 'git-commit' | 'rss' | 'user-drop' | etc.
                           (overlaps `source` semantically; `source`
                           stays the broad bucket — manual/upload/llm/
                           ingest — and `source_kind` is the ingest
                           sub-type. `source_kind` is NULL for non-
                           ingests.)
  * source_identifier    — URL/commit-hash/post-id, dedup key. NULL
                           for manual/upload/llm.
  * raw_content          — pre-classification text (≤4000 chars at
                           ingest). NULL for non-ingests.
  * classification_json  — MembraneAgent output (is_relevant, tags,
                           summary, proposed_target_user_ids, etc.).
                           Defaults to '{}' so non-ingest reads don't
                           need a None-check.
  * ingested_by_user_id  — who dropped the link; NULL for webhook/
                           cron pulls and for non-ingests.
  * approved_by_user_id  — who cleared a flagged ingest. NULL until
                           approved (or never, for auto-routed).
  * approved_at          — timestamp of approval.
  * trace_id             — correlates with the IM message that
                           triggered the ingest, when applicable.

Nullability relaxations (so signals can sit in this table):
  * project_id           — was NOT NULL; signals allow org-level
                           ingests with no single project.
  * owner_user_id        — was NOT NULL; webhook payloads have no
                           human owner.

Status vocabulary widens at the app layer (VALID_STATUSES grows from
{draft, published, archived} to also include {pending-review,
approved, rejected, routed}) — no DB-level enum, the column is just
String(16). Documented in services/kb_items.py.

Dedup of (project_id, source_identifier) for ingests is enforced at
the app layer (KbItemRepository.upsert_ingest, F3). SQLite supports
partial unique indexes, but we keep the constraint app-level for
portability with PostgreSQL drivers that don't share the same syntax.

Reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0022_kb_items_absorb_signals"
down_revision: str | Sequence[str] | None = "0021_personal_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Native ADD COLUMN — works on SQLite for nullable columns and avoids
    # the table-recreate path inside batch_alter (which trips a column-
    # reorder CircularDependencyError when multiple FK columns are added
    # in one batch on SQLite ≥ 3.35 with SQLAlchemy 2.x).
    op.add_column(
        "kb_items",
        sa.Column("source_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "kb_items",
        sa.Column("source_identifier", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "kb_items",
        sa.Column("raw_content", sa.Text(), nullable=True),
    )
    op.add_column(
        "kb_items",
        sa.Column(
            "classification_json",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )
    # FK declared at ORM layer only (mirrors 0021_personal_tasks pattern).
    # SQLite's ALTER TABLE doesn't support adding FK constraints; the ORM
    # still describes the relationship for query-time joins.
    op.add_column(
        "kb_items",
        sa.Column("ingested_by_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "kb_items",
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "kb_items",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "kb_items",
        sa.Column("trace_id", sa.String(length=64), nullable=True),
    )

    # Nullability relaxation does need batch on SQLite (rewrites the table).
    # Isolated batch with just two alter_column calls — no column reorder
    # contention.
    with op.batch_alter_table("kb_items") as batch:
        batch.alter_column(
            "project_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )
        batch.alter_column(
            "owner_user_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )

    op.create_index(
        "ix_kb_items_source_kind", "kb_items", ["source_kind"]
    )
    op.create_index(
        "ix_kb_items_source_identifier",
        "kb_items",
        ["project_id", "source_identifier"],
    )
    op.create_index(
        "ix_kb_items_trace_id", "kb_items", ["trace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_kb_items_trace_id", table_name="kb_items")
    op.drop_index("ix_kb_items_source_identifier", table_name="kb_items")
    op.drop_index("ix_kb_items_source_kind", table_name="kb_items")
    with op.batch_alter_table("kb_items") as batch:
        batch.alter_column(
            "owner_user_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch.alter_column(
            "project_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
    op.drop_column("kb_items", "trace_id")
    op.drop_column("kb_items", "approved_at")
    op.drop_column("kb_items", "approved_by_user_id")
    op.drop_column("kb_items", "ingested_by_user_id")
    op.drop_column("kb_items", "classification_json")
    op.drop_column("kb_items", "raw_content")
    op.drop_column("kb_items", "source_identifier")
    op.drop_column("kb_items", "source_kind")
