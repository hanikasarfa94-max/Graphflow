#!/usr/bin/env bash
# Swap the TLS-dependent default nginx conf for the port-80-only prod
# conf, then bounce nginx. Safe to re-run; the target file is tracked
# in the repo at deploy/nginx/workgraph.prod.conf.
set -euo pipefail

cd "$(dirname "$0")/.."

SRC="deploy/nginx/workgraph.prod.conf"
DST="deploy/nginx/conf.d/workgraph.conf"

if [ ! -f "$SRC" ]; then
  echo "ERROR: $SRC not found — did the tarball get extracted cleanly?"
  exit 1
fi

cp -f "$SRC" "$DST"
echo "[patch-nginx-port80] wrote $DST"

docker compose -f deploy/docker-compose.yml restart nginx
sleep 2
docker compose -f deploy/docker-compose.yml ps

echo
echo "smoke:"
curl -sI http://127.0.0.1:8080/ | head -1 || true
curl -sI https://graphflow.flyflow.love/ | head -1 || true
