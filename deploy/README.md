# WorkGraph AI — single-node deploy

Targets a small Aliyun VPS (2 vCPU, 4 GB is enough for the dev-sized SQLite
setup). One nginx container fronts everything; api + web are independent
containers on a private compose network; redis backs the WebSocket fanout.

## Layout

```
deploy/
├── docker-compose.yml    # api + web + nginx + redis + certbot
├── .env.example          # copy to .env before `docker compose up`
├── nginx/
│   ├── conf.d/workgraph.conf   # 80/443 vhost, / → web, /api → api, /ws upgrade
│   └── certs/                  # fullchain.pem + privkey.pem (from certbot)
└── README.md             # this file
```

Dockerfiles live next to the code they build:
- `apps/api/Dockerfile`     — multistage uv build, runtime is `python:3.11-slim`
- `apps/web/Dockerfile`     — multistage `bun build`, runtime is `node:20-slim`

## First boot

1. Point DNS for your domain at the VPS. Edit
   `deploy/nginx/conf.d/workgraph.conf` and replace `workgraph.example.com`
   with the real hostname.
2. Copy env and fill secrets:
   ```
   cp deploy/.env.example deploy/.env
   # Fill DEEPSEEK_API_KEY if you want live LLM; leave empty for stub mode.
   ```
   Sessions are stored in the DB (tokens are random via `secrets.token_urlsafe`),
   so there is no HMAC secret to rotate in this deployment.
3. Bring up the stack without TLS (comment out the 443 server block the
   first time, or use a self-signed cert):
   ```
   docker compose -f deploy/docker-compose.yml up -d api web redis nginx
   ```
4. Issue the production cert via the certbot service:
   ```
   docker compose -f deploy/docker-compose.yml run --rm certbot \
     certonly --webroot -w /var/www/certbot \
       -d workgraph.example.com \
       --email you@example.com --agree-tos --no-eff-email
   ```
   Symlink the issued cert into place and reload nginx:
   ```
   ln -sf live/workgraph.example.com/fullchain.pem deploy/nginx/certs/fullchain.pem
   ln -sf live/workgraph.example.com/privkey.pem   deploy/nginx/certs/privkey.pem
   docker compose -f deploy/docker-compose.yml exec nginx nginx -s reload
   ```
   The certbot service then renews every 12h automatically.

## What each service expects

- **api** listens on `:8000` inside the compose net. The healthcheck hits
  `GET /health` which now reports `sse_streams` and `ws_streams` counts.
  SQLite data lives on the `api-data` volume; switch to Postgres by
  adjusting `WORKGRAPH_DATABASE_URL`.
- **web** listens on `:3000`. `WORKGRAPH_API_BASE=http://api:8000` is used
  by server-side fetch (`requireUser`, `serverFetch`). The browser never
  sees that URL — same-origin /api is rewritten by Next to the api
  container.
- **nginx** is the only public listener. `/api/events/stream` and `/ws/`
  have dedicated locations that disable buffering and set the WebSocket
  upgrade headers.
- **redis** is used by `CollabHub` for cross-process WebSocket fanout.
  On a single node it still gives clean restart semantics.

## Updating

```
git pull
docker compose -f deploy/docker-compose.yml build api web
docker compose -f deploy/docker-compose.yml up -d api web
```

Compose's rolling behavior is good enough for the two stateless services.
SQLite migrations run on api startup via `persistence.init_schema`; add
explicit alembic once the schema stabilizes.
