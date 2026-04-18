from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from workgraph_api.services import (
    SESSION_COOKIE,
    AuthenticatedUser,
    AuthService,
    ClarificationService,
    IntakeService,
    PlanningService,
)


def get_intake_service(request: Request) -> IntakeService:
    return request.app.state.intake_service


def get_clarification_service(request: Request) -> ClarificationService:
    return request.app.state.clarification_service


def get_planning_service(request: Request) -> PlanningService:
    return request.app.state.planning_service


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def get_collab_hub(request: Request):
    return request.app.state.collab_hub


def get_im_service(request: Request):
    return request.app.state.im_service


def get_assignment_service(request: Request):
    return request.app.state.assignment_service


def get_comment_service(request: Request):
    return request.app.state.comment_service


def get_notification_service(request: Request):
    return request.app.state.notification_service


def get_project_service(request: Request):
    return request.app.state.project_service


async def maybe_user(
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> AuthenticatedUser | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return await service.resolve_session(token)


async def require_user(
    user: AuthenticatedUser | None = Depends(maybe_user),
) -> AuthenticatedUser:
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user
