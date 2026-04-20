"""baseline — the schema as of v1 (before Sprint 1b / 2a / 2b).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-04-20

The v1 schema was created via `Base.metadata.create_all()` out of
apps/api/src/workgraph_api/bootstrap.py with dev-SQLite drift detection.
Prod DBs that predate Alembic are `alembic stamp 0001_baseline` — that
tells Alembic "the existing tables already match this revision" without
re-creating them.

For a FRESH database (no tables yet), running `alembic upgrade head`
will still work because later migrations are idempotent CREATE TABLE
statements with IF NOT EXISTS semantics, and the dev bootstrap can
pre-populate via create_all before stamp.

No DDL here — intentional. This file exists as the anchor; real
schema mutations start in 0002.
"""
from __future__ import annotations

from collections.abc import Sequence


revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Intentional no-op. Existing v1 DBs are stamped here via
    `alembic stamp 0001_baseline` to mark them at parity with the
    pre-v2 schema."""
    pass


def downgrade() -> None:
    """Nothing to roll back — this is the anchor."""
    pass
