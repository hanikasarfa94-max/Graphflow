"""Phase R — RenderService + API integration tests.

Covers:
  1. Happy path — GET postmortem generates on first call, caches on second.
  2. Regenerate endpoint evicts the cache entry and produces a fresh doc
     with a newer `generated_at` timestamp.
  3. Postmortem citations reference real decision IDs from the stubbed
     context (agent stub emits `**D-<id>**` bullets only for real ids).
  4. Handoff endpoint returns the target user's doc; the target must be
     a project member.
  5. Non-member → 403 on both postmortem and handoff endpoints.
"""
from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from workgraph_api.main import app

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


async def _intake(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


async def _setup(client: AsyncClient, event_id: str, owner: str) -> str:
    await _register(client, owner)
    project_id = await _intake(client, event_id)
    r = await client.post(f"/api/projects/{project_id}/plan")
    assert r.status_code == 200, r.text
    return project_id


def _alt_client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------- postmortem happy path + cache -----------------------------


@pytest.mark.asyncio
async def test_postmortem_generates_and_caches(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _setup(client, "render-1", "owner_rnd1")

    r1 = await client.get(f"/api/projects/{project_id}/renders/postmortem")
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["kind"] == "postmortem"
    assert body1["doc"]["title"]
    assert len(body1["doc"]["sections"]) == 5
    first_generated = body1["generated_at"]

    # Agent should only have been called once; second GET is cache hit.
    render_agent = app.state.render_agent
    call_count_after_first = len(render_agent.postmortem_calls)

    r2 = await client.get(f"/api/projects/{project_id}/renders/postmortem")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["generated_at"] == first_generated
    assert len(render_agent.postmortem_calls) == call_count_after_first


# ---------- regenerate evicts cache -----------------------------------


@pytest.mark.asyncio
async def test_postmortem_regenerate_evicts_cache(api_env):
    client, _, _, _, _, _ = api_env
    project_id = await _setup(client, "render-2", "owner_rnd2")

    r1 = await client.get(f"/api/projects/{project_id}/renders/postmortem")
    assert r1.status_code == 200
    first_generated = r1.json()["generated_at"]

    # Small sleep to let the ISO timestamp advance on systems whose
    # datetime.now resolution rounds to the nearest microsecond.
    await asyncio.sleep(0.01)

    render_agent = app.state.render_agent
    before_regen = len(render_agent.postmortem_calls)
    r2 = await client.post(
        f"/api/projects/{project_id}/renders/postmortem/regenerate"
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["generated_at"] != first_generated
    assert len(render_agent.postmortem_calls) == before_regen + 1


# ---------- decision citation grounding -------------------------------


@pytest.mark.asyncio
async def test_postmortem_cites_only_real_decision_ids(api_env):
    """The agent stub emits `**D-<id>**` bullets for every decision row
    it receives — those ids must match the rows the DecisionRepository
    actually has for the project.
    """
    client, maker, _, _, _, _ = api_env
    project_id = await _setup(client, "render-3", "owner_rnd3")

    r = await client.get(f"/api/projects/{project_id}/renders/postmortem")
    assert r.status_code == 200
    body = r.json()

    # Collect the decisions section text and cross-check every cited id
    # exists in the context the agent was handed.
    key_section = next(
        s for s in body["doc"]["sections"] if s["heading"] == "Key decisions (lineage)"
    )
    rendered_text = key_section["body_markdown"]

    render_agent = app.state.render_agent
    assert render_agent.postmortem_calls, "agent must have been called"
    last_ctx = render_agent.postmortem_calls[-1]
    real_ids = {d["id"] for d in (last_ctx.get("decisions") or [])}

    # Every **D-<id>** citation in rendered text must be a real id.
    import re

    for match in re.findall(r"\*\*D-([A-Za-z0-9_\-]+)\*\*", rendered_text):
        assert match in real_ids, (
            f"rendered cite D-{match} not in real decision ids {real_ids}"
        )


# ---------- handoff happy path ----------------------------------------


@pytest.mark.asyncio
async def test_handoff_renders_for_project_member(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "owner_rnd4")
    project_id = await _intake(client, "render-4")

    # Get owner's user id via /auth/me.
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    owner_id = me.json()["id"]

    r = await client.get(
        f"/api/projects/{project_id}/renders/handoff/{owner_id}"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "handoff"
    assert body["user_id"] == owner_id
    assert len(body["doc"]["sections"]) == 6


# ---------- membership guard ------------------------------------------


@pytest.mark.asyncio
async def test_non_member_cannot_read_renders(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "owner_rnd5")
    project_id = await _intake(client, "render-5")
    me = await client.get("/api/auth/me")
    owner_id = me.json()["id"]

    async with _alt_client() as outsider:
        await _register(outsider, "stranger_rnd5")
        r = await outsider.get(
            f"/api/projects/{project_id}/renders/postmortem"
        )
        assert r.status_code == 403
        r = await outsider.post(
            f"/api/projects/{project_id}/renders/postmortem/regenerate"
        )
        assert r.status_code == 403
        r = await outsider.get(
            f"/api/projects/{project_id}/renders/handoff/{owner_id}"
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_handoff_target_must_be_project_member(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "owner_rnd6")
    project_id = await _intake(client, "render-6")

    # A second user exists globally but is NOT a project member.
    async with _alt_client() as other:
        await _register(other, "outsider_rnd6")
        me = await other.get("/api/auth/me")
        stranger_id = me.json()["id"]

    r = await client.get(
        f"/api/projects/{project_id}/renders/handoff/{stranger_id}"
    )
    # Current owner is a member, but the handoff target (stranger_id) is
    # not — should 403.
    assert r.status_code == 403
