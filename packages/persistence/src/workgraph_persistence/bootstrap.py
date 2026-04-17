from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from .db import Base


async def create_all(engine: AsyncEngine) -> None:
    """Create all tables. Phase 2: used at app startup + in tests.

    Phase 5 replaces this with Alembic migrations when graph-state schema lands.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
