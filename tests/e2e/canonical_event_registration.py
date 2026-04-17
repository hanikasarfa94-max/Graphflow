"""Canonical E2E fixture — per PLAN.md decision 3B.

This fixture starts with the canonical event-registration scenario from
prompt-contracts.md §16.1 and evolves across phases:

  Phase 2 (here): intake creates project + requirement, event emitted
                  with trace_id, dedup works across both paths.
  Phase 3: Requirement Agent parses 4 scope items + deadline, confidence >0.7
  Phase 4: ≥1 open_question generated, routed to correct Feishu channel
  Phase 5: graph entities (Goal/Deliverable/Constraint/Risk) present
  Phase 6+: planning, sync, conflict, decision, delivery assertions chained

Every subsequent agent phase APPENDS its assertion block — this file is the
single end-to-end contract that proves the demo path works end-to-end.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from workgraph_agents import RequirementAgent
from workgraph_agents.testing import StubRequirementAgent
from workgraph_domain import EventBus
from workgraph_persistence import (
    EventRepository,
    build_engine,
    build_sessionmaker,
    create_all,
    drop_all,
    session_scope,
)

from workgraph_api.main import app
from workgraph_api.services import IntakeService

CANONICAL_REQUIREMENT_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _make_env(agent):
    engine = build_engine("sqlite+aiosqlite:///:memory:")
    await create_all(engine)
    maker = build_sessionmaker(engine)
    bus = EventBus(maker)
    service = IntakeService(maker, bus, agent=agent)

    app.state.engine = engine
    app.state.sessionmaker = maker
    app.state.event_bus = bus
    app.state.intake_service = service

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    return client, maker, engine


@pytest_asyncio.fixture
async def canonical_env():
    """Phase 2 plumbing tests — stub agent, no network."""
    client, maker, engine = await _make_env(StubRequirementAgent())
    async with client:
        yield client, maker
    await drop_all(engine)
    await engine.dispose()


@pytest_asyncio.fixture
async def canonical_env_live():
    """Phase 3+ E2E — real RequirementAgent against DeepSeek."""
    client, maker, engine = await _make_env(RequirementAgent())
    async with client:
        yield client, maker
    await drop_all(engine)
    await engine.dispose()


skip_if_no_key = pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY not set — live canonical E2E requires DeepSeek",
)


# ---------- Phase 2 assertions --------------------------------------------


@pytest.mark.asyncio
async def test_canonical_intake_via_api_path(canonical_env):
    client, maker = canonical_env
    trace_id = "trace-canonical-api"

    resp = await client.post(
        "/api/intake/message",
        json={
            "text": CANONICAL_REQUIREMENT_TEXT,
            "source_event_id": "canonical-api-1",
        },
        headers={"x-trace-id": trace_id},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "api"
    assert body["deduplicated"] is False
    assert body["requirement"]["raw_text"] == CANONICAL_REQUIREMENT_TEXT
    assert resp.headers.get("x-trace-id") == trace_id

    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("intake.received")
    assert len(events) == 1
    assert events[0].trace_id == trace_id
    assert events[0].payload["project_id"] == body["project"]["id"]


@pytest.mark.asyncio
async def test_canonical_intake_via_feishu_path(canonical_env):
    client, maker = canonical_env

    resp = await client.post(
        "/api/intake/feishu/webhook",
        json={
            "event_id": "canonical-fs-1",
            "message_text": CANONICAL_REQUIREMENT_TEXT,
            "sender_id": "ou_canonical_user",
            "chat_id": "oc_canonical_chat",
            "raw": {"_demo": "feishu-envelope-placeholder"},
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "feishu"
    assert body["requirement"]["raw_text"] == CANONICAL_REQUIREMENT_TEXT

    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("intake.received")
    assert len(events) == 1
    assert events[0].payload["source"] == "feishu"


@pytest.mark.asyncio
async def test_canonical_both_paths_same_domain_shape(canonical_env):
    """Core AC for Phase 2: API path and Feishu path produce the same domain result."""
    client, _ = canonical_env

    r_api = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_REQUIREMENT_TEXT, "source_event_id": "canonical-parity-api"},
    )
    r_fs = await client.post(
        "/api/intake/feishu/webhook",
        json={"event_id": "canonical-parity-fs", "message_text": CANONICAL_REQUIREMENT_TEXT},
    )
    api_body = r_api.json()
    fs_body = r_fs.json()

    assert set(api_body.keys()) == set(fs_body.keys())
    assert set(api_body["project"].keys()) == set(fs_body["project"].keys())
    assert set(api_body["requirement"].keys()) == set(fs_body["requirement"].keys())
    assert api_body["requirement"]["raw_text"] == fs_body["requirement"]["raw_text"]


@pytest.mark.asyncio
async def test_canonical_dedup_on_both_paths(canonical_env):
    client, _ = canonical_env

    # Two identical API calls → one project.
    api_payload = {"text": CANONICAL_REQUIREMENT_TEXT, "source_event_id": "canonical-dedup-api"}
    r1 = await client.post("/api/intake/message", json=api_payload)
    r2 = await client.post("/api/intake/message", json=api_payload)
    assert r1.json()["project"]["id"] == r2.json()["project"]["id"]
    assert r2.json()["deduplicated"] is True

    # Two identical Feishu calls → one project.
    fs_payload = {"event_id": "canonical-dedup-fs", "message_text": CANONICAL_REQUIREMENT_TEXT}
    f1 = await client.post("/api/intake/feishu/webhook", json=fs_payload)
    f2 = await client.post("/api/intake/feishu/webhook", json=fs_payload)
    assert f1.json()["project"]["id"] == f2.json()["project"]["id"]
    assert f2.json()["deduplicated"] is True


# ---------- Phase 3 assertions — live Requirement Agent --------------------
# Marked `eval` so default `uv run pytest` skips them; CI + devs opt in with
# `-m eval`. Decision 3B: canonical fixture asserts 4 scope items, deadline,
# confidence >0.7 on the real agent against DeepSeek.


@pytest.mark.eval
@skip_if_no_key
@pytest.mark.asyncio
async def test_canonical_requirement_parse_phase3(canonical_env_live):
    client, maker = canonical_env_live
    trace_id = "trace-canonical-phase3"

    resp = await client.post(
        "/api/intake/message",
        json={
            "text": CANONICAL_REQUIREMENT_TEXT,
            "source_event_id": "canonical-phase3-1",
        },
        headers={"x-trace-id": trace_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    req = body["requirement"]

    # Parse landed on the requirement row.
    assert req["parse_outcome"] == "ok"
    assert req["parsed_at"] is not None
    parsed = req["parsed_json"]
    assert parsed is not None

    # Core Phase 3 AC (3B):
    scope = parsed["scope_items"]
    assert len(scope) >= 4, f"expected >=4 scope items, got {len(scope)}: {scope}"
    scope_lower = " ".join(s.lower() for s in scope)
    for must_mention in ("invitation", "phone", "export", "conversion"):
        assert must_mention in scope_lower, (
            f"scope missing {must_mention!r}: {scope}"
        )
    assert parsed["deadline"] is not None
    assert parsed["confidence"] > 0.7

    # requirement.parsed event emitted with the right trace_id.
    async with session_scope(maker) as session:
        events = await EventRepository(session).list_by_name("requirement.parsed")
    assert len(events) == 1
    assert events[0].trace_id == trace_id
    assert events[0].payload["project_id"] == body["project"]["id"]
    assert events[0].payload["outcome"] == "ok"
    assert events[0].payload["scope_count"] == len(scope)
