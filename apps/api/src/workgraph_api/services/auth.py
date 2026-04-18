from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    SessionRepository,
    UserRepository,
    UserRow,
    session_scope,
)

# 200k PBKDF2-sha256 rounds. Strong enough for demo auth, stdlib only — no
# wheel-install hazards on the Aliyun VPS. Bump if the demo surface ever
# starts holding real user data.
_PBKDF2_ROUNDS = 200_000
_SESSION_TTL = timedelta(days=7)
SESSION_COOKIE = "wg_session"


class AuthError(Exception):
    """Base for all auth service errors."""


class UsernameTaken(AuthError):
    pass


class InvalidCredentials(AuthError):
    pass


class UsernameInvalid(AuthError):
    """Username fails shape validation (length / charset)."""


class PasswordTooShort(AuthError):
    pass


@dataclass(slots=True)
class AuthenticatedUser:
    id: str
    username: str
    display_name: str


def _hash_password(password: str, salt: str) -> str:
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        _PBKDF2_ROUNDS,
    )
    return derived.hex()


def _new_salt() -> str:
    return secrets.token_hex(16)


def _new_session_token() -> str:
    return secrets.token_urlsafe(32)


def _valid_username(username: str) -> bool:
    if not (3 <= len(username) <= 32):
        return False
    # Letters, digits, underscore, dash — no spaces, no @.
    return all(c.isalnum() or c in "_-" for c in username)


class AuthService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus

    async def register(
        self, *, username: str, password: str, display_name: str | None = None
    ) -> AuthenticatedUser:
        if not _valid_username(username):
            raise UsernameInvalid(
                "username must be 3–32 chars, letters/digits/underscore/dash only"
            )
        if len(password) < 6:
            raise PasswordTooShort("password must be at least 6 characters")

        salt = _new_salt()
        pwd_hash = _hash_password(password, salt)
        async with session_scope(self._sessionmaker) as session:
            repo = UserRepository(session)
            existing = await repo.get_by_username(username)
            if existing is not None:
                raise UsernameTaken(f"username already taken: {username}")
            try:
                row = await repo.create(
                    username=username,
                    password_hash=pwd_hash,
                    password_salt=salt,
                    display_name=display_name or username,
                )
            except IntegrityError as e:
                await session.rollback()
                raise UsernameTaken(f"username already taken: {username}") from e
            user = AuthenticatedUser(
                id=row.id, username=row.username, display_name=row.display_name
            )

        await self._event_bus.emit(
            "auth.registered",
            {"user_id": user.id, "username": user.username},
        )
        return user

    async def login(
        self, *, username: str, password: str
    ) -> tuple[AuthenticatedUser, str, datetime]:
        async with session_scope(self._sessionmaker) as session:
            user_row = await UserRepository(session).get_by_username(username)
            if user_row is None:
                raise InvalidCredentials("invalid username or password")
            expected = _hash_password(password, user_row.password_salt)
            # Constant-time compare to avoid timing attacks even though this
            # is demo-only — cheap to do right.
            if not hmac.compare_digest(expected, user_row.password_hash):
                raise InvalidCredentials("invalid username or password")

            token = _new_session_token()
            expires_at = datetime.now(timezone.utc) + _SESSION_TTL
            await SessionRepository(session).create(
                token=token, user_id=user_row.id, expires_at=expires_at
            )
            user = AuthenticatedUser(
                id=user_row.id,
                username=user_row.username,
                display_name=user_row.display_name,
            )

        await self._event_bus.emit(
            "auth.login",
            {"user_id": user.id, "username": user.username},
        )
        return user, token, expires_at

    async def logout(self, token: str) -> None:
        async with session_scope(self._sessionmaker) as session:
            await SessionRepository(session).delete(token)

    async def resolve_session(self, token: str) -> AuthenticatedUser | None:
        async with session_scope(self._sessionmaker) as session:
            row = await SessionRepository(session).get(token)
            if row is None:
                return None
            # Treat stored expires_at as UTC even if a driver returns it naive.
            expires_at = row.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                await SessionRepository(session).delete(token)
                return None
            user_row: UserRow | None = await UserRepository(session).get(row.user_id)
            if user_row is None:
                return None
            return AuthenticatedUser(
                id=user_row.id,
                username=user_row.username,
                display_name=user_row.display_name,
            )
