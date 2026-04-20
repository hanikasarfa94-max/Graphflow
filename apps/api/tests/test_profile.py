"""Observed-profile tallies — compute-on-read, no migrations.

Covers the service in isolation (direct session seeding, deterministic
`now`) plus one HTTP-level sanity check through /api/users/me/profile
so the router wiring + auth guard are exercised.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    AssignmentRow,
    DecisionRow,
    MessageRow,
    ProjectMemberRow,
    ProjectRow,
    RequirementRow,
    RiskRow,
    TaskRow,
    UserRow,
    session_scope,
)

from workgraph_api.services.profile_tallies import compute_profile


def _uid() -> str:
    return str(uuid4())


async def _seed_user(session, *, username: str) -> UserRow:
    row = UserRow(
        id=_uid(),
        username=username,
        display_name=username.title(),
        password_hash="x" * 32,
        password_salt="s" * 16,
    )
    session.add(row)
    await session.flush()
    return row


async def _seed_project(session, *, title: str = "P") -> ProjectRow:
    proj = ProjectRow(id=_uid(), title=title)
    session.add(proj)
    await session.flush()
    req = RequirementRow(id=_uid(), project_id=proj.id, raw_text=title, version=1)
    session.add(req)
    await session.flush()
    return proj


@pytest.mark.asyncio
async def test_compute_profile_counts_messages_within_windows(api_env):
    _, maker, _, _, _, _ = api_env
    now = datetime.now(timezone.utc)

    async with session_scope(maker) as session:
        user = await _seed_user(session, username="alice-prof")
        project = await _seed_project(session, title="Profile-M")
        session.add(
            ProjectMemberRow(
                id=_uid(), project_id=project.id, user_id=user.id, role="owner"
            )
        )
        # 2 messages in the 7d window, 3 more in the 30d window, 1 outside.
        for dt in [now - timedelta(days=1), now - timedelta(days=3)]:
            session.add(
                MessageRow(
                    id=_uid(),
                    project_id=project.id,
                    author_id=user.id,
                    body="hi",
                    created_at=dt,
                )
            )
        for dt in [
            now - timedelta(days=10),
            now - timedelta(days=20),
            now - timedelta(days=29),
        ]:
            session.add(
                MessageRow(
                    id=_uid(),
                    project_id=project.id,
                    author_id=user.id,
                    body="later",
                    created_at=dt,
                )
            )
        # Outside 30d — must not count.
        session.add(
            MessageRow(
                id=_uid(),
                project_id=project.id,
                author_id=user.id,
                body="old",
                created_at=now - timedelta(days=60),
            )
        )
        await session.flush()
        user_id = user.id

    async with session_scope(maker) as session:
        tallies = await compute_profile(session, user_id, now=now)

    assert tallies.observed.messages_posted_7d == 2
    assert tallies.observed.messages_posted_30d == 5
    assert tallies.observed.projects_active == 1
    assert tallies.role_counts == {"owner": 1}
    assert tallies.display_name == "Alice-Prof"
    assert tallies.last_activity_at is not None


@pytest.mark.asyncio
async def test_compute_profile_risks_only_on_owned_projects(api_env):
    _, maker, _, _, _, _ = api_env
    now = datetime.now(timezone.utc)

    async with session_scope(maker) as session:
        owner = await _seed_user(session, username="owner-prof")
        other = await _seed_user(session, username="other-prof")

        owned = await _seed_project(session, title="Owned")
        # User is owner here
        session.add(
            ProjectMemberRow(
                id=_uid(),
                project_id=owned.id,
                user_id=owner.id,
                role="owner",
            )
        )
        # Open risk on owned project — counts.
        req_owned = (
            await session.execute(
                select(RequirementRow).where(
                    RequirementRow.project_id == owned.id
                )
            )
        ).scalar_one()
        session.add(
            RiskRow(
                id=_uid(),
                project_id=owned.id,
                requirement_id=req_owned.id,
                sort_order=0,
                title="scope risk",
                content="",
                severity="high",
                status="open",
            )
        )
        # Closed risk on owned project — does NOT count.
        session.add(
            RiskRow(
                id=_uid(),
                project_id=owned.id,
                requirement_id=req_owned.id,
                sort_order=1,
                title="stale risk",
                content="",
                severity="low",
                status="resolved",
            )
        )

        # Risk on a project the user is only a 'member' of — does NOT count.
        elsewhere = await _seed_project(session, title="Elsewhere")
        session.add(
            ProjectMemberRow(
                id=_uid(),
                project_id=elsewhere.id,
                user_id=owner.id,
                role="member",
            )
        )
        session.add(
            ProjectMemberRow(
                id=_uid(),
                project_id=elsewhere.id,
                user_id=other.id,
                role="owner",
            )
        )
        req_else = (
            await session.execute(
                select(RequirementRow).where(
                    RequirementRow.project_id == elsewhere.id
                )
            )
        ).scalar_one()
        session.add(
            RiskRow(
                id=_uid(),
                project_id=elsewhere.id,
                requirement_id=req_else.id,
                sort_order=0,
                title="not-mine",
                content="",
                severity="medium",
                status="open",
            )
        )
        await session.flush()
        owner_id = owner.id

    async with session_scope(maker) as session:
        tallies = await compute_profile(session, owner_id, now=now)

    assert tallies.observed.risks_owned == 1
    assert tallies.role_counts == {"owner": 1, "member": 1}
    assert tallies.observed.projects_active == 2


@pytest.mark.asyncio
async def test_compute_profile_decisions_and_routings(api_env):
    _, maker, _, _, _, _ = api_env
    now = datetime.now(timezone.utc)

    async with session_scope(maker) as session:
        user = await _seed_user(session, username="dec-prof")
        project = await _seed_project(session, title="Dec")
        session.add(
            ProjectMemberRow(
                id=_uid(),
                project_id=project.id,
                user_id=user.id,
                role="owner",
            )
        )
        await session.flush()

        # A dangling DecisionRow needs a conflict_id. We piggyback on an
        # uuid that doesn't have to resolve — DecisionRow uses ondelete=CASCADE
        # but no FK check on SQLite in-memory unless enforced. To keep the
        # test independent of conflict seeding, write the row directly.
        session.add(
            DecisionRow(
                id=_uid(),
                conflict_id=_uid(),
                project_id=project.id,
                resolver_id=user.id,
                option_index=0,
                rationale="ok",
                created_at=now - timedelta(days=5),
            )
        )
        session.add(
            DecisionRow(
                id=_uid(),
                conflict_id=_uid(),
                project_id=project.id,
                resolver_id=user.id,
                option_index=1,
                rationale="ok2",
                created_at=now - timedelta(days=40),  # outside window
            )
        )

        # Routings (assignments resolved by user).
        req_row = (
            await session.execute(
                select(RequirementRow).where(
                    RequirementRow.project_id == project.id
                )
            )
        ).scalar_one()
        task = TaskRow(
            id=_uid(),
            project_id=project.id,
            requirement_id=req_row.id,
            title="t",
            description="",
            assignee_role="unknown",
        )
        session.add(task)
        await session.flush()
        session.add(
            AssignmentRow(
                id=_uid(),
                project_id=project.id,
                task_id=task.id,
                user_id=user.id,
                active=False,
                resolved_at=now - timedelta(days=2),
            )
        )
        # Unresolved → ignored.
        session.add(
            AssignmentRow(
                id=_uid(),
                project_id=project.id,
                task_id=task.id,
                user_id=user.id,
                active=True,
            )
        )
        await session.flush()
        user_id = user.id

    async with session_scope(maker) as session:
        tallies = await compute_profile(session, user_id, now=now)

    assert tallies.observed.decisions_resolved_30d == 1
    assert tallies.observed.routings_answered_30d == 1


@pytest.mark.asyncio
async def test_compute_profile_empty_user_is_all_zeroes(api_env):
    _, maker, _, _, _, _ = api_env
    async with session_scope(maker) as session:
        user = await _seed_user(session, username="ghost")
        user_id = user.id

    async with session_scope(maker) as session:
        tallies = await compute_profile(session, user_id)
    assert tallies.observed.messages_posted_7d == 0
    assert tallies.observed.messages_posted_30d == 0
    assert tallies.observed.decisions_resolved_30d == 0
    assert tallies.observed.risks_owned == 0
    assert tallies.observed.routings_answered_30d == 0
    assert tallies.observed.projects_active == 0
    assert tallies.role_counts == {}
    assert tallies.last_activity_at is None


@pytest.mark.asyncio
async def test_users_me_profile_requires_auth(api_env):
    client, _, _, _, _, _ = api_env
    # Fresh client — no cookie.
    client.cookies.clear()
    r = await client.get("/api/users/me/profile")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_users_me_profile_returns_tallies(api_env):
    client, _, _, _, _, _ = api_env
    await client.post(
        "/api/auth/register",
        json={"username": "profuser", "password": "hunter22"},
    )
    r = await client.get("/api/users/me/profile")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["display_name"] == "profuser"
    assert body["observed"]["messages_posted_7d"] == 0
    assert body["observed"]["projects_active"] == 0
    assert body["role_counts"] == {}
    assert body["last_activity_at"] is None
