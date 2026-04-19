"""Stream service — Phase B of v2 chat-centered surface.

Wraps StreamRepository / StreamMemberRepository with the DM dedup rule,
stream-list shaping (with unread_count), and the "touch activity" hook
for when a message is posted.

Project streams are auto-backfilled on boot via
`workgraph_persistence.streams_backfill.backfill_streams_from_projects`,
so this service mainly handles:
  * DM creation (with 1:1 dedup)
  * GET /api/streams listing
  * mark-read on a stream (sets last_read_at)

Phase L additions:
  * ensure_personal_stream — lazy creation of a (user, project) personal
    stream; idempotent; used by RoutingService and tests when a new member
    joins a project after boot.
  * post_system_message — bypasses the member-check so the edge-agent
    system user can post into a personal / DM stream.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    MessageRepository,
    ProjectMemberRepository,
    StreamMemberRepository,
    StreamRepository,
    UserRepository,
    session_scope,
)

from .collab_hub import CollabHub


def _stream_frame(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    """Same shape as the project-channel broadcast frames so the WS
    consumer decodes both with a single switch.
    """
    return {"type": kind, "payload": data}


class StreamService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        # `hub` is optional so pre-existing test wiring (which instantiates
        # StreamService directly with two args) keeps working. Prod boot +
        # conftest pass the real hub; when present we broadcast on
        # `/ws/streams/{id}` for every post. When absent the broadcast is
        # a no-op.
        self._hub = hub

    async def create_or_get_dm(
        self, *, user_id: str, other_user_id: str
    ) -> dict[str, Any]:
        """Return the canonical 1:1 DM stream between user_id and
        other_user_id. Creates if none exists, otherwise returns the
        existing one. No-op if user_id == other_user_id.
        """
        if user_id == other_user_id:
            return {"ok": False, "error": "cannot_dm_self"}

        async with session_scope(self._sessionmaker) as session:
            user_repo = UserRepository(session)
            other = await user_repo.get(other_user_id)
            if other is None:
                return {"ok": False, "error": "user_not_found"}

            stream_repo = StreamRepository(session)
            existing = await stream_repo.find_dm_between(user_id, other_user_id)
            if existing is None:
                stream = await stream_repo.create(type="dm", project_id=None)
                member_repo = StreamMemberRepository(session)
                await member_repo.add(stream_id=stream.id, user_id=user_id)
                await member_repo.add(
                    stream_id=stream.id, user_id=other_user_id
                )
                created = True
            else:
                stream = existing
                created = False

            payload = await _shape_stream(session, stream, viewer_id=user_id)

        if created:
            await self._event_bus.emit(
                "stream.created",
                {
                    "stream_id": stream.id,
                    "type": "dm",
                    "members": [user_id, other_user_id],
                },
            )
        return {"ok": True, "created": created, "stream": payload}

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            stream_repo = StreamRepository(session)
            streams = await stream_repo.list_for_user(user_id)
            return [
                await _shape_stream(session, s, viewer_id=user_id)
                for s in streams
            ]

    async def mark_read(
        self, *, stream_id: str, user_id: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            member_repo = StreamMemberRepository(session)
            row = await member_repo.mark_read(
                stream_id=stream_id, user_id=user_id
            )
            if row is None:
                return {"ok": False, "error": "not_a_member"}
            return {
                "ok": True,
                "stream_id": stream_id,
                "user_id": user_id,
                "last_read_at": row.last_read_at.isoformat()
                if row.last_read_at
                else None,
            }

    async def post_message(
        self, *, stream_id: str, author_id: str, body: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            stream_repo = StreamRepository(session)
            stream = await stream_repo.get(stream_id)
            if stream is None:
                return {"ok": False, "error": "stream_not_found"}

            member_repo = StreamMemberRepository(session)
            if not await member_repo.is_member(stream_id=stream_id, user_id=author_id):
                return {"ok": False, "error": "not_a_member"}

            row = await MessageRepository(session).append(
                project_id=stream.project_id,
                author_id=author_id,
                body=body,
                stream_id=stream_id,
            )
            await stream_repo.touch_activity(stream_id)
            author = await UserRepository(session).get(author_id)

        payload = {
            "id": row.id,
            "stream_id": stream_id,
            "project_id": stream.project_id,
            "author_id": author_id,
            "author_username": author.username if author else None,
            "body": body,
            "created_at": row.created_at.isoformat(),
        }
        await self._event_bus.emit("stream.message.posted", payload)
        if self._hub is not None:
            await self._hub.publish_stream(
                stream_id, _stream_frame("message", payload)
            )
        return {"ok": True, **payload}

    # ---- Phase L ---------------------------------------------------------

    async def ensure_personal_stream(
        self, *, user_id: str, project_id: str
    ) -> dict[str, Any]:
        """Idempotently create the (user, project) personal stream with
        owner + edge-agent as members. Returns the stream id.

        Caller must verify the user is a project member — this service
        does not enforce membership (the backfill creates for all members
        unconditionally; RoutingService checks on dispatch).
        """
        async with session_scope(self._sessionmaker) as session:
            stream_repo = StreamRepository(session)
            existing = await stream_repo.get_personal_for_user_in_project(
                user_id=user_id, project_id=project_id
            )
            created = False
            if existing is None:
                existing = await stream_repo.create(
                    type="personal",
                    project_id=project_id,
                    owner_user_id=user_id,
                )
                created = True
            stream_id = existing.id
            member_repo = StreamMemberRepository(session)
            await member_repo.add(
                stream_id=stream_id, user_id=user_id, role_in_stream="admin"
            )
            await member_repo.add(
                stream_id=stream_id,
                user_id=EDGE_AGENT_SYSTEM_USER_ID,
                role_in_stream="member",
            )
        if created:
            await self._event_bus.emit(
                "stream.created",
                {
                    "stream_id": stream_id,
                    "type": "personal",
                    "project_id": project_id,
                    "owner_user_id": user_id,
                },
            )
        return {
            "ok": True,
            "stream_id": stream_id,
            "created": created,
            "project_id": project_id,
            "owner_user_id": user_id,
        }

    async def post_system_message(
        self,
        *,
        stream_id: str,
        author_id: str,
        body: str,
        kind: str = "text",
        linked_id: str | None = None,
    ) -> dict[str, Any]:
        """Post a message into a stream WITHOUT the is_member author guard.

        Used by RoutingService so the edge-agent system user (which is a
        stream member on every personal stream by construction) can post
        a structured card (kind + linked_id). Also used to post
        kind='routed-dm-log' on behalf of a human into the source↔target
        DM — the human is a DM member so the guard would pass, but we go
        through this same helper for consistency + structured columns.

        Returns the same shape as `post_message`, with extra `kind` +
        `linked_id` on the payload for WS consumers.
        """
        async with session_scope(self._sessionmaker) as session:
            stream_repo = StreamRepository(session)
            stream = await stream_repo.get(stream_id)
            if stream is None:
                return {"ok": False, "error": "stream_not_found"}

            row = await MessageRepository(session).append(
                project_id=stream.project_id,
                author_id=author_id,
                body=body,
                stream_id=stream_id,
                kind=kind,
                linked_id=linked_id,
            )
            await stream_repo.touch_activity(stream_id)
            author = await UserRepository(session).get(author_id)

        payload = {
            "id": row.id,
            "stream_id": stream_id,
            "project_id": stream.project_id,
            "author_id": author_id,
            "author_username": author.username if author else None,
            "body": body,
            "kind": kind,
            "linked_id": linked_id,
            "created_at": row.created_at.isoformat(),
        }
        await self._event_bus.emit("stream.message.posted", payload)
        if self._hub is not None:
            await self._hub.publish_stream(
                stream_id, _stream_frame("message", payload)
            )
        return {"ok": True, **payload}

    async def list_messages(
        self, *, stream_id: str, viewer_id: str, limit: int = 100
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            stream_repo = StreamRepository(session)
            stream = await stream_repo.get(stream_id)
            if stream is None:
                return {"ok": False, "error": "stream_not_found"}

            member_repo = StreamMemberRepository(session)
            if not await member_repo.is_member(stream_id=stream_id, user_id=viewer_id):
                return {"ok": False, "error": "not_a_member"}

            rows = await MessageRepository(session).list_for_stream(
                stream_id, limit=limit
            )
            user_repo = UserRepository(session)
            authors: dict[str, str] = {}
            for r in rows:
                if r.author_id not in authors:
                    u = await user_repo.get(r.author_id)
                    if u is not None:
                        authors[r.author_id] = u.username

        messages = [
            {
                "id": r.id,
                "stream_id": stream_id,
                "project_id": r.project_id,
                "author_id": r.author_id,
                "author_username": authors.get(r.author_id),
                "body": r.body,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
        return {"ok": True, "messages": messages}


async def _shape_stream(
    session, stream, *, viewer_id: str
) -> dict[str, Any]:
    """Shared shaping for stream payloads returned by /api/streams and
    POST /api/streams/dm. Includes id, type, project_id, members with
    display names, last_activity_at, and unread_count for the viewer.
    """
    member_repo = StreamMemberRepository(session)
    user_repo = UserRepository(session)

    raw_members = await member_repo.list_for_stream(stream.id)
    members: list[dict[str, Any]] = []
    for m in raw_members:
        u = await user_repo.get(m.user_id)
        if u is None:
            continue
        members.append(
            {
                "user_id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "role_in_stream": m.role_in_stream,
            }
        )
    unread = await member_repo.unread_count(
        stream_id=stream.id, user_id=viewer_id
    )
    return {
        "id": stream.id,
        "type": stream.type,
        "project_id": stream.project_id,
        "owner_user_id": stream.owner_user_id,
        "members": members,
        "last_activity_at": stream.last_activity_at.isoformat()
        if stream.last_activity_at
        else None,
        "created_at": stream.created_at.isoformat()
        if stream.created_at
        else None,
        "unread_count": unread,
    }


__all__ = ["StreamService"]
