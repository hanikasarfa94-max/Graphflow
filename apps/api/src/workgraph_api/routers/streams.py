"""Stream endpoints — project + DM (Phase B/v2) and room (N-Next).

North-star §"Streams as the unifying primitive": one renderer, four types
in N-Next:
  * 'project' — main team room, auto-backfilled per cell at boot.
  * 'personal' — per-user sub-agent stream, project-anchored.
  * 'dm' — 1:1 between two users, no project anchor.
  * 'room' — sub-team / topical / ad-hoc rooms within a cell. N-Next
    addition per new_concepts.md §6.11 + Correction R.2.

Endpoints:
  * POST /api/streams/dm                      — create or get 1:1 DM
  * GET  /api/streams                         — list streams I belong to
  * POST /api/streams/{id}/read               — mark stream read
  * POST /api/streams/{id}/messages           — post message
  * GET  /api/streams/{id}/messages           — list messages
  * POST /api/projects/{id}/rooms             — N-Next: create room
  * GET  /api/projects/{id}/rooms             — N-Next: list rooms

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


class CreateRoomRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    member_user_ids: list[str] = Field(default_factory=list, max_length=200)


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


# ---- N-Next: multi-room (new_concepts.md §6.11, Correction R.2) -------


@router.post("/projects/{project_id}/rooms")
async def post_create_room(
    project_id: str,
    body: CreateRoomRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """Create a room (sub-team / topical / ad-hoc stream) inside a cell.

    Members must be a subset of the cell's project members. Creator is
    auto-added. TODO (N.4): route through MembraneService.review() with
    CandidateKind='manual_room' for cell-governance gating.
    """
    service = _get_service(request)
    result = await service.create_room(
        project_id=project_id,
        creator_user_id=user.id,
        name=body.name,
        member_user_ids=body.member_user_ids,
    )
    if not result.get("ok"):
        err = result.get("error", "create_room_failed")
        if err == "name_required" or err == "name_too_long":
            raise HTTPException(status_code=400, detail=err)
        if err == "not_a_member":
            raise HTTPException(status_code=403, detail=err)
        if err == "non_cell_member":
            raise HTTPException(status_code=400, detail=err)
        raise HTTPException(status_code=400, detail=err)
    return result


@router.get("/projects/{project_id}/rooms")
async def get_list_rooms(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
):
    """List every room stream in a cell. Project members + organization-
    leads (read-only bypass per B4) can list."""
    service = _get_service(request)
    result = await service.list_rooms_for_project(
        project_id=project_id, viewer_user_id=user.id
    )
    if not result.get("ok"):
        err = result.get("error", "list_rooms_failed")
        if err == "not_a_member":
            raise HTTPException(status_code=403, detail=err)
        raise HTTPException(status_code=400, detail=err)
    return {"rooms": result["rooms"]}
