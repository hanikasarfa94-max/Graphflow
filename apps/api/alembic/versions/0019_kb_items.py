"""kb_items — Phase V: first-class user-authored KB notes.

Revision ID: 0019_kb_items
Revises: 0018_task_progress
Create Date: 2026-04-25

User-authored notes (manual write, file uploads, LLM-created on
behalf-of-user) get their own table. Distinct from membrane_signals
(which is for URL/RSS/web-search ingests). The wiki UI lists both.

Scope semantics:
  * personal — visible only to owner_user_id; LLM uses as private
    pretext for that user's sub-agent ONLY.
  * group    — shared with all project members; affects everyone's
    pretext. Promoted from personal via explicit owner action
    (Phase V.1) or LLM-mediated route (Phase V.2).

Additive only. Reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0019_kb_items"
down_revision: str | Sequence[str] | None = "0018_task_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kb_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "folder_id",
            sa.String(length=36),
            sa.ForeignKey("kb_folders.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "owner_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "scope", sa.String(length=16), nullable=False, server_default="personal", index=True
        ),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content_md", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="published",
        ),
        sa.Column(
            "source", sa.String(length=16), nullable=False, server_default="manual"
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
    )


def downgrade() -> None:
    op.drop_table("kb_items")
