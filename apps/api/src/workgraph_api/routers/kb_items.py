"""KB items router — Phase V manual-write primitive.

  POST   /api/projects/{project_id}/kb-items
      Create a new KB note. Default scope=personal. Body:
      {title, content_md?, scope?, folder_id?, source?, status?}.

  GET    /api/projects/{project_id}/kb-items
      List items visible to the current user (their personal +
      everyone's group items).

  GET    /api/kb-items/{id}
      Detail. Personal items are owner-only.

  PATCH  /api/kb-items/{id}
      Edit. Owner of item OR project owner.

  DELETE /api/kb-items/{id}
      Owner of item OR project owner.

  POST   /api/kb-items/{id}/promote
      Personal → group. Owner of item OR project owner.

  POST   /api/kb-items/{id}/demote
      Group → personal. Project owner only.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    KbItemError,
    KbItemService,
)


router = APIRouter(tags=["kb-items"])


_CODE_TO_STATUS: dict[str, int] = {
    "invalid_title": 400,
    "invalid_scope": 400,
    "invalid_status": 400,
    "invalid_source": 400,
    "content_too_large": 400,
    "not_found": 404,
    "not_a_member": 403,
    "forbidden": 403,
}


def _raise(err: KbItemError) -> None:
    status = err.status or _CODE_TO_STATUS.get(err.code, 400)
    raise HTTPException(status_code=status, detail=err.code)


def _service(request: Request) -> KbItemService:
    return request.app.state.kb_item_service


class CreateKbItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    content_md: str = Field(default="", max_length=200_000)
    scope: str = Field(default="personal", min_length=1, max_length=16)
    folder_id: str | None = Field(default=None, max_length=36)
    source: str = Field(default="manual", min_length=1, max_length=16)
    status: str = Field(default="published", min_length=1, max_length=16)


class UpdateKbItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=500)
    content_md: str | None = Field(default=None, max_length=200_000)
    status: str | None = Field(default=None, min_length=1, max_length=16)
    folder_id: str | None = Field(default=None, max_length=36)


@router.post("/api/projects/{project_id}/kb-items")
async def create_item(
    project_id: str,
    body: CreateKbItemRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.create(
            project_id=project_id,
            owner_user_id=user.id,
            title=body.title,
            content_md=body.content_md,
            scope=body.scope,
            folder_id=body.folder_id,
            source=body.source,
            status=body.status,
        )
    except KbItemError as err:
        _raise(err)


@router.get("/api/projects/{project_id}/kb-items")
async def list_items(
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
    limit: int = 200,
) -> dict[str, Any]:
    service = _service(request)
    try:
        items = await service.list_visible(
            project_id=project_id, viewer_user_id=user.id, limit=limit
        )
        return {"ok": True, "items": items}
    except KbItemError as err:
        _raise(err)


@router.get("/api/kb-items/{item_id}")
async def get_item(
    item_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.get(item_id=item_id, viewer_user_id=user.id)
    except KbItemError as err:
        _raise(err)


@router.patch("/api/kb-items/{item_id}")
async def patch_item(
    item_id: str,
    body: UpdateKbItemRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.update(
            item_id=item_id,
            actor_user_id=user.id,
            title=body.title,
            content_md=body.content_md,
            status=body.status,
            folder_id=body.folder_id,
        )
    except KbItemError as err:
        _raise(err)


@router.delete("/api/kb-items/{item_id}")
async def delete_item(
    item_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.delete(item_id=item_id, actor_user_id=user.id)
    except KbItemError as err:
        _raise(err)


@router.post("/api/kb-items/{item_id}/promote")
async def promote_item(
    item_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.promote_to_group(
            item_id=item_id, actor_user_id=user.id
        )
    except KbItemError as err:
        _raise(err)


@router.post("/api/kb-items/{item_id}/demote")
async def demote_item(
    item_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.demote_to_personal(
            item_id=item_id, actor_user_id=user.id
        )
    except KbItemError as err:
        _raise(err)
