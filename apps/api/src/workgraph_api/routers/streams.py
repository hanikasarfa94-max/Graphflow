"""Phase B (v2) — stream endpoints.

North-star §"Streams as the unifying primitive": one renderer, two types in
v1 (project + dm). Project streams are auto-backfilled from existing
projects on boot, so v1 surface focuses on:

  * POST /api/streams/dm      — create (or return existing) 1:1 DM
  * GET  /api/streams         — list streams the caller belongs to
  * POST /api/streams/{id}/read  — mark stream read (updates last_read_at)

All routes require a signed-in user.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import AuthenticatedUser, StreamService

router = APIRouter(prefix="/api", tags=["streams"])


class CreateDMRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    other_user_id: str = Field(min_length=1, max_length=64)


class StreamMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)


def _get_service(request: Request) -> StreamService:
    return request.app.state.stream_service


@router.post("/streams/dm")
async def post_create_dm(
    body: CreateDMRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    result = await service.create_or_get_dm(
        user_id=user.id, other_user_id=body.other_user_id
    )
    if not result.get("ok"):
        err = result.get("error", "create_dm_failed")
        if err == "user_not_found":
            raise HTTPException(status_code=404, detail=err)
        if err == "cannot_dm_self":
            raise HTTPException(status_code=400, detail=err)
        raise HTTPException(status_code=400, detail=err)
    return result


@router.get("/streams")
async def get_list_streams(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    items = await service.list_for_user(user.id)
    return {"streams": items}


@router.post("/streams/{stream_id}/read")
async def post_mark_stream_read(
    stream_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    result = await service.mark_read(stream_id=stream_id, user_id=user.id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "not_found"))
    return result


@router.post("/streams/{stream_id}/messages")
async def post_stream_message(
    stream_id: str,
    body: StreamMessageRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    result = await service.post_message(
        stream_id=stream_id, author_id=user.id, body=body.body
    )
    if not result.get("ok"):
        err = result.get("error", "post_failed")
        if err == "stream_not_found":
            raise HTTPException(status_code=404, detail=err)
        if err == "not_a_member":
            raise HTTPException(status_code=403, detail=err)
        raise HTTPException(status_code=400, detail=err)
    return result


@router.get("/streams/{stream_id}/messages")
async def get_stream_messages(
    stream_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    user: AuthenticatedUser = Depends(require_user),
):
    service = _get_service(request)
    result = await service.list_messages(
        stream_id=stream_id, viewer_id=user.id, limit=limit
    )
    if not result.get("ok"):
        err = result.get("error", "list_failed")
        if err == "stream_not_found":
            raise HTTPException(status_code=404, detail=err)
        if err == "not_a_member":
            raise HTTPException(status_code=403, detail=err)
        raise HTTPException(status_code=400, detail=err)
    return {"messages": result["messages"]}
