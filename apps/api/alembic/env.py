"""Alembic migration runner for workgraph-api.

Sync-engine at migration time. The app runs on async (aiosqlite /
asyncpg) but migrations happen out-of-process during deploys, where
simple sync DBAPI is less surprising. We read the async URL from the
env and strip the async driver prefix to get a sync equivalent:

    sqlite+aiosqlite:///./data/workgraph.sqlite
      → sqlite:///./data/workgraph.sqlite

    postgresql+asyncpg://user:pass@host/db
      → postgresql+psycopg2://user:pass@host/db

target_metadata is sourced from workgraph_persistence.orm so
alembic's autogenerate stays accurate as new ORM models land.
"""
from __future__ import annotations

import os
import re
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool


# Make the workgraph_* packages importable. env.py runs from the
# apps/api directory; the packages live at ../../packages/*/src.
_repo_root = Path(__file__).resolve().parents[3]
for rel in (
    "packages/persistence/src",
    "packages/domain/src",
    "packages/schemas/src",
    "packages/observability/src",
    "apps/api/src",
):
    sys.path.insert(0, str(_repo_root / rel))

from workgraph_persistence.db import Base  # noqa: E402
import workgraph_persistence.orm  # noqa: E402,F401 — side-effect: registers all Rows on Base


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


_ASYNC_TO_SYNC_DRIVERS = {
    "aiosqlite": "pysqlite",  # SQLAlchemy's canonical sync sqlite driver
    "asyncpg": "psycopg2",
    "asyncmy": "pymysql",
}


def _resolve_sync_url() -> str:
    """Prefer explicit alembic config, else WORKGRAPH_DATABASE_URL,
    else fall back to the dev default. Always strips async driver
    prefixes so the sync DBAPI Alembic uses can connect."""
    url = config.get_main_option("sqlalchemy.url") or ""
    if not url:
        url = os.environ.get("WORKGRAPH_DATABASE_URL", "")
    if not url:
        # Same default as apps/api settings.py. Mirrors dev layout.
        url = f"sqlite:///{(_repo_root / 'data' / 'workgraph.sqlite').as_posix()}"

    # Rewrite `dialect+asyncdriver://...` to `dialect+syncdriver://...`.
    # If the user already passed a sync URL we leave it alone.
    m = re.match(r"^(?P<dialect>[a-z0-9]+)\+(?P<driver>[a-z0-9]+)://", url)
    if m and m.group("driver") in _ASYNC_TO_SYNC_DRIVERS:
        sync_driver = _ASYNC_TO_SYNC_DRIVERS[m.group("driver")]
        url = re.sub(
            r"^([a-z0-9]+)\+[a-z0-9]+://",
            f"\\1+{sync_driver}://",
            url,
            count=1,
        )
    # SQLAlchemy ships pysqlite built-in; collapse "sqlite+pysqlite" to
    # the canonical "sqlite" form that sqlite3 recognizes without extras.
    url = url.replace("sqlite+pysqlite://", "sqlite://")
    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB. Useful for `alembic upgrade
    head --sql` to preview changes before applying."""
    url = _resolve_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB."""
    ini_section = config.get_section(config.config_ini_section) or {}
    ini_section["sqlalchemy.url"] = _resolve_sync_url()
    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # compare_type catches new columns + column-type changes.
            # compare_server_default flags server-side default drift.
            compare_type=True,
            compare_server_default=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
