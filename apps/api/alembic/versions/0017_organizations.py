"""Organizations — minimum-viable Studio / Enterprise tier above project.

Revision ID: 0017_organizations
Revises: 0016_votes
Create Date: 2026-04-24

Adds the architectural tier the user flagged as missing — a container
above ProjectRow so authority distribution, "viewer vs new-employee"
permissioning, and multi-project housekeeping have a home.

v1 scope is deliberately tiny so we can ship in one agent run:

1. `organizations` table — id / name / slug / owner_user_id / description.
   * `slug` is UNIQUE so /workspaces/{slug} URLs are stable. Short (64)
     because this is a URL fragment, not freeform.
   * `owner_user_id` is SET NULL on delete so orphaned orgs don't
     cascade-destroy member / project data before a human can sort them
     out.
2. `organization_members` table — polymorphic on role (owner / admin /
   member / viewer) with a UNIQUE (organization_id, user_id). `role` is
   a short String so we don't need an enum migration dance later.
3. `projects.organization_id` — nullable FK. Existing projects stay
   unassigned (nullable + no default) so the migration is additive /
   reversible. When set, the project nests under a workspace.

Out of scope (flagged in the service layer):
  * Authority delegation from org to project.
  * Cross-org project moves.
  * Workspace-scoped routing, KB, or SSO.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0017_organizations"
down_revision: str | Sequence[str] | None = "0016_votes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "slug", sa.String(length=64), nullable=False, unique=True, index=True
        ),
        sa.Column(
            "owner_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("description", sa.String(length=4000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "organization_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "organization_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "invited_by_user_id",
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
        sa.UniqueConstraint(
            "organization_id",
            "user_id",
            name="uq_organization_member",
        ),
    )
    with op.batch_alter_table("projects") as batch:
        batch.add_column(
            sa.Column(
                "organization_id",
                sa.String(length=36),
                sa.ForeignKey("organizations.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("organization_id")
    op.drop_table("organization_members")
    op.drop_table("organizations")
