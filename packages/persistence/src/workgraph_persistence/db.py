from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def build_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    # aiosqlite needs check_same_thread off for our pool; other dialects ignore it.
    connect_args: dict = {}
    kwargs: dict = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        if ":memory:" in database_url:
            # In-memory SQLite gives EACH connection its own private database,
            # so the test harness must share ONE connection — otherwise the
            # default pool intermittently checks out a second, empty DB under
            # concurrency and a read misses a just-committed write (the systemic
            # test flake). StaticPool holds one shared connection, which the
            # harness (conftest _DrainingTransport, EventBus.drain) assumes.
            # Scoped to :memory: ONLY: file-based SQLite (dev/CI) keeps the
            # default pool — a file DB is shared across connections (no separate
            # empty-DB problem) and StaticPool would needlessly serialize all
            # access. Postgres (deploy target) keeps the default MVCC pool.
            kwargs["poolclass"] = StaticPool
    return create_async_engine(
        database_url, echo=echo, future=True, connect_args=connect_args, **kwargs
    )


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(
    maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    session = maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session(
    maker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_scope(maker) as session:
        yield session
