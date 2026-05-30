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
    StreamMemberRepository,
    StreamRepository,
    UserRepository,
    session_scope,
)


class ProjectService:
    def __init__(
        self, sessionmaker: async_sessionmaker, event_bus: EventBus
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        # M5.1 — late-bound MembraneService. When attached, non-owner
        # skill_tags edits + member invites stage for owner review;
        # without it, behavior is the pre-M5.1 direct mutation.
        self._membrane_service = None

    def attach_membrane(self, membrane_service) -> None:
        """Late-bind the Membrane gate for skill_tags / invite. Without
        this attach, mutations stay direct (legacy behavior); production
        wiring in main.py must call attach_membrane for the invariant
        to hold."""
        self._membrane_service = membrane_service

    async def bind_creator(self, *, project_id: str, user_id: str) -> None:
        async with session_scope(self._sessionmaker) as session:
            await ProjectMemberRepository(session).add(
                project_id=project_id, user_id=user_id, role="owner"
            )
            # Phase B (v2): ensure a project stream exists + creator is in it.
            # Idempotent — boot backfill handles pre-existing projects, this
            # covers the just-created case.
            stream_repo = StreamRepository(session)
            stream = await stream_repo.get_for_project(project_id)
            if stream is None:
                stream = await stream_repo.create(
                    type="project", project_id=project_id
                )
            await StreamMemberRepository(session).add(
                stream_id=stream.id,
                user_id=user_id,
                role_in_stream="admin",
            )
        await self._event_bus.emit(
            "project.member_added",
            {"project_id": project_id, "user_id": user_id, "role": "owner"},
        )

    async def add_member(
        self,
        *,
        project_id: str,
        username: str,
        invited_by: str,
        _skip_membrane: bool = False,
    ) -> dict:
        """Add a member to a project.

        M5.1: When `self._membrane_service` is attached and the inviter
        is NOT a project owner, the call stages an IMSuggestion for
        owner approval and returns `{ok=True, deferred=True, ...}`
        instead of mutating. `_skip_membrane=True` is the back-channel
        the accept handler uses (avoids gate recursion). Owners
        auto_merge through to direct add as before.
        """
        # Pre-resolve owner / member state for the gate decision.
        async with session_scope(self._sessionmaker) as session:
            members = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            is_owner = any(
                m.user_id == invited_by and m.role == "owner" for m in members
            )
            owner_ids = [m.user_id for m in members if m.role == "owner"]

        if (
            self._membrane_service is not None
            and not _skip_membrane
            and not is_owner
        ):
            review = await self._membrane_service.review_manual_invite(
                project_id=project_id,
                proposer_user_id=invited_by,
                target_username=username,
                owner_ids=owner_ids,
            )
            if review.action == "reject":
                return {
                    "ok": False,
                    "error": "membrane_rejected",
                    "reason": review.reason,
                }
            if review.action in ("request_review", "request_clarification"):
                return {
                    "ok": True,
                    "deferred": True,
                    "reason": review.reason,
                    "suggestion_id": review.suggestion_id,
                    "user_id": None,
                    "username": username,
                }

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
            # Phase B (v2): join the project stream so the invitee sees it in
            # GET /api/streams and receives broadcast messages.
            stream_repo = StreamRepository(session)
            stream = await stream_repo.get_for_project(project_id)
            if stream is None:
                stream = await stream_repo.create(
                    type="project", project_id=project_id
                )
            await StreamMemberRepository(session).add(
                stream_id=stream.id, user_id=user_row.id
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

    async def set_member_skill_tags(
        self,
        *,
        project_id: str,
        actor_user_id: str,
        target_user_id: str,
        skill_tags: list[str],
        _skip_membrane: bool = False,
    ) -> dict[str, Any]:
        """Set per-project skill_tags for a member.

        M5.1: gates non-owner edits (self or cross) through the
        Membrane. Owner edits auto_merge. `_skip_membrane=True` is
        the accept-handler back-channel.

        Permission rules (consistent with the prior router-level checks):
          * actor must be a project member.
          * cross-edit (actor != target) requires owner role.
          * self-edit by non-owner now goes through review (closes
            the gap that let any member silently grant themselves
            project skill_tags routing then cited as 'role' evidence).
        """
        # Normalize tags consistently with the router's prior shape:
        # lowercase, strip, dedup, drop empties, cap each at 32 chars.
        seen: set[str] = set()
        cleaned: list[str] = []
        for raw in skill_tags or []:
            if not isinstance(raw, str):
                continue
            tag = raw.strip().lower()[:32]
            if not tag or tag in seen:
                continue
            seen.add(tag)
            cleaned.append(tag)

        async with session_scope(self._sessionmaker) as session:
            members = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            actor = next(
                (m for m in members if m.user_id == actor_user_id), None
            )
            if actor is None:
                return {"ok": False, "error": "not_a_project_member"}
            target = next(
                (m for m in members if m.user_id == target_user_id), None
            )
            if target is None:
                return {"ok": False, "error": "member_not_found"}
            is_owner = actor.role == "owner"
            owner_ids = [m.user_id for m in members if m.role == "owner"]

        # Cross-edit by non-owner stays a hard 403 (preserves the
        # existing router-level invariant).
        if actor_user_id != target_user_id and not is_owner:
            return {"ok": False, "error": "owner_or_self_only"}

        if (
            self._membrane_service is not None
            and not _skip_membrane
            and not is_owner
        ):
            review = await self._membrane_service.review_manual_skill_change(
                project_id=project_id,
                proposer_user_id=actor_user_id,
                target_user_id=target_user_id,
                new_skill_tags=cleaned,
                owner_ids=owner_ids,
            )
            if review.action == "reject":
                return {
                    "ok": False,
                    "error": "membrane_rejected",
                    "reason": review.reason,
                }
            if review.action in ("request_review", "request_clarification"):
                return {
                    "ok": True,
                    "deferred": True,
                    "reason": review.reason,
                    "suggestion_id": review.suggestion_id,
                    "user_id": target_user_id,
                    "skill_tags": None,
                }

        # Owner-direct or accept-replay: write through.
        async with session_scope(self._sessionmaker) as session:
            updated = await ProjectMemberRepository(session).set_skill_tags(
                project_id=project_id,
                user_id=target_user_id,
                skill_tags=cleaned,
            )
            if updated is None:
                return {"ok": False, "error": "member_not_found"}
            return {
                "ok": True,
                "user_id": target_user_id,
                "skill_tags": list(updated.skill_tags or []),
            }

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

    async def set_license_tier(
        self, *, project_id: str, user_id: str, tier: str
    ) -> dict:
        """Phase B (v2): mutate a project member's license tier.

        Allowed values: 'full' | 'task_scoped' | 'observer'. Observer loses
        mutation capability in message post / suggestion accept. Task-scoped
        storage lands in v1 but enforcement is v2.
        """
        if tier not in {"full", "task_scoped", "observer"}:
            return {"ok": False, "error": "invalid_tier"}
        from workgraph_persistence import ProjectMemberRow as _PMR
        from sqlalchemy import select as _select

        async with session_scope(self._sessionmaker) as session:
            row = (
                await session.execute(
                    _select(_PMR).where(
                        _PMR.project_id == project_id,
                        _PMR.user_id == user_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return {"ok": False, "error": "not_a_member"}
            row.license_tier = tier
            # Mirror into the stream member role so the stream surface can
            # render observer state without a join. 'admin' stays 'admin'
            # (owner) — we don't demote admins here.
            stream_repo = StreamRepository(session)
            stream = await stream_repo.get_for_project(project_id)
            if stream is not None:
                member_repo = StreamMemberRepository(session)
                sm = await member_repo.get_member(stream.id, user_id)
                if sm is not None and sm.role_in_stream != "admin":
                    sm.role_in_stream = (
                        "observer" if tier == "observer" else "member"
                    )
            await session.flush()
        return {"ok": True, "project_id": project_id, "user_id": user_id, "tier": tier}

    async def members(self, project_id: str) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            memberships = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            if not memberships:
                return []
            user_ids = [m.user_id for m in memberships]
            # Batch-fetch members in one query (was N+1 per member, on the
            # hot /state path). get_many returns rows in arbitrary order.
            rows = await UserRepository(session).get_many(user_ids)
            users = {u.id: u for u in rows}
            return [
                {
                    "user_id": m.user_id,
                    "username": users[m.user_id].username if m.user_id in users else None,
                    "display_name": (
                        users[m.user_id].display_name if m.user_id in users else None
                    ),
                    "role": m.role,
                    "license_tier": m.license_tier,
                    "skill_tags": list(m.skill_tags or []),
                }
                for m in memberships
                if m.user_id in users
            ]
