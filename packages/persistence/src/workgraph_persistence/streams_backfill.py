"""Phase B (v2) — stream backfill helper.

Dev SQLite drops + recreates on boot (no Alembic per project convention),
so on every startup we sync the stream primitive with the authoritative
ProjectRow + ProjectMemberRow tables:

  * one StreamRow(type='project') per ProjectRow (1-to-1, idempotent) —
    the shared "team room" (secondary surface in v2)
  * one StreamRow(type='personal') per (project, member) pair — the
    user's private conversation with their sub-agent (Phase L — primary
    surface)
  * one StreamMemberRow per ProjectMemberRow on the team room, with
    role_in_stream mirroring license_tier
  * personal streams contain exactly two members: the owner + the
    shared edge-agent system user
  * any MessageRow with a null stream_id and a populated project_id gets
    its stream_id filled from the ProjectRow's team-room stream

The helper is idempotent: existing StreamRow / StreamMemberRow rows are
reused on re-runs. Called from the API lifespan after `create_all`.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .db import session_scope
from .orm import (
    MessageRow,
    ProjectMemberRow,
    ProjectRow,
    StreamMemberRow,
    StreamRow,
    UserRow,
)
from .repositories import StreamMemberRepository, StreamRepository


# Phase L — one shared system user represents "the sub-agent" across every
# personal stream. Alternative: one edge-agent row per human (so Maya's
# agent has its own UserRow distinct from Raj's). That's more faithful to
# the "one sub-agent per user globally" thesis, but in v1 we collapse it
# to a single system user — the agent's personality is expressed entirely
# by the LLM prompt + user context, not by the DB row. If v2 needs
# per-user agent rows for profile tracking, we migrate then.
EDGE_AGENT_SYSTEM_USER_ID = "edge-agent-system"
_EDGE_AGENT_USERNAME = "edge"
_EDGE_AGENT_DISPLAY_NAME = "🧠 Edge"
# System users cannot authenticate — the password-salt+hash pair is bogus
# (pbkdf2 would never match), and there is no /api/auth/login path that
# uses this id. Kept populated because the UserRow columns are non-null.
_EDGE_AGENT_PASSWORD_HASH = "!system-user-no-login!"
_EDGE_AGENT_PASSWORD_SALT = "0" * 32


async def ensure_edge_agent_system_user(
    sessionmaker: async_sessionmaker,
) -> UserRow:
    """Seed (or fetch) the shared edge-agent system UserRow.

    Idempotent — safe to call on every boot + in tests. The row uses a
    stable id (`EDGE_AGENT_SYSTEM_USER_ID`) so routed signals / personal
    stream members keep their FK targets across DB rebuilds.
    """
    async with session_scope(sessionmaker) as session:
        existing = (
            await session.execute(
                select(UserRow).where(UserRow.id == EDGE_AGENT_SYSTEM_USER_ID)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        row = UserRow(
            id=EDGE_AGENT_SYSTEM_USER_ID,
            username=_EDGE_AGENT_USERNAME,
            display_name=_EDGE_AGENT_DISPLAY_NAME,
            password_hash=_EDGE_AGENT_PASSWORD_HASH,
            password_salt=_EDGE_AGENT_PASSWORD_SALT,
            profile={"kind": "system", "role": "edge-agent"},
            display_language="en",
        )
        session.add(row)
        await session.flush()
        return row


async def backfill_streams_from_projects(
    sessionmaker: async_sessionmaker,
) -> dict[str, int]:
    """Ensure every project has:
      - a team-room stream with all project members
      - one personal stream per member (owner + edge-agent)
      - messages linked to the team-room stream

    Returns a counter dict useful for boot-log observability:
      {
        "streams_created": int,           # team rooms created
        "personal_streams_created": int,  # Phase L
        "members_added": int,
        "messages_linked": int,
      }
    """
    streams_created = 0
    personal_streams_created = 0
    members_added = 0
    messages_linked = 0

    # Phase L: seed the edge-agent system user before wiring personal
    # streams so FK targets for StreamMemberRow resolve.
    await ensure_edge_agent_system_user(sessionmaker)

    async with session_scope(sessionmaker) as session:
        stream_repo = StreamRepository(session)
        member_repo = StreamMemberRepository(session)

        projects = list(
            (await session.execute(select(ProjectRow))).scalars().all()
        )

        for project in projects:
            existing = await stream_repo.get_for_project(project.id)
            if existing is None:
                existing = await stream_repo.create(
                    type="project", project_id=project.id
                )
                streams_created += 1
            stream_id = existing.id

            pm_rows = list(
                (
                    await session.execute(
                        select(ProjectMemberRow).where(
                            ProjectMemberRow.project_id == project.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for pm in pm_rows:
                was_member = await member_repo.is_member(stream_id, pm.user_id)
                role = (
                    "observer"
                    if pm.license_tier == "observer"
                    else "admin"
                    if pm.role == "owner"
                    else "member"
                )
                await member_repo.add(
                    stream_id=stream_id,
                    user_id=pm.user_id,
                    role_in_stream=role,
                )
                if not was_member:
                    members_added += 1

                # Phase L — ensure this (project, user) has a personal stream
                # with the owner + edge-agent as its two members.
                personal = await stream_repo.get_personal_for_user_in_project(
                    user_id=pm.user_id, project_id=project.id
                )
                if personal is None:
                    personal = await stream_repo.create(
                        type="personal",
                        project_id=project.id,
                        owner_user_id=pm.user_id,
                    )
                    personal_streams_created += 1
                owner_was_in = await member_repo.is_member(
                    personal.id, pm.user_id
                )
                await member_repo.add(
                    stream_id=personal.id,
                    user_id=pm.user_id,
                    role_in_stream="admin",
                )
                if not owner_was_in:
                    members_added += 1
                edge_was_in = await member_repo.is_member(
                    personal.id, EDGE_AGENT_SYSTEM_USER_ID
                )
                await member_repo.add(
                    stream_id=personal.id,
                    user_id=EDGE_AGENT_SYSTEM_USER_ID,
                    role_in_stream="member",
                )
                if not edge_was_in:
                    members_added += 1

            # Backfill stream_id on any project messages that haven't been
            # linked yet — covers the demo-seed path where messages get
            # written before the stream exists, or legacy DBs pre-phase-B.
            unlinked = list(
                (
                    await session.execute(
                        select(MessageRow).where(
                            MessageRow.project_id == project.id,
                            MessageRow.stream_id.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for m in unlinked:
                m.stream_id = stream_id
                messages_linked += 1

    return {
        "streams_created": streams_created,
        "personal_streams_created": personal_streams_created,
        "members_added": members_added,
        "messages_linked": messages_linked,
    }
