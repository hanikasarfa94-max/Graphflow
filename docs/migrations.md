# Database migrations & schema model

**Status:** current. Written 2026-05-31 (M11a). Authoritative on how this repo
initializes and evolves its schema.

## The deploy model: `create_all` + `stamp head` (NOT `upgrade` from empty)

This project does **not** build its schema by running the Alembic chain from an
empty database. The schema source of truth is the SQLAlchemy ORM
(`packages/persistence/src/workgraph_persistence/orm.py`), materialized by
`Base.metadata.create_all`:

- **App startup** (`apps/api/src/workgraph_api/main.py:376`) calls
  `bootstrap.create_all(engine)` (`packages/persistence/.../bootstrap.py:42`),
  which runs `Base.metadata.create_all`. In dev a column-level staleness check
  may drop-and-recreate the local SQLite; in **prod it never drops** — a stale
  schema logs loudly and surfaces the `OperationalError` (post-mortem
  2026-04-25, when a silent drop wiped a live DB).
- **Tests** build a fresh `:memory:` DB via the same `create_all` per session
  (`apps/api/tests/conftest.py`), with `StaticPool` scoped to in-memory SQLite.
- **Alembic's role** is the *production migration ledger*: after `create_all`
  builds a new DB, the operator runs `alembic stamp head` to mark it current.
  On an existing prod DB, real schema changes ship as new migrations applied
  with `alembic upgrade head`.

## The chain is intentionally NOT runnable from empty

`alembic upgrade head` against a brand-new empty DB **fails** (around `0012`
with `NoSuchTableError: membrane_signals`). This is expected, not a bug:
`membrane_signals` was created mid-chain and later **dropped** during the
F2→F5 KB fold (`0024_drop_membrane_signals.py`), so intermediate revisions
reference a table that no longer exists in a linear empty-DB replay. Because the
deploy model is `create_all` + `stamp` (never empty-upgrade), this path is dead
and is **not** maintained. Do not try to "fix" the chain to run from empty
unless that is adopted as an explicit, separately-scoped goal — it is
archaeology with no benefit to the current deploy path.

## How to run `alembic check` correctly

`alembic check` (autogenerate-diff) is only meaningful against a DB whose schema
matches `create_all` and is stamped at head. Running it against a **contaminated
DB** — e.g. one left half-migrated by a failed `upgrade head` — reports a flood
of phantom drift (server_defaults, type mismatches, dangling FKs) that reflects
the stale intermediate schema, **not** the real ORM↔migration relationship.

Correct procedure (clean DB):

```bash
# 1. build the schema the way the app does
WORKGRAPH_DATABASE_URL="sqlite+aiosqlite:////tmp/check.db" \
  uv run python -c "import asyncio; from workgraph_persistence import build_engine, create_all; \
  asyncio.run(create_all(build_engine('sqlite+aiosqlite:////tmp/check.db')))"

# 2. stamp it at head (matches deploy)
cd apps/api && WORKGRAPH_DATABASE_URL="sqlite+aiosqlite:////tmp/check.db" \
  uv run alembic stamp head

# 3. now the diff is honest — expect "No new upgrade operations detected"
WORKGRAPH_DATABASE_URL="sqlite+aiosqlite:////tmp/check.db" \
  uv run alembic check
```

As of 2026-05-31 (post-M6), this reports **clean** — the `create_all` schema and
the migration head agree. The `test_schema_drift` guardrail
(`packages/persistence/tests/test_schema_drift.py`) enforces this in CI: a future
ORM change that lacks a matching migration will fail it.

## Adding a schema change

1. Edit the ORM model in `orm.py` (the source of truth).
2. Add a new migration in `apps/api/alembic/versions/` (`down_revision` = current
   head) that performs the **same** change with **identical** index/constraint
   names — `create_all` and the migration must agree, or `alembic check` drifts.
   Use `op.batch_alter_table` for SQLite-safe column/constraint ops (see `0027`).
3. Run the clean `alembic check` procedure above → must be clean.
4. Run `test_schema_drift` + the persistence suite.

See also: `ARCHITECTURE-AUDIT-2026-05-30.md` §M6/M11.
