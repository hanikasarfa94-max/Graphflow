"""plan_tasks personal-scope columns — Phase T.

Revision ID: 0021_personal_tasks
Revises: 0020_kb_attachments
Create Date: 2026-04-25

Mirrors the kb_items personal/group split for tasks. A user can now
write a self-set personal task without going through the planning
agent or attaching to a Plan; promoting to the canonical group plan
goes through MembraneService.review (same gate as group-scope KB
writes).

Three additive changes, plus one nullability relaxation:

  * scope            VARCHAR(16) NOT NULL DEFAULT 'plan'
                     Existing rows are 'plan' (planning-agent
                     produced); manual creates default to 'personal'.
  * owner_user_id    VARCHAR(36) NULL  (FK users.id ON DELETE SET NULL)
                     The proposer of a personal task. Null on
                     LLM-produced plan tasks (no single owner).
  * source_message_id VARCHAR(36) NULL (FK messages.id ON DELETE SET NULL)
                     Link a task back to the chat message it was
                     proposed from (analog of source_suggestion_id
                     on decisions).
  * requirement_id   nullable: was NOT NULL because every plan task
                     hangs off the latest Requirement. Personal
                     tasks have no Requirement until promoted.

Backward-compatible: existing rows keep requirement_id set + scope
defaults to 'plan'. The UniqueConstraint on (requirement_id,
sort_order) tolerates NULL requirement_id rows since SQLite +
PostgreSQL both treat NULLs as distinct in unique indexes.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0021_personal_tasks"
down_revision: str | Sequence[str] | None = "0020_kb_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("plan_tasks") as batch:
        batch.add_column(
            sa.Column(
                "scope",
                sa.String(length=16),
                nullable=False,
                server_default="plan",
            )
        )
        batch.add_column(
            sa.Column(
                "owner_user_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "source_message_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch.alter_column(
            "requirement_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("plan_tasks") as batch:
        batch.alter_column(
            "requirement_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batch.drop_column("source_message_id")
        batch.drop_column("owner_user_id")
        batch.drop_column("scope")
