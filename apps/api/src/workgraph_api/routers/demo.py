"""Phase 13 — canonical demo seed endpoint.

One endpoint, one job: drive the canonical event-registration demo
walk via the API so a fresh DB boots into "just shipped the demo
project" state.

Gated to env=dev|staging. In prod this endpoint 404s (we don't even
advertise its existence) so a real deployment never leaks seed data.

Used by:
  * Playwright demo-lock spec — seed then assert the UI renders it.
  * Demo-day dry runs — reset + seed in a single POST.
  * Manual smoke-test kiosks.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.demo_seed import (
    DEFAULT_PASSWORD,
    DEFAULT_SOURCE_EVENT_ID,
    DEFAULT_USERNAME,
    run_canonical_demo,
)
from workgraph_api.settings import load_settings

router = APIRouter(prefix="/api/demo", tags=["demo"])


class SeedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(default=DEFAULT_USERNAME, max_length=80)
    password: str = Field(default=DEFAULT_PASSWORD, min_length=6, max_length=200)
    source_event_id: str = Field(
        default=DEFAULT_SOURCE_EVENT_ID, max_length=200
    )


def _dev_only() -> None:
    """Hard gate — the seed endpoint must not exist in prod."""
    env = load_settings().env
    if env == "prod":
        # 404 rather than 403 so prod surfaces look like the route
        # was never wired in the first place.
        raise HTTPException(status_code=404, detail="not found")


@router.post("/seed")
async def seed_canonical_demo(request: Request, body: SeedRequest | None = None):
    """Drive the full canonical flow on a fresh cookie jar.

    We build an internal ASGI httpx client so the walker speaks to the
    real routes (same middleware, same dependencies) without needing a
    second HTTP hop. The caller's cookie jar is not touched.
    """
    _dev_only()
    body = body or SeedRequest()

    transport = ASGITransport(app=request.app)
    async with AsyncClient(
        transport=transport, base_url="http://demo-seed"
    ) as inner:
        result = await run_canonical_demo(
            inner,
            app_state=request.app.state,
            username=body.username,
            password=body.password,
            source_event_id=body.source_event_id,
        )
    return {
        "project_id": result.project_id,
        "requirement_version": result.requirement_version,
        "clarification_ids": result.clarification_ids,
        "conflict_id": result.conflict_id,
        "decision_id": result.decision_id,
        "delivery_id": result.delivery_id,
        "delivery_trace_id": result.delivery_trace_id,
        "completed_scope_items": result.completed_scope_items,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
    }
