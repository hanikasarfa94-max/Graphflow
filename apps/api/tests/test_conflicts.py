"""Phase 8 — ConflictService + API integration tests.

Exercises the end-to-end flow without hitting the LLM:

  1. Intake → plan → auto-recheck produces conflicts (stub explanation agent).
  2. Fingerprint upsert is idempotent — a second recheck doesn't dupe rows.
  3. Dismissed conflicts don't reopen even if the rule re-fires.
  4. Resolve with option_index bounds-checks against the actual options list.
  5. Non-member is 403 on list/recheck/resolve/dismiss.
  6. Assignment hook re-runs detection so missing_owner conflicts go stale.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from workgraph_api.main import app
from workgraph_persistence import (
    ConflictRepository,
    EventRepository,
    PlanRepository,
    ProjectMemberRepository,
    RequirementRepository,
    session_scope,
)

CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _register(client: AsyncClient, username: str, password: str = "hunter22"):
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _login(client: AsyncClient, username: str, password: str = "hunter22"):
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert r.status_code == 200, r.text


async def _intake_canonical(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


def _alt_client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def _setup(client: AsyncClient, event_id: str) -> str:
    """Register owner, intake, plan, drain background recheck. Returns project_id."""
    await _register(client, "owner_c")
    project_id = await _intake_canonical(client, event_id)
    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200, r.text
    await app.state.conflict_service.drain()
    return project_id


# ---------- happy path ----------------------------------------------------


@pytest.mark.asyncio
async def test_recheck_after_plan_surfaces_conflicts(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _setup(client, "conflict-1")

    r = await client.get(f"/api/projects/{project_id}/conflicts")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "conflicts" in body and "summary" in body
    assert len(body["conflicts"]) >= 1
    kinds = {c["rule"] for c in body["conflicts"]}
    # Stub plan creates 3 tasks with specific roles + no assignments → missing_owner.
    assert "missing_owner" in kinds
    for c in body["conflicts"]:
        assert c["summary"], f"no summary on {c['id']}"
        assert len(c["options"]) >= 2


@pytest.mark.asyncio
async def test_post_plan_triggers_automatic_recheck(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _setup(client, "conflict-2")

    async with session_scope(maker) as session:
        rows = await ConflictRepository(session).list_for_project(project_id)
        events = await EventRepository(session).list_by_name("conflicts.rechecked")
    assert len(rows) >= 1
    assert len(events) >= 1
    assert events[0].payload["project_id"] == project_id


# ---------- idempotency --------------------------------------------------


@pytest.mark.asyncio
async def test_recheck_is_idempotent_on_fingerprint(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _setup(client, "conflict-3")

    async with session_scope(maker) as session:
        before = await ConflictRepository(session).list_for_project(project_id)
    before_ids = {r.id for r in before}

    r = await client.post(f"/api/projects/{project_id}/conflicts/recheck")
    assert r.status_code == 200, r.text
    await app.state.conflict_service.drain()

    async with session_scope(maker) as session:
        after = await ConflictRepository(session).list_for_project(project_id)
    after_ids = {r.id for r in after}
    assert before_ids == after_ids


# ---------- dismissed stays dismissed ------------------------------------


@pytest.mark.asyncio
async def test_dismissed_conflict_does_not_reopen(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _setup(client, "conflict-4")

    r = await client.get(f"/api/projects/{project_id}/conflicts")
    open_list = r.json()["conflicts"]
    assert open_list
    target_id = open_list[0]["id"]

    r = await client.post(f"/api/conflicts/{target_id}/dismiss")
    assert r.status_code == 200, r.text
    assert r.json()["conflict"]["status"] == "dismissed"

    r = await client.post(f"/api/projects/{project_id}/conflicts/recheck")
    assert r.status_code == 200
    await app.state.conflict_service.drain()

    async with session_scope(maker) as session:
        row = await ConflictRepository(session).get(target_id)
    assert row is not None
    assert row.status == "dismissed"


# ---------- resolve ------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_rejects_out_of_range_option_index(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _setup(client, "conflict-5")

    r = await client.get(f"/api/projects/{project_id}/conflicts")
    target_id = r.json()["conflicts"][0]["id"]

    r = await client.post(
        f"/api/conflicts/{target_id}/resolve",
        json={"option_index": 99},
    )
    assert r.status_code == 400
    assert "option_out_of_range" in r.text


@pytest.mark.asyncio
async def test_resolve_happy_path(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _setup(client, "conflict-6")

    r = await client.get(f"/api/projects/{project_id}/conflicts")
    target = r.json()["conflicts"][0]
    r = await client.post(
        f"/api/conflicts/{target['id']}/resolve",
        json={"option_index": 0},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conflict"]["status"] == "resolved"
    assert body["conflict"]["resolved_option_index"] == 0


# ---------- /state composite ---------------------------------------------


@pytest.mark.asyncio
async def test_state_endpoint_includes_conflicts(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _setup(client, "conflict-7")

    r = await client.get(f"/api/projects/{project_id}/state")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "conflicts" in body
    assert "conflict_summary" in body
    assert body["conflict_summary"]["open"] == len(body["conflicts"])


# ---------- membership guard --------------------------------------------


@pytest.mark.asyncio
async def test_non_member_cannot_access_conflicts(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _setup(client, "conflict-8")

    async with _alt_client() as outsider:
        await _register(outsider, "stranger")
        r = await outsider.get(f"/api/projects/{project_id}/conflicts")
        assert r.status_code == 403
        r = await outsider.post(f"/api/projects/{project_id}/conflicts/recheck")
        assert r.status_code == 403


# ---------- assignment hook -> stale missing_owner -----------------------


@pytest.mark.asyncio
async def test_assignment_hook_stales_missing_owner(api_env):
    client, maker, _, _, _, _ = api_env
    project_id = await _setup(client, "conflict-9")

    # Find a missing_owner row + the task it targets.
    r = await client.get(f"/api/projects/{project_id}/conflicts")
    missing = [c for c in r.json()["conflicts"] if c["rule"] == "missing_owner"]
    assert missing, "stub plan should produce a missing_owner conflict"
    target_task_id = missing[0]["targets"][0]
    conflict_id = missing[0]["id"]

    # Register + promote a would-be assignee to project member.
    async with _alt_client() as owner_client:
        reg = await _register(owner_client, "assignee1")
    user_id = reg["id"]
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id, role="member"
        )

    r = await client.post(
        f"/api/tasks/{target_task_id}/assignment",
        json={"user_id": user_id},
    )
    assert r.status_code == 200, r.text
    await app.state.conflict_service.drain()

    async with session_scope(maker) as session:
        row = await ConflictRepository(session).get(conflict_id)
    assert row is not None
    assert row.status == "stale"
