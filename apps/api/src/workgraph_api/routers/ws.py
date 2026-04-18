"""WebSocket endpoint for realtime project collaboration.

Clients connect to `/ws/projects/{project_id}` with a session cookie OR a
`?token=` query param. On connect we subscribe to the CollabHub queue for
that project and forward every payload as a JSON text frame.

Inbound frames are presence pings that we echo back; everything else is
ignored (writes go through HTTP, not WS).
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from workgraph_persistence import ProjectRow, session_scope

from workgraph_api.services import SESSION_COOKIE

_log = logging.getLogger("workgraph.api.ws")


router = APIRouter(tags=["ws"])


ACTIVE_WS = {"count": 0}


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


@router.get("/ws/_debug/active_count")
async def active_ws_count() -> dict:
    return {"count": ACTIVE_WS["count"]}
