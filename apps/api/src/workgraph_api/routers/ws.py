"""WebSocket endpoint for realtime project collaboration.

Clients connect to `/ws/projects/{project_id}` with a session cookie OR a
`?token=` query param. On connect we subscribe to the CollabHub queue for
that project and forward every payload as a JSON text frame.

Inbound frames are presence pings that we echo back; everything else is
ignored (writes go through HTTP, not WS).

`/ws/streams/{stream_id}` is the stream-scoped channel — same contract
(session/cookie auth, hello/pong, message frames) but fanned out on the
stream namespace only. Used by PersonalStream and DMStream to replace 3s
polling.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from workgraph_persistence import (
    ProjectRow,
    StreamMemberRepository,
    StreamRepository,
    session_scope,
)

from workgraph_api.services import SESSION_COOKIE
from workgraph_api.settings import load_settings

_settings = load_settings()

_log = logging.getLogger("workgraph.api.ws")


router = APIRouter(tags=["ws"])


ACTIVE_WS = {"count": 0}
ACTIVE_STREAM_WS = {"count": 0}


@router.websocket("/ws/projects/{project_id}")
async def project_ws(
    websocket: WebSocket,
    project_id: str,
    token: str | None = Query(default=None),
) -> None:
    auth_service = websocket.app.state.auth_service
    project_service = websocket.app.state.project_service
    hub = websocket.app.state.collab_hub
    sessionmaker = websocket.app.state.sessionmaker

    session_token = websocket.cookies.get(SESSION_COOKIE) or token
    user = None
    if session_token:
        user = await auth_service.resolve_session(session_token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with session_scope(sessionmaker) as session:
        project = (
            await session.execute(select(ProjectRow).where(ProjectRow.id == project_id))
        ).scalar_one_or_none()
    if project is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    if not await project_service.is_member(project_id=project_id, user_id=user.id):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    ACTIVE_WS["count"] += 1
    queue = await hub.subscribe(project_id)
    await websocket.send_text(
        json.dumps(
            {
                "type": "hello",
                "payload": {
                    "project_id": project_id,
                    "user_id": user.id,
                    "username": user.username,
                },
            }
        )
    )

    async def _pump_outbound() -> None:
        while True:
            payload = await queue.get()
            await websocket.send_text(json.dumps(payload, default=str))

    async def _pump_inbound() -> None:
        while True:
            msg = await websocket.receive_text()
            # Only honor ping frames for now; every other client intent goes
            # through HTTP. Ignoring unknown payloads keeps us forward-compatible.
            try:
                data = json.loads(msg)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_text(
                    json.dumps({"type": "pong", "payload": {}})
                )

    outbound = asyncio.create_task(_pump_outbound(), name=f"ws-out-{project_id}")
    inbound = asyncio.create_task(_pump_inbound(), name=f"ws-in-{project_id}")
    try:
        done, pending = await asyncio.wait(
            {outbound, inbound}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(project_id, queue)
        ACTIVE_WS["count"] = max(0, ACTIVE_WS["count"] - 1)


@router.websocket("/ws/streams/{stream_id}")
async def stream_ws(
    websocket: WebSocket,
    stream_id: str,
    token: str | None = Query(default=None),
) -> None:
    """Per-stream WS channel.

    Auth: caller must be a StreamMember of `stream_id`. Cookie or token
    auth mirrors `/ws/projects/{project_id}` so the two routes share the
    same deployment story (session cookie from the Next.js frontend;
    token for curl/websocat manual tests).

    Broadcasts: every StreamService.post_message and post_system_message
    fans out a `{"type": "message", "payload": {...}}` frame on this
    channel (see StreamService._hub.publish_stream).
    """
    auth_service = websocket.app.state.auth_service
    hub = websocket.app.state.collab_hub
    sessionmaker = websocket.app.state.sessionmaker

    session_token = websocket.cookies.get(SESSION_COOKIE) or token
    user = None
    if session_token:
        user = await auth_service.resolve_session(session_token)
    if user is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with session_scope(sessionmaker) as session:
        stream = await StreamRepository(session).get(stream_id)
        if stream is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        member_repo = StreamMemberRepository(session)
        if not await member_repo.is_member(stream_id=stream_id, user_id=user.id):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await websocket.accept()
    ACTIVE_STREAM_WS["count"] += 1
    queue = await hub.subscribe_stream(stream_id)
    await websocket.send_text(
        json.dumps(
            {
                "type": "hello",
                "payload": {
                    "stream_id": stream_id,
                    "user_id": user.id,
                    "username": user.username,
                },
            }
        )
    )

    async def _pump_outbound() -> None:
        while True:
            payload = await queue.get()
            await websocket.send_text(json.dumps(payload, default=str))

    async def _pump_inbound() -> None:
        while True:
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
            except Exception:
                continue
            if isinstance(data, dict) and data.get("type") == "ping":
                await websocket.send_text(
                    json.dumps({"type": "pong", "payload": {}})
                )

    outbound = asyncio.create_task(_pump_outbound(), name=f"ws-stream-out-{stream_id}")
    inbound = asyncio.create_task(_pump_inbound(), name=f"ws-stream-in-{stream_id}")
    try:
        done, pending = await asyncio.wait(
            {outbound, inbound}, return_when=asyncio.FIRST_COMPLETED
        )
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe_stream(stream_id, queue)
        ACTIVE_STREAM_WS["count"] = max(0, ACTIVE_STREAM_WS["count"] - 1)


# Introspection of live WS subscriber counts. The same counters are already
# exposed (un-authed) via /health for ops probes, so this route is purely a
# dev aid. Registered ONLY when env == "dev" — in staging/prod the route is
# absent from the schema.
if _settings.env == "dev":
    @router.get("/ws/_debug/active_count")
    async def active_ws_count() -> dict:
        return {"count": ACTIVE_WS["count"], "stream_count": ACTIVE_STREAM_WS["count"]}
