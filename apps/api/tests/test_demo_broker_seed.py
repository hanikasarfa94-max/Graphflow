"""Integration test for the dev-only broker demo seed endpoint."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from workgraph_persistence import (
    ProjectMemberRow,
    StreamRow,
    session_scope,
)


@pytest.mark.asyncio
async def test_seed_broker_creates_two_user_project(api_env):
    client, maker, *_ = api_env

    r = await client.post("/api/demo/seed-broker")
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["project_id"]
    assert data["sender_username"] == "demo_sender"
    assert data["recipient_username"] == "demo_recipient"
    assert data["sender_id"] and data["recipient_id"]
    assert data["sender_id"] != data["recipient_id"]

    project_id = data["project_id"]
    recipient_id = data["recipient_id"]

    async with session_scope(maker) as session:
        # Recipient is a member with the seeded skill tags (grounding).
        member = (
            await session.execute(
                select(ProjectMemberRow).where(
                    ProjectMemberRow.project_id == project_id,
                    ProjectMemberRow.user_id == recipient_id,
                )
            )
        ).scalar_one()
        assert "backend" in (member.skill_tags or [])

        # Both users have a personal stream (backfill ran).
        personals = list(
            (
                await session.execute(
                    select(StreamRow).where(
                        StreamRow.project_id == project_id,
                        StreamRow.type == "personal",
                    )
                )
            )
            .scalars()
            .all()
        )
        owners = {s.owner_user_id for s in personals}
        assert data["sender_id"] in owners
        assert recipient_id in owners
