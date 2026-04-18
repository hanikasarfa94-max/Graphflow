"""Server-Sent Events stream for a project's event log.

Phase 7' scope: tails the `events` table filtered by `project_id`, pushes
`{id, name, trace_id, payload, created_at}` lines to the browser. Polling
the DB keeps the implementation dependency-free (no Redis required for the
SSE path). The CollabHub handles WS broadcast in parallel for deltas that
do not show up in the events table.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from workgraph_persistence import EventRepository, ProjectRow, session_scope

from workgraph_api.deps import maybe_user, require_user
from workgraph_api.services import AuthenticatedUser, ProjectService

_log = logging.getLogger("workgraph.api.events_stream")


router = APIRouter(prefix="/api/events", tags=["events"])


_POLL_INTERVAL_SEC = 0.25
# Track tail connections for the fault-injection test. Each SSE generator
# increments on open and decrements on close; the /health endpoint reports
# the count so the test can assert drops after disconnects.
ACTIVE_STREAMS = {"count": 0}


def _format_sse(event_id: str, data: dict) -> bytes:
    payload = json.dumps(data, default=str)
    return f"id: {event_id}\ndata: {payload}\n\n".encode("utf-8")


async def _tail_events(
    request: Request,
    project_id: str,
    sessionmaker,
) -> AsyncIterator[bytes]:
    ACTIVE_STREAMS["count"] += 1
    try:
        # Emit a hello event so clients can confirm the connection landed.
        yield _format_sse(
            "hello",
            {
                "type": "hello",
                "project_id": project_id,
            },
        )
        cursor: str | None = None
        while True:
            if await request.is_disconnected():
                _log.debug("sse client disconnected", extra={"project_id": project_id})
                return
            async with session_scope(sessionmaker) as session:
                rows = await EventRepository(session).list_for_project_since(
                    project_id, since_id=cursor, limit=50
                )
            for row in rows:
                cursor = row.id
                payload_summary = row.payload
                yield _format_sse(
                    row.id,
                    {
                        "id": row.id,
                        "name": row.name,
                        "trace_id": row.trace_id,
                        "payload": payload_summary,
                        "created_at": row.created_at.isoformat(),
                    },
                )
            # Heartbeat to keep proxies from closing idle connections.
            if not rows:
                yield b": keep-alive\n\n"
            try:
                await asyncio.sleep(_POLL_INTERVAL_SEC)
            except asyncio.CancelledError:
                return
    finally:
        ACTIVE_STREAMS["count"] = max(0, ACTIVE_STREAMS["count"] - 1)


@router.get("/stream")
async def stream_events(
    request: Request,
    project_id: str,
    user: AuthenticatedUser | None = Depends(maybe_user),
) -> StreamingResponse:
    # Two auth paths: session cookie OR ?token=<session_token> for EventSource
    # clients that cannot send custom headers and struggle with cookies during
    # a same-origin Next.js rewrite. Cookie wins when both are provided.
    if user is None:
        token = request.query_params.get("token")
        if token:
            auth_service = request.app.state.auth_service
            user = await auth_service.resolve_session(token)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")

    project_service: ProjectService = request.app.state.project_service
    project = None
    async with session_scope(request.app.state.sessionmaker) as session:
        project = (
            await session.execute(select(ProjectRow).where(ProjectRow.id == project_id))
        ).scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")

    is_member = await project_service.is_member(project_id=project_id, user_id=user.id)
    if not is_member:
        raise HTTPException(status_code=403, detail="not a project member")

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        _tail_events(request, project_id, request.app.state.sessionmaker),
        media_type="text/event-stream",
        headers=headers,
    )


@router.get("/_debug/active_count")
async def active_count() -> dict[str, Any]:
    return {"count": ACTIVE_STREAMS["count"]}
