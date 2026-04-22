"""meeting_transcripts — Phase 2.B uploaded meeting transcripts.

Revision ID: 0012_meeting_transcripts
Revises: 0011_membrane_active
Create Date: 2026-04-22

One row per uploaded transcript. Metabolism status + extracted signals
are mutated in place as the background edge-LLM pass completes. See
packages/persistence/src/workgraph_persistence/orm.py:MeetingTranscriptRow
for the authoritative column list. Additive only — new table, no
renames or drops.

Chains off 0011_membrane_active (the parallel Phase 2.A sibling).
Deploy order is 0010 → 0011 → 0012.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0012_meeting_transcripts"
down_revision: str | Sequence[str] | None = "0011_membrane_active"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meeting_transcripts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "uploader_user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "title",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
        sa.Column("transcript_text", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "participant_user_ids",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "metabolism_status",
            sa.String(length=16),
            nullable=False,
            server_default="pending",
            index=True,
        ),
        sa.Column(
            "metabolism_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "metabolism_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "extracted_signals",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error_message", sa.String(length=2000), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("meeting_transcripts")
