"""KbItemService — Phase V manual-write KB primitive.

Solves the QA finding "no way to write a doc, only paste URLs."
KbItemRow is a first-class user-authored note, distinct from the
membrane-ingested signals. The wiki UI will list both.

Scope contract:
  * personal — owner_user_id only. LLM never reads for other users.
  * group    — every project member can read; affects shared pretext.

Permission model (v0):
  * Create:    any project member; default scope=personal.
  * Read list: project members get personal-they-own + all-group.
  * Update:    owner of the item OR project owner (for group-scope
               cleanups). Personal stays editable by owner only.
  * Delete:    owner OR project owner.
  * Promote (personal → group): owner asks; project owner accepts.
    Bare owner-promotes-self is allowed in v0 — frontend can confirm
    "this will affect everyone's pretext" before the call. Phase V.2
    inserts the membrane review step.
  * Demote (group → personal): project owner only.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    KbItemRepository,
    KbItemRow,
    ProjectMemberRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.kb_items")

VALID_SCOPES = frozenset({"personal", "group"})
VALID_STATUSES = frozenset({"draft", "published", "archived"})
VALID_SOURCES = frozenset({"manual", "upload", "llm"})

_MAX_CONTENT_BYTES = 64 * 1024  # 64KB; larger needs blob-store v2.


class KbItemError(Exception):
    """Service-layer error with machine-readable code + optional HTTP
    status hint. Router maps `code` → status via a small table; the
    optional `status_` arg lets callers override for callers that need
    a non-default mapping (e.g. forbidden vs not-found ambiguity)."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        status_: int | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.status = status_


class KbItemService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        *,
        project_id: str,
        owner_user_id: str,
        title: str,
        content_md: str = "",
        scope: str = "personal",
        folder_id: str | None = None,
        source: str = "manual",
        status: str = "published",
    ) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise KbItemError("invalid_title", "title required")
        if len(title) > 500:
            title = title[:500]
        content_md = content_md or ""
        if len(content_md.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise KbItemError("content_too_large", "content > 64KB")
        if scope not in VALID_SCOPES:
            raise KbItemError("invalid_scope")
        if status not in VALID_STATUSES:
            raise KbItemError("invalid_status")
        if source not in VALID_SOURCES:
            raise KbItemError("invalid_source")

        async with session_scope(self._sessionmaker) as session:
            if not await ProjectMemberRepository(session).is_member(
                project_id, owner_user_id
            ):
                raise KbItemError("not_a_member", status_=403)
            row = await KbItemRepository(session).create(
                project_id=project_id,
                owner_user_id=owner_user_id,
                title=title,
                content_md=content_md,
                scope=scope,
                folder_id=folder_id,
                source=source,
                status=status,
            )
            return _serialize(row)

    async def list_visible(
        self, *, project_id: str, viewer_user_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            if not await ProjectMemberRepository(session).is_member(
                project_id, viewer_user_id
            ):
                raise KbItemError("not_a_member", status_=403)
            rows = await KbItemRepository(session).list_visible_for_user(
                project_id=project_id,
                viewer_user_id=viewer_user_id,
                limit=limit,
            )
            return [_serialize(r) for r in rows]

    async def get(
        self, *, item_id: str, viewer_user_id: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            await self._assert_can_read(session, row, viewer_user_id)
            return _serialize(row)

    async def update(
        self,
        *,
        item_id: str,
        actor_user_id: str,
        title: str | None = None,
        content_md: str | None = None,
        status: str | None = None,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        if status is not None and status not in VALID_STATUSES:
            raise KbItemError("invalid_status")
        if content_md is not None and len(content_md.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise KbItemError("content_too_large")
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            await self._assert_can_edit(session, row, actor_user_id)
            updated = await KbItemRepository(session).update(
                item_id=item_id,
                title=title,
                content_md=content_md,
                status=status,
                folder_id=folder_id,
            )
            return _serialize(updated)

    async def delete(
        self, *, item_id: str, actor_user_id: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            await self._assert_can_edit(session, row, actor_user_id)
            await KbItemRepository(session).delete(item_id)
            return {"ok": True, "deleted_id": item_id}

    async def promote_to_group(
        self, *, item_id: str, actor_user_id: str
    ) -> dict[str, Any]:
        """Personal → group. v0: owner-self-promote allowed; project owner
        also allowed. Frontend should confirm intent before calling."""
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            if row.scope == "group":
                return _serialize(row)
            is_owner_of_item = row.owner_user_id == actor_user_id
            is_project_owner = await _is_project_owner(
                session, row.project_id, actor_user_id
            )
            if not (is_owner_of_item or is_project_owner):
                raise KbItemError("forbidden", status_=403)
            updated = await KbItemRepository(session).set_scope(
                item_id=item_id, scope="group"
            )
            return _serialize(updated)

    async def demote_to_personal(
        self, *, item_id: str, actor_user_id: str
    ) -> dict[str, Any]:
        """Group → personal. Project owner only — protects shared
        pretext from accidental loss when the original author leaves."""
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            if row.scope == "personal":
                return _serialize(row)
            if not await _is_project_owner(
                session, row.project_id, actor_user_id
            ):
                raise KbItemError("forbidden", status_=403)
            updated = await KbItemRepository(session).set_scope(
                item_id=item_id, scope="personal"
            )
            return _serialize(updated)

    # ---- internals -----------------------------------------------------

    async def _assert_can_read(
        self, session, row: KbItemRow, viewer_user_id: str
    ) -> None:
        if not await ProjectMemberRepository(session).is_member(
            row.project_id, viewer_user_id
        ):
            raise KbItemError("not_a_member", status_=403)
        if row.scope == "personal" and row.owner_user_id != viewer_user_id:
            raise KbItemError("forbidden", status_=403)

    async def _assert_can_edit(
        self, session, row: KbItemRow, actor_user_id: str
    ) -> None:
        if row.owner_user_id == actor_user_id:
            return
        if await _is_project_owner(session, row.project_id, actor_user_id):
            return
        raise KbItemError("forbidden", status_=403)


async def _is_project_owner(session, project_id: str, user_id: str) -> bool:
    members = await ProjectMemberRepository(session).list_for_project(
        project_id
    )
    return any(m.user_id == user_id and m.role == "owner" for m in members)


def _serialize(row: KbItemRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "folder_id": row.folder_id,
        "owner_user_id": row.owner_user_id,
        "scope": row.scope,
        "title": row.title,
        "content_md": row.content_md,
        "status": row.status,
        "source": row.source,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


__all__ = [
    "KbItemService",
    "KbItemError",
    "VALID_SCOPES",
    "VALID_STATUSES",
    "VALID_SOURCES",
]
