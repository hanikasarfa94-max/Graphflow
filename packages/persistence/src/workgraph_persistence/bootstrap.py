from __future__ import annotations

import logging
import os

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from .db import Base

_log = logging.getLogger("workgraph.persistence.bootstrap")


async def create_all(engine: AsyncEngine) -> None:
    """Create all tables. Phase 2: used at app startup + in tests.

    Drift handling: in dev (`WORKGRAPH_ENV != "prod"`), a schema
    mismatch — any ORM table missing a column the model declares —
    triggers a drop-and-recreate so the local SQLite stays usable
    without running migrations by hand. In prod we never drop: the
    fallback once silently wiped a live database when an Alembic
    migration hadn't run yet (post-mortem 2026-04-25). Prod relies
    on Alembic; if the schema is stale, log loudly and let the
    `OperationalError` surface so the operator runs the migration.
    """
    env = (os.environ.get("WORKGRAPH_ENV") or "dev").lower()
    is_prod = env == "prod"

    async with engine.begin() as conn:
        stale = await conn.run_sync(_schema_is_stale)
        if stale:
            if is_prod:
                _log.error(
                    "stale schema detected in prod — refusing to drop. "
                    "Run `alembic upgrade head` against the live DB."
                )
            else:
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
