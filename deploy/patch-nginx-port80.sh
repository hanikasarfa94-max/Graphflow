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

# Mainland prod skips ports 80/443 (ICP friction + Aliyun default-blocked)
# and binds to 8080/8443 instead. Idempotent — no-op if already rewritten.
sed -i 's/"80:80"/"8080:80"/g; s/"443:443"/"8443:443"/g' \
    deploy/docker-compose.yml
echo "[patch-nginx-port80] host ports remapped to 8080/8443"

docker compose -f deploy/docker-compose.yml up -d --force-recreate nginx
sleep 2
docker compose -f deploy/docker-compose.yml ps

echo
echo "smoke:"
curl -sI http://127.0.0.1:8080/ | head -1 || true
curl -sI https://graphflow.flyflow.love/ | head -1 || true
