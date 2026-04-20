# Alembic migrations

Out-of-process schema migrations for the api DB. Runs via sync
SQLAlchemy drivers — the async URL (`sqlite+aiosqlite://…` /
`postgresql+asyncpg://…`) is rewritten to a sync equivalent in
`env.py` automatically.

## Dev — default is still `create_all`

The FastAPI bootstrap still calls `Base.metadata.create_all()` with
drift detection on startup. Fast for dev iteration, no migration
churn when you add a column to an ORM model.

You never **need** to run alembic in dev. Commands below are for when
you want to author new migrations or verify that the current set
applies cleanly.

## Prod — migrations are the deploy gate

Prod DBs (Aliyun SWAS sqlite + future Postgres) use Alembic. The
first deploy that adopts it stamps the existing DB at baseline, then
every subsequent deploy runs `alembic upgrade head` before the api
container starts.

### First-time stamp (one-off, per prod DB)

```bash
# From the api container, with WORKGRAPH_DATABASE_URL set:
cd /app/apps/api
alembic stamp 0001_baseline
```

This tells Alembic "the existing tables already match this revision"
without re-creating them. It writes to the `alembic_version` table.

### Regular upgrade (every deploy, after stamp)

```bash
cd /app/apps/api
alembic upgrade head
```

Idempotent — re-running when up-to-date is a no-op.

### Preview SQL without applying

```bash
alembic upgrade head --sql
```

## Author a new migration

When you change an ORM model:

```bash
cd apps/api
alembic revision --autogenerate -m "what changed"
```

Review the generated file. Auto-generate hits ~95% of cases but
always sanity-check — it doesn't know about your server-side
defaults, check constraints, or multi-statement migrations.

## Current revisions

- `0001_baseline` — v1 schema anchor (no-op upgrade)
- `0002_status_transitions` — Sprint 1b time-cursor source
- `0003_commitments` — Sprint 2a thesis-commit primitive
- `0004_commitment_sla` — Sprint 2b SLA columns on commitments

## Caveats

- **SQLite ALTER TABLE is limited.** env.py sets `render_as_batch=True`
  for sqlite so add_column / drop_column work via the copy-and-swap
  pattern. Don't hand-write `op.alter_column(...)` without `batch_alter_table`
  for sqlite.
- **FK cascades on sqlite** require `PRAGMA foreign_keys = ON` per
  connection; the app already sets this at session scope.
- **Downgrade** paths exist but aren't wired into any automation. Use
  for dev experiments, not for rolling back prod data.
