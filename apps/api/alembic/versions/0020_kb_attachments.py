"""kb_items.attachment_* columns — Phase V.B: file upload support.

Revision ID: 0020_kb_attachments
Revises: 0019_kb_items
Create Date: 2026-04-25

Three new nullable columns on `kb_items` so an item can carry a
file attachment alongside its markdown body. The bytes live on disk
under `WORKGRAPH_KB_UPLOADS_ROOT/<item_id>/<filename>` (default
`/data/kb-uploads`). We store the relative pieces, not the absolute
path, so the root can move without rewriting rows.

Additive only. Reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0020_kb_attachments"
down_revision: str | Sequence[str] | None = "0019_kb_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("kb_items") as batch:
        batch.add_column(
            sa.Column("attachment_filename", sa.String(length=500), nullable=True)
        )
        batch.add_column(
            sa.Column("attachment_mime", sa.String(length=120), nullable=True)
        )
        batch.add_column(
            sa.Column("attachment_bytes", sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("kb_items") as batch:
        batch.drop_column("attachment_bytes")
        batch.drop_column("attachment_mime")
        batch.drop_column("attachment_filename")
