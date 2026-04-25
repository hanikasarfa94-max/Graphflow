"""Organization (Workspace) endpoints — minimum-viable tier above project.

Design notes:
  * `slug` is the URL key for everything except create. The path in the
    frontend is `/workspaces/{slug}` — mirror that here so the two
    stay legible together.
  * All endpoints require an authenticated user. Authorization is
    delegated to the service layer (which surfaces machine-readable
    `OrganizationError.code` strings that we map to HTTP here).
  * Response shapes are dumb dicts — we're not introducing pydantic
    output models yet because the v1 surface is tiny and matches the
    existing project router's pattern.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import require_user
from workgraph_api.services import (
    AuthenticatedUser,
    OrganizationError,
    OrganizationService,
)

router = APIRouter(prefix="/api/organizations", tags=["organizations"])


# ---- Request bodies --------------------------------------------------------


class CreateOrganizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=3, max_length=64)
    description: str | None = Field(default=None, max_length=4000)


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=32)
    role: str = Field(default="member", min_length=1, max_length=16)


class UpdateRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(min_length=1, max_length=16)


# ---- Error translation -----------------------------------------------------


def _raise_from(err: OrganizationError) -> None:
    """Map service-layer codes to HTTP. Kept small — we don't try to
    exhaust every possible code, just the ones the v1 surface raises."""
    code_to_status = {
        "duplicate_slug": 409,
        "invalid_slug": 400,
        "invalid_name": 400,
        "invalid_description": 400,
        "invalid_role": 400,
        "organization_not_found": 404,
        "project_not_found": 404,
        "member_not_found": 404,
        "user_not_found": 404,
        "forbidden": 403,
        "last_owner": 400,
    }
    status = code_to_status.get(err.code, 400)
    # Surface the code as the HTTP `detail` string. The global exception
    # handler (main.py:_http_handler) wraps it as
    # `{code, message: <code>, trace_id, details}` — frontend i18n keys
    # off `r.json()["message"]`. Same convention as the gated-proposals
    # and other v1 routers.
    raise HTTPException(status_code=status, detail=err.code)


def _service(request: Request) -> OrganizationService:
    return request.app.state.organization_service


# ---- Endpoints -------------------------------------------------------------


@router.post("")
async def create_organization(
    body: CreateOrganizationRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.create_organization(
            name=body.name,
            slug=body.slug,
            owner_user_id=user.id,
            description=body.description,
        )
    except OrganizationError as err:
        _raise_from(err)
        raise  # unreachable — keeps type-checker happy


@router.get("")
async def list_organizations(
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> list[dict[str, Any]]:
    service = _service(request)
    return await service.list_for_user(user.id)


@router.get("/{slug}")
async def get_organization(
    slug: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.get_by_slug(slug, viewer_user_id=user.id)
    except OrganizationError as err:
        _raise_from(err)
        raise


@router.get("/{slug}/members")
async def list_members(
    slug: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> list[dict[str, Any]]:
    service = _service(request)
    try:
        return await service.list_members(slug=slug, viewer_user_id=user.id)
    except OrganizationError as err:
        _raise_from(err)
        raise


@router.post("/{slug}/invite")
async def invite_member(
    slug: str,
    body: InviteRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.invite_member(
            slug=slug,
            inviter_user_id=user.id,
            target_username=body.username,
            role=body.role,
        )
    except OrganizationError as err:
        _raise_from(err)
        raise


@router.patch("/{slug}/members/{user_id}")
async def update_member_role(
    slug: str,
    user_id: str,
    body: UpdateRoleRequest,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.update_member_role(
            slug=slug,
            actor_user_id=user.id,
            target_user_id=user_id,
            new_role=body.role,
        )
    except OrganizationError as err:
        _raise_from(err)
        raise


@router.delete("/{slug}/members/{user_id}")
async def remove_member(
    slug: str,
    user_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.remove_member(
            slug=slug,
            actor_user_id=user.id,
            target_user_id=user_id,
        )
    except OrganizationError as err:
        _raise_from(err)
        raise


@router.post("/{slug}/projects/{project_id}/attach")
async def attach_project(
    slug: str,
    project_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    service = _service(request)
    try:
        return await service.attach_project(
            slug=slug,
            project_id=project_id,
            actor_user_id=user.id,
        )
    except OrganizationError as err:
        _raise_from(err)
        raise
