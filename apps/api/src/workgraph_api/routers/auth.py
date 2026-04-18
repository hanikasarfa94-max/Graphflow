from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from workgraph_api.deps import get_auth_service, require_user
from workgraph_api.services import (
    SESSION_COOKIE,
    AuthenticatedUser,
    AuthService,
    InvalidCredentials,
    PasswordTooShort,
    UsernameInvalid,
    UsernameTaken,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    id: str
    username: str
    display_name: str


def _user_dict(user: AuthenticatedUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
    }


def _set_cookie(response: Response, token: str, *, secure: bool) -> None:
    # max_age 7 days to match AuthService session TTL.
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=60 * 60 * 24 * 7,
        path="/",
        httponly=True,
        secure=secure,
        samesite="lax",
    )


@router.post("/register", response_model=UserResponse)
async def post_register(
    body: RegisterRequest,
    response: Response,
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> dict:
    try:
        user = await service.register(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
        )
    except UsernameTaken as e:
        raise HTTPException(status_code=409, detail=str(e))
    except (UsernameInvalid, PasswordTooShort) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Auto-login on register — one fewer step for demo users.
    _, token, _ = await service.login(username=body.username, password=body.password)
    secure = request.url.scheme == "https"
    _set_cookie(response, token, secure=secure)
    return _user_dict(user)


@router.post("/login", response_model=UserResponse)
async def post_login(
    body: LoginRequest,
    response: Response,
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> dict:
    try:
        user, token, _ = await service.login(
            username=body.username, password=body.password
        )
    except InvalidCredentials as e:
        raise HTTPException(status_code=401, detail=str(e))
    secure = request.url.scheme == "https"
    _set_cookie(response, token, secure=secure)
    return _user_dict(user)


@router.post("/logout")
async def post_logout(
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await service.logout(token)
    response.delete_cookie(key=SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def get_me(user: AuthenticatedUser = Depends(require_user)) -> dict:
    return _user_dict(user)
