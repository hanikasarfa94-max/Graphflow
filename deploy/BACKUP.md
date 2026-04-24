# Backups — WorkGraph prod

Nightly snapshot of the SQLite DB that powers the api container.

## Layout

- **Source DB (live):** `workgraph_api-data` docker volume, mounted into the
  `api` container at `/data/workgraph.db`. Host path:
  `/var/lib/docker/volumes/workgraph_api-data/_data/workgraph.db`.
- **Backups:** `/opt/workgraph/backups/workgraph-YYYYMMDD-HHMMSS.db`
- **Logs:** `/opt/workgraph/backups/backup.log` (per-run lines) and
  `/opt/workgraph/backups/cron.log` (raw cron stdout+stderr).
- **Script:** `/opt/workgraph/deploy/backup.sh`
- **Schedule:** `/etc/cron.d/workgraph-backup` — runs `0 3 * * *` as root.
- **Retention:** 14 days. `find -mtime +14 -delete` each run.

## How the snapshot is taken

The api image does **not** ship the `sqlite3` CLI, but it does ship
Python's `sqlite3` module, which binds the same `sqlite3_backup_init`
C API as the CLI's `.backup` dot-command. The script runs a small inline
Python program inside the `api` container to copy the live DB to
`/tmp/backup.db`, then `docker compose cp`s it out to the host. This is
a consistent online snapshot — it does not block the api's writes.

## Restore

Assume `/opt/workgraph/backups/workgraph-20260424-030005.db` is the target.

```bash
cd /opt/workgraph

# 1. Stop the api (web can stay up — it'll just 5xx until api returns).
docker compose -f deploy/docker-compose.yml stop api

# 2. Move aside the current DB, drop the backup into place.
#    The volume mountpoint on the host:
VOL=/var/lib/docker/volumes/workgraph_api-data/_data
mv "${VOL}/workgraph.db" "${VOL}/workgraph.db.broken-$(date +%s)"
cp /opt/workgraph/backups/workgraph-20260424-030005.db "${VOL}/workgraph.db"

# 3. Fix ownership — the api container runs as uid 1000 (user 'workgraph');
#    files copied in as root won't be writable by the process.
chown 1000:1000 "${VOL}/workgraph.db"
chmod 644       "${VOL}/workgraph.db"

# 4. Restart api and verify.
docker compose -f deploy/docker-compose.yml start api
docker compose -f deploy/docker-compose.yml logs --tail=50 api

# 5. Sanity-check row counts (via the api container's Python).
docker compose -f deploy/docker-compose.yml exec -T api python -c \
  "import sqlite3; c=sqlite3.connect('/data/workgraph.db'); \
   print(sorted((t, c.execute(f'SELECT count(*) FROM {t}').fetchone()[0]) \
   for (t,) in c.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')))"
```

If the api refuses to start after restore, check the schema version — a
backup taken before a migration won't match the current code. In that
case either (a) downgrade the api image to the matching tag, or
(b) re-run `alembic upgrade head` against the restored file (see
`DEPLOY.md §5b`).

## Caveats

- **Same-VPS only.** Backups and source DB share the same disk. This
  protects against: accidental `docker volume rm`, corruption of the
  live DB, bad migration, fat-finger `DELETE` without `WHERE`. It does
  **not** protect against: VPS disk failure, VPS account termination,
  datacenter-level outage. Off-host push to Aliyun OSS is on the roadmap
  (`rclone copy /opt/workgraph/backups/ oss:...`) but not wired in yet.
- **Retention is by mtime.** If you manually `touch` an old file to keep
  it around, understand that the 14-day window resets from the mtime.
- **No encryption at rest.** The backup DB contains user data. Anyone
  with root on the VPS can read it — same trust boundary as the live DB.

## Re-deploying the cron entry

`/etc/cron.d/workgraph-backup` lives on the VPS, not in the repo. If it
gets wiped (fresh VPS, bad rollback), recreate it:

```bash
cat > /etc/cron.d/workgraph-backup <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 3 * * *   root  /opt/workgraph/deploy/backup.sh >> /opt/workgraph/backups/cron.log 2>&1
EOF
chmod 644 /etc/cron.d/workgraph-backup
```

No `systemctl reload` needed — `cron` rescans `/etc/cron.d/` each minute.

## Manual run

Useful before a risky migration or deploy:

```bash
/opt/workgraph/deploy/backup.sh
tail -n 5 /opt/workgraph/backups/backup.log
ls -lh /opt/workgraph/backups/
```
