#!/usr/bin/env bash
# Run all demo seeds inside the api container.
# One-shot: bash /opt/workgraph/deploy/seed.sh
set -euo pipefail

COMPOSE="docker compose -f $(dirname "$0")/docker-compose.yml"

for s in seed_moonshot seed_moonshot_zh seed_rich_details seed_wiki seed_v2_features; do
  echo "=== $s ==="
  $COMPOSE exec -T api python /app/scripts/demo/$s.py
done

echo
echo "=== smoke ==="
curl -sI http://127.0.0.1:8080/ | head -5
