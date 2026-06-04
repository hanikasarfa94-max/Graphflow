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


@pytest.mark.asyncio
async def test_routing_events_inspection_endpoint(api_env):
    client, maker, *_ = api_env

    # Fresh DB: endpoint returns the four buckets, all empty.
    r0 = await client.get("/api/demo/routing-events")
    assert r0.status_code == 200, r0.text
    assert set(r0.json().keys()) == {
        "routing.dispatched",
        "routing.opened",
        "routing.replied",
        "routing.accepted",
    }

    seed = (await client.post("/api/demo/seed-broker")).json()
    # Log the test client in as the sender, then dispatch a routed signal.
    await client.post(
        "/api/auth/login",
        json={"username": seed["sender_username"], "password": seed["password"]},
    )
    disp = await client.post(
        "/api/routing/dispatch",
        json={
            "target_user_id": seed["recipient_id"],
            "project_id": seed["project_id"],
            "framing": "demo routing ask",
            "background": [],
            "options": [
                {
                    "id": "ok",
                    "label": "Sounds good",
                    "kind": "action",
                    "background": "",
                    "reason": "r",
                    "tradeoff": "t",
                    "weight": 0.6,
                }
            ],
        },
    )
    assert disp.status_code == 200, disp.text

    events = (await client.get("/api/demo/routing-events")).json()
    assert events["routing.dispatched"]["count"] >= 1
    last = events["routing.dispatched"]["recent"][-1]
    assert last["payload"]["signal_id"]
    assert last["created_at"]
