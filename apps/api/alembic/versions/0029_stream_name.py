"""StreamRow.name — persisted display name for room streams.

Revision ID: 0029_stream_name
Revises: 0028_frecency_columns
Create Date: 2026-04-30

Per the room-stream slice (one canonical entity, multiple projections):
the room view, room nav, and DecisionCard vote-scope explainer all
need real room names. Today `create_room()` accepts a `name` parameter
but doesn't persist it — `_shape_stream()` and `list_rooms_for_project`
return rows without a name field. The frontend would render unnamed
streams.

Adds `name` column (String(200), nullable). Nullable because non-room
stream types ('project', 'personal', 'dm') don't carry an explicit
name — they derive their display from the project / owner / DM
partner. Reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0029_stream_name"
down_revision: str | Sequence[str] | None = "0028_frecency_columns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("streams") as batch_op:
        batch_op.add_column(
            sa.Column("name", sa.String(length=200), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("streams") as batch_op:
        batch_op.drop_column("name")
