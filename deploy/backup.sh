#!/usr/bin/env bash
#
# Nightly SQLite backup for the WorkGraph prod api container.
#
# What this does:
#   1. Asks the running `api` container to take a consistent online snapshot
#      of /data/workgraph.db into /tmp/backup.db using Python's sqlite3
#      module (the api image has no sqlite3 CLI, but it does have the Python
#      bindings — same C function underneath: sqlite3_backup_init, which is
#      lock-free against a live writer).
#   2. docker cp's that snapshot out to /opt/workgraph/backups/ on the host,
#      timestamped.
#   3. Deletes the in-container /tmp/backup.db.
#   4. Prunes host backups older than 14 days.
#   5. Appends a one-line audit record to backup.log.
#
# Backups live on the SAME VPS as the source DB — this protects against
# "oops deleted the docker volume" and app-level data corruption, NOT
# against full VPS disk loss. Off-host sync (rclone → Aliyun OSS) is a
# planned follow-up.
#
# Exit codes:
#   0  — backup completed, file verified, retention applied
#   1  — any step failed (cron will surface via mail if configured)
#
set -euo pipefail

COMPOSE_FILE="/opt/workgraph/deploy/docker-compose.yml"
BACKUP_DIR="/opt/workgraph/backups"
LOG_FILE="${BACKUP_DIR}/backup.log"
RETENTION_DAYS=14
TS="$(date +%Y%m%d-%H%M%S)"
BACKUP_NAME="workgraph-${TS}.db"
HOST_PATH="${BACKUP_DIR}/${BACKUP_NAME}"
CONTAINER_TMP="/tmp/backup.db"

mkdir -p "${BACKUP_DIR}"

log() {
    # timestamped line, visible in tail -f
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "${LOG_FILE}"
}

fail() {
    log "FAIL: $*"
    exit 1
}

log "begin backup -> ${HOST_PATH}"

# 1. Online snapshot inside the api container.
#    sqlite3.Connection.backup() is the Python binding for the same
#    SQLite C API the .backup dot-command wraps — safe while api writes.
docker compose -f "${COMPOSE_FILE}" exec -T api python - <<'PY' \
    || fail "in-container snapshot failed"
import sqlite3, os, sys
src_path = "/data/workgraph.db"
dst_path = "/tmp/backup.db"
if os.path.exists(dst_path):
    os.remove(dst_path)
src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
dst = sqlite3.connect(dst_path)
with dst:
    src.backup(dst)
src.close(); dst.close()
print(f"snapshot ok -> {dst_path} ({os.path.getsize(dst_path)} bytes)")
PY

# 2. Copy the snapshot out of the container to the host backups dir.
docker compose -f "${COMPOSE_FILE}" cp "api:${CONTAINER_TMP}" "${HOST_PATH}" \
    || fail "docker cp to host failed"

# 3. Clean up the in-container tmp file (best-effort; never fail the job on this).
docker compose -f "${COMPOSE_FILE}" exec -T api rm -f "${CONTAINER_TMP}" \
    || log "WARN: could not remove ${CONTAINER_TMP} inside container (non-fatal)"

# 4. Verify the copied file: exists, nonzero, and starts with the SQLite
#    magic string "SQLite format 3\000".
[[ -s "${HOST_PATH}" ]] || fail "backup file missing or zero-byte: ${HOST_PATH}"
MAGIC="$(head -c 15 "${HOST_PATH}" 2>/dev/null || true)"
if [[ "${MAGIC}" != "SQLite format 3" ]]; then
    fail "backup file magic mismatch (got: ${MAGIC})"
fi
SIZE_BYTES="$(stat -c %s "${HOST_PATH}")"

# 5. Retention: prune workgraph-*.db files older than RETENTION_DAYS.
#    -mtime +N matches files with modification time > N*24h ago, so +14
#    == strictly older than 14 days, which is what we want.
PRUNED_COUNT=0
while IFS= read -r -d '' old; do
    rm -f -- "${old}"
    PRUNED_COUNT=$((PRUNED_COUNT + 1))
    log "pruned: ${old}"
done < <(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'workgraph-*.db' -mtime "+${RETENTION_DAYS}" -print0)

log "OK ${BACKUP_NAME} size=${SIZE_BYTES}B pruned=${PRUNED_COUNT}"
exit 0
