# Deploy — quick reference

Single-node Aliyun VPS, mainland, 4 GB RAM, Docker already installed.
Domain via Cloudflare DNS. Port 8080 instead of 80 (skips ICP friction).
No TLS initially — Cloudflare Flexible SSL is the easiest add later.

## 0. Prep on Windows (once)

```powershell
# From repo root
tar --exclude='.git' --exclude='node_modules' --exclude='.next' `
    --exclude='data/workgraph.sqlite' --exclude='apps/api/data' `
    --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' `
    --exclude='.gstack' --exclude='.claude' `
    --exclude='workgraph-mock-data-v2/.git' `
    -czf workgraph.tar.gz *

scp workgraph.tar.gz root@118.31.226.72:/opt/
```

## 1. On VPS — one-time host setup

```bash
# Swap (bun build needs it)
fallocate -l 2G /swap && chmod 600 /swap && mkswap /swap && swapon /swap
echo "/swap none swap sw 0 0" >> /etc/fstab

# Docker China mirrors
cat > /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com",
    "https://hub-mirror.c.163.com"
  ],
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
EOF
systemctl restart docker

# Extract repo
mkdir -p /opt/workgraph && cd /opt/workgraph
tar -xzf /opt/workgraph.tar.gz
```

**Every subsequent deploy — extract, but preserve prod-local files:**
```bash
cd /opt/workgraph
tar -xzf /opt/workgraph.tar.gz \
    --exclude='data' \
    --exclude='deploy/.env' \
    --exclude='deploy/nginx/conf.d' \
    --exclude='deploy/docker-compose.yml'   # preserves the 8080/8443 port patch
```
Forgetting `deploy/nginx/conf.d` restores the stock TLS-enabled nginx
conf, which crash-loops on a missing cert. If that happens, rewrite the
file per §4 and `docker compose restart nginx`.

Forgetting `deploy/docker-compose.yml` reverts nginx host-ports to
`80:80` / `443:443`, which breaks the Cloudflare Tunnel upstream that
points at `127.0.0.1:8080`. Recovery: re-apply the §4 sed patches and
`docker compose up -d nginx`.

**Heredoc trap for interactive deploys:** if you run a deploy block via
`ssh root@vps <<'TAG' … TAG`, the closing `TAG` line must sit at
column 0. Any leading whitespace makes bash swallow the terminator and
you get `TAG: command not found` at the end. The commands inside still
run — it's cosmetic — but the ssh session also won't cleanly close,
which is confusing the first time.

## 2. Cloudflare DNS (one-time, in Cloudflare dashboard)

- `flyflow.love` → DNS → Records
- A record: Name `@`, Value `118.31.226.72`, Proxy **DNS only** (grey cloud)
- Delete any other A records for `@`

## 3. Aliyun Security Group (one-time, in Aliyun ECS console)

Add inbound rules:
- TCP `8080/8080` from `0.0.0.0/0`  (demo HTTP)
- TCP `8443/8443` from `0.0.0.0/0`  (optional, for later TLS)

## 4. On VPS — config patches

```bash
cd /opt/workgraph

# Compose: expose 8080/8443 instead of 80/443
sed -i 's/"80:80"/"8080:80"/g' deploy/docker-compose.yml
sed -i 's/"443:443"/"8443:443"/g' deploy/docker-compose.yml

# nginx: replace file with port-80-only (no TLS yet)
cat > deploy/nginx/conf.d/workgraph.conf <<'NGX_EOF'
upstream workgraph_api { server api:8000; keepalive 32; }
upstream workgraph_web { server web:3000; keepalive 32; }

server {
    listen 80;
    server_name flyflow.love _;
    client_max_body_size 2m;

    location /.well-known/acme-challenge/ { root /var/www/certbot; }

    location /ws/ {
        proxy_pass http://workgraph_api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location = /api/events/stream {
        proxy_pass http://workgraph_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    location /api/ {
        proxy_pass http://workgraph_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Connection "";
        proxy_read_timeout 60s;
    }

    location / {
        proxy_pass http://workgraph_web;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Connection "";
        proxy_read_timeout 60s;
    }
}
NGX_EOF

# .env — fill DEEPSEEK_API_KEY manually after copy
cp -n deploy/.env.example deploy/.env
vi deploy/.env    # set DEEPSEEK_API_KEY=sk-...  + WORKGRAPH_ENV=prod
```

## 5. Build + up + seed

```bash
cd /opt/workgraph

# Build (3-8 min; watch for OOM)
docker compose -f deploy/docker-compose.yml build api web

# Bring up
docker compose -f deploy/docker-compose.yml up -d redis api web nginx
docker compose -f deploy/docker-compose.yml ps

# Seed (one shot, all four scripts + smoke test)
bash /opt/workgraph/deploy/seed.sh
# External: http://flyflow.love:8080/
```





## 5b. Schema migrations (Alembic)

The api Dockerfile bundles Alembic. The bootstrap still uses
`Base.metadata.create_all()` for dev speed, but prod graduates to
Alembic for any schema change that can't survive a drop+recreate.

**First time per prod DB — stamp at baseline (one-off):**
```bash
docker compose -f deploy/docker-compose.yml exec -T api \
    /app/.venv/bin/alembic -c /app/apps/api/alembic.ini stamp 0001_baseline
```
Writes the `alembic_version` table marking the existing schema as "at
v1". No tables are altered; no data is moved.

**Every subsequent deploy — upgrade before the app serves traffic:**
```bash
docker compose -f deploy/docker-compose.yml exec -T api \
    /app/.venv/bin/alembic -c /app/apps/api/alembic.ini upgrade head
```
Idempotent — no-op when already at head. Applies
`0002_status_transitions`, `0003_commitments`, `0004_commitment_sla`,
`0005_handoff_records` to bring a v1 DB to v2. Preview before applying
with `... upgrade head --sql`.

**Why the full binary path:** `docker compose exec -T api sh -lc "..."`
spawns a login shell that drops the container's
`PATH=/app/.venv/bin:$PATH`, so `alembic` can't be found by name. Calling
`/app/.venv/bin/alembic` directly sidesteps the shell entirely.

**Why `--workdir /app/apps/api`:** `script_location = alembic` in
alembic.ini is relative to the command's CWD, not the config file's
directory. The container WORKDIR is `/app`, so alembic looks for
`/app/alembic/` and fails. Setting `--workdir /app/apps/api` on
`docker compose exec` fixes it.

**Recovery: "table already exists" on first migration run.** If the
prod DB was ever booted before being stamped, the bootstrap layer
(`Base.metadata.create_all()` in the api's startup path) already
created every ORM table — including any table a pending migration
would create. `alembic upgrade head` then blows up trying to
re-create an existing table. The DB is not corrupted; alembic just
doesn't know the schema is already at head. Recovery:

```bash
# 1. Confirm the tables actually exist (expect to see all)
docker compose -f deploy/docker-compose.yml exec -T api python -c \
  "import sqlite3; c=sqlite3.connect('/app/data/workgraph.sqlite'); \
   print(sorted(r[0] for r in c.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')))"

# 2. Stamp at head — no DDL runs; just tells alembic "DB matches head"
docker compose -f deploy/docker-compose.yml exec -T --workdir /app/apps/api api \
    /app/.venv/bin/alembic stamp head

# 3. Verify
docker compose -f deploy/docker-compose.yml exec -T --workdir /app/apps/api api \
    /app/.venv/bin/alembic current
```

After this, future `upgrade head` runs are a no-op until a new migration
file lands — exactly what we want.

**Rollback** is available (`alembic downgrade -1`) but not automated
— treat it as a dev convenience, not a prod safety net.

## 6. Operate

```bash
# Tail logs
docker compose -f deploy/docker-compose.yml logs -f api web nginx

# Restart one service after a code change
docker compose -f deploy/docker-compose.yml restart api

# Full rebuild after a git pull / new tarball
docker compose -f deploy/docker-compose.yml build api web
docker compose -f deploy/docker-compose.yml up -d api web

# Stop everything (data persists on the docker volume)
docker compose -f deploy/docker-compose.yml down
```

## 7. Add TLS later (when you want HTTPS)

Easiest path — Cloudflare Flexible SSL (no cert on origin, Cloudflare does HTTPS):
1. In Cloudflare → `flyflow.love` → SSL/TLS → set mode to **Flexible**
2. Flip the A record proxy to **Proxied** (orange cloud)
3. Done. `https://flyflow.love` works; Cloudflare talks to origin over HTTP.
4. Caveat: mainland users may hit CF edge blocks — test before committing.

Harder path — real cert on origin via Let's Encrypt DNS-01 (no port 80 exposure needed). Ask me for the steps if you need origin TLS.

## Troubleshooting

- **bun build OOM**: `export NODE_OPTIONS=--max_old_space_size=3072` then rebuild.
- **`dig` returns multiple IPs**: leftover CF record; delete in CF dashboard.
- **Port 8080 timeout from outside**: security group rule missing.
- **`api` crashlooping**: check `docker compose logs api`; likely DB path or DEEPSEEK key.
- **WS 502 in browser**: `nginx` container didn't pick up conf — `docker compose restart nginx`.
