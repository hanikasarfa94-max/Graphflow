# WorkGraph AI

Coordination as a graph, not a document.

See `PLAN.md` for the build plan, `AGENT.md` for conventions, `docs/dev.md` for the full spec.

## Quick start

```bash
# Python deps (uses D:/uv-cache on this machine, see .env.example)
UV_CACHE_DIR=/d/uv-cache uv sync

# Web deps
cd apps/web && bun install

# Run everything
uv run uvicorn workgraph_api.main:app --reload --port 8000    # api
uv run python -m workgraph_worker.main                         # worker
cd apps/web && bun dev                                          # web (port 3000)

# Tests
uv run pytest
cd apps/web && bun test
```

## Layout

```
apps/
  api/     FastAPI — intake, planning, sync endpoints
  worker/  Celery — async agent runs (wired in later phases)
  web/     Next.js — stage-driven canvas + graph sidebar
packages/
  schemas/        shared Pydantic models (ApiError, domain DTOs)
  observability/  structured logging, trace_id propagation
  domain/         entities, state transitions (graph-native, 1E)
  agents/         LLM prompt runners, Instructor-validated output
  orchestrator/   workflow stage logic, agent invocation order
  feishu_adapter/ Feishu message/docs/Base clients
```
