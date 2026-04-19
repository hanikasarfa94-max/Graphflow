# syntax=docker/dockerfile:1.7
# Multi-stage build for the FastAPI backend. uv handles the workspace lock
# and materializes a single virtualenv containing all workspace deps.

FROM ghcr.io/astral-sh/uv:0.5-python3.11-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Copy workspace manifest + all member pyproject.toml files so the lock
# resolves identically to local. Source comes after to keep the layer cache
# useful on code-only changes.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/worker/pyproject.toml apps/worker/pyproject.toml
COPY packages/schemas/pyproject.toml packages/schemas/pyproject.toml
COPY packages/observability/pyproject.toml packages/observability/pyproject.toml
COPY packages/persistence/pyproject.toml packages/persistence/pyproject.toml
COPY packages/domain/pyproject.toml packages/domain/pyproject.toml
COPY packages/agents/pyproject.toml packages/agents/pyproject.toml
COPY packages/orchestrator/pyproject.toml packages/orchestrator/pyproject.toml
COPY packages/feishu_adapter/pyproject.toml packages/feishu_adapter/pyproject.toml

COPY apps/api/src apps/api/src
COPY packages/schemas/src packages/schemas/src
COPY packages/observability/src packages/observability/src
COPY packages/persistence/src packages/persistence/src
COPY packages/domain/src packages/domain/src
COPY packages/agents/src packages/agents/src
COPY packages/orchestrator/src packages/orchestrator/src
COPY packages/feishu_adapter/src packages/feishu_adapter/src

RUN uv sync --frozen --package workgraph-api --no-dev

# ---------- runtime ----------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# curl for healthchecks only. Everything else comes from the venv.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/apps/api/src /app/apps/api/src
COPY --from=builder /app/packages /app/packages

# Seed scripts + mock-data fixtures are baked in so
# `docker compose exec api uv run python scripts/demo/seed_moonshot.py`
# works out of the box in production.
COPY scripts /app/scripts
COPY workgraph-mock-data-v2 /app/workgraph-mock-data-v2

RUN useradd --system --uid 1000 workgraph \
    && chown -R workgraph:workgraph /app
USER workgraph

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "workgraph_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
