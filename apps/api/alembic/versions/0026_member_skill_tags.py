"""project_members.skill_tags — assignee coverage check.

Revision ID: 0026_member_skill_tags
Revises: 0025_requirement_budget
Create Date: 2026-04-26

Adds a JSON list column on project_members so members can declare
their functional skills (frontend / backend / qa / design / etc).
The membrane's task_promote review uses this to flag promotions of
tasks tagged role='backend' when no project member carries that tag.

Defaults to '[]' so existing rows keep working without a backfill.
Reads are null-safe via the ORM default=list.

Reversible.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0026_member_skill_tags"
down_revision: str | Sequence[str] | None = "0025_requirement_budget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_members",
        sa.Column(
            "skill_tags",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("project_members", "skill_tags")
