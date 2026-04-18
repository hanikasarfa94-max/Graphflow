"""Project membership + listing.

Phase 7'' binds users to projects via ProjectMemberRow. Creator auto-joins
at intake time via `bind_creator`; additional users are invited via
`add_member`. `list_for_user` powers the /projects page.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    ProjectMemberRepository,
    ProjectRow,
    RequirementRepository,
    UserRepository,
    session_scope,
)


class ProjectService:
    def __init__(
        self, sessionmaker: async_sessionmaker, event_bus: EventBus
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus

    async def bind_creator(self, *, project_id: str, user_id: str) -> None:
        async with session_scope(self._sessionmaker) as session:
            await ProjectMemberRepository(session).add(
                project_id=project_id, user_id=user_id, role="owner"
            )
        await self._event_bus.emit(
            "project.member_added",
            {"project_id": project_id, "user_id": user_id, "role": "owner"},
        )

    async def add_member(
        self, *, project_id: str, username: str, invited_by: str
    ) -> dict:
        async with session_scope(self._sessionmaker) as session:
            user_row = await UserRepository(session).get_by_username(username)
            if user_row is None:
                return {"ok": False, "error": "user_not_found"}
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return {"ok": False, "error": "project_not_found"}
            await ProjectMemberRepository(session).add(
                project_id=project_id, user_id=user_row.id
            )
            member_user_id = user_row.id
        await self._event_bus.emit(
            "project.member_added",
            {
                "project_id": project_id,
                "user_id": member_user_id,
                "username": username,
                "invited_by": invited_by,
            },
        )
        return {"ok": True, "user_id": member_user_id, "username": username}

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            memberships = await ProjectMemberRepository(session).list_for_user(user_id)
            if not memberships:
                return []
            project_ids = [m.project_id for m in memberships]
            projects = list(
                (
                    await session.execute(
                        select(ProjectRow).where(ProjectRow.id.in_(project_ids))
                    )
                )
                .scalars()
                .all()
            )
            req_repo = RequirementRepository(session)
            by_id = {p.id: p for p in projects}
            result: list[dict[str, Any]] = []
            for m in memberships:
                p = by_id.get(m.project_id)
                if p is None:
                    continue
                latest = await req_repo.latest_for_project(p.id)
                result.append(
                    {
                        "id": p.id,
                        "title": p.title,
                        "role": m.role,
                        "requirement_version": latest.version if latest else 0,
                        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                    }
                )
            return result

    async def is_member(self, *, project_id: str, user_id: str) -> bool:
        async with session_scope(self._sessionmaker) as session:
            return await ProjectMemberRepository(session).is_member(
                project_id, user_id
            )

    async def members(self, project_id: str) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            memberships = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            if not memberships:
                return []
            user_ids = [m.user_id for m in memberships]
            user_repo = UserRepository(session)
            users = {}
            for uid in user_ids:
                row = await user_repo.get(uid)
                if row is not None:
                    users[uid] = row
            return [
                {
                    "user_id": m.user_id,
                    "username": users[m.user_id].username if m.user_id in users else None,
                    "display_name": (
                        users[m.user_id].display_name if m.user_id in users else None
                    ),
                    "role": m.role,
                }
                for m in memberships
                if m.user_id in users
            ]
