from __future__ import annotations

import logging

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from .db import Base

_log = logging.getLogger("workgraph.persistence.bootstrap")


async def create_all(engine: AsyncEngine) -> None:
    """Create all tables. Phase 2: used at app startup + in tests.

    Phase B (v2, no Alembic): on a dev SQLite file that predates a schema
    change (new column, new table), `create_all` alone leaves the stale
    columns in place and any ORM query against the schema-drifted table
    fails with `OperationalError: no such column: ...`. Per PLAN-v2
    "Dev SQLite init_schema drops + recreates", we detect a drift and
    drop-then-recreate the full schema. This is safe because dev SQLite
    holds nothing the user can't re-seed; prod uses Postgres + Alembic.
    """
    async with engine.begin() as conn:
        if await conn.run_sync(_schema_is_stale):
            _log.warning(
                "stale dev SQLite schema detected — dropping + recreating"
            )
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


def _schema_is_stale(sync_conn) -> bool:
    """True when any ORM-defined table already exists but is missing at
    least one column that the model declares. Returns False if no ORM
    tables exist yet (first boot) or if every existing table matches.
    """
    try:
        inspector = inspect(sync_conn)
        existing_tables = set(inspector.get_table_names())
    except Exception:
        return False
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue
        existing_cols = {
            c["name"] for c in inspector.get_columns(table_name)
        }
        expected_cols = {c.name for c in table.columns}
        if not expected_cols.issubset(existing_cols):
            return True
    return False


async def drop_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
