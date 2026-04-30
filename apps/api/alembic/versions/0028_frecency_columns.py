"""last_accessed_at + access_count — N-Next §7.4 frecency primitives.

Revision ID: 0028_frecency_columns
Revises: 0027_decision_scope_stream
Create Date: 2026-04-29

Per PLAN-Next.md §N.1.5 + the test report's Path B recommendation:
add frecency columns to all five node-bearing row types so the §7.4
ranker can score `log(1 + access_count) × time_decay(now -
last_accessed_at)` and the LLM prompt can show "fresh-but-old-cited"
items as more relevant than "new-but-untouched" ones.

Tables touched:
  * messages
  * decisions
  * kb_items
  * plan_tasks
  * graph_risks

For each:
  - add `last_accessed_at` (DateTime tz, nullable initially)
  - add `access_count` (Integer NOT NULL DEFAULT 0)
  - backfill `last_accessed_at = created_at` on existing rows
  - flip `last_accessed_at` to NOT NULL after the backfill

Bump-on-touch hooks land in a follow-up commit. This migration is
just the column-shape; existing INSERT paths (which don't set
`last_accessed_at`) work because the ORM default fills it at
INSERT time. Migration is reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0028_frecency_columns"
down_revision: str | Sequence[str] | None = "0027_decision_scope_stream"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES: tuple[str, ...] = (
    "messages",
    "decisions",
    "kb_items",
    "plan_tasks",
    "graph_risks",
)


def upgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "last_accessed_at",
                    sa.DateTime(timezone=True),
                    nullable=True,
                )
            )
            batch_op.add_column(
                sa.Column(
                    "access_count",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
        # Backfill last_accessed_at from created_at for every existing row.
        # On a freshly-created row the ORM default fills it at INSERT time,
        # so this is only meaningful for rows that pre-date the migration.
        op.execute(
            sa.text(
                f"UPDATE {table} SET last_accessed_at = created_at "
                f"WHERE last_accessed_at IS NULL"
            )
        )
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "last_accessed_at",
                existing_type=sa.DateTime(timezone=True),
                nullable=False,
            )


def downgrade() -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("access_count")
            batch_op.drop_column("last_accessed_at")
