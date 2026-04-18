from __future__ import annotations

import pytest

from workgraph_persistence import EventRepository, session_scope

CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


@pytest.mark.asyncio
async def test_api_intake_creates_project(api_env):
    client, _maker, _bus, _agent, _clar, _plan = api_env
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": "api-evt-1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "api"
    assert body["source_event_id"] == "api-evt-1"
    assert body["deduplicated"] is False
    assert body["project"]["id"]
    assert body["requirement"]["raw_text"] == CANONICAL_TEXT
    assert body["requirement"]["project_id"] == body["project"]["id"]


@pytest.mark.asyncio
async def test_api_intake_dedup_returns_same_project(api_env):
    client, _, _, _, _, _ = api_env
    r1 = await client.post(
        "/api/intake/message",
        json={"text": "first call", "source_event_id": "api-dup-1"},
    )
    r2 = await client.post(
        "/api/intake/message",
        json={"text": "second call with different text", "source_event_id": "api-dup-1"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["deduplicated"] is False
    assert r2.json()["deduplicated"] is True
    assert r1.json()["project"]["id"] == r2.json()["project"]["id"]
    # Original raw_text preserved — dedup does not overwrite.
    assert r2.json()["requirement"]["raw_text"] == "first call"


@pytest.mark.asyncio
async def test_api_intake_autogenerates_source_event_id(api_env):
    client, _, _, _, _, _ = api_env
    r1 = await client.post("/api/intake/message", json={"text": "first message"})
    r2 = await client.post("/api/intake/message", json={"text": "second message"})
    # No explicit source_event_id → each call generates a unique one → two projects.
    assert r1.json()["project"]["id"] != r2.json()["project"]["id"]
    assert r1.json()["source_event_id"] != r2.json()["source_event_id"]


@pytest.mark.asyncio
async def test_api_intake_rejects_empty_text(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.post("/api/intake/message", json={"text": ""})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


@pytest.mark.asyncio
async def test_feishu_webhook_creates_project(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.post(
        "/api/intake/feishu/webhook",
        json={
            "event_id": "fs-evt-100",
            "message_text": CANONICAL_TEXT,
            "sender_id": "ou_abc",
            "chat_id": "oc_xyz",
            "raw": {"envelope": "simulated"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "feishu"
    assert body["source_event_id"] == "fs-evt-100"


@pytest.mark.asyncio
async def test_feishu_webhook_dedup_on_event_id(api_env):
    client, _, _, _, _, _ = api_env
    payload = {"event_id": "fs-dup-1", "message_text": "hello"}
    r1 = await client.post("/api/intake/feishu/webhook", json=payload)
    r2 = await client.post("/api/intake/feishu/webhook", json=payload)
    assert r1.json()["deduplicated"] is False
    assert r2.json()["deduplicated"] is True
    assert r1.json()["project"]["id"] == r2.json()["project"]["id"]


@pytest.mark.asyncio
async def test_api_and_feishu_produce_identical_domain_shape(api_env):
    """AC: API path and Feishu path produce the same domain result."""
    client, _, _, _, _, _ = api_env
    r_api = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": "parity-api"},
    )
    r_fs = await client.post(
        "/api/intake/feishu/webhook",
        json={"event_id": "parity-fs", "message_text": CANONICAL_TEXT},
    )
    api_body = r_api.json()
    fs_body = r_fs.json()

    # Same top-level keys.
    assert set(api_body.keys()) == set(fs_body.keys())
    # Same project/requirement sub-schemas.
    assert set(api_body["project"].keys()) == set(fs_body["project"].keys())
    assert set(api_body["requirement"].keys()) == set(fs_body["requirement"].keys())
    # Same requirement text → same domain meaning.
    assert api_body["requirement"]["raw_text"] == fs_body["requirement"]["raw_text"]


@pytest.mark.asyncio
async def test_intake_emits_event_with_trace_id(api_env):
    client, maker, _, _, _, _ = api_env
    r = await client.post(
        "/api/intake/message",
        json={"text": "event emission test", "source_event_id": "evt-emit-1"},
        headers={"x-trace-id": "tr-intake-9"},
    )
    assert r.status_code == 200
    async with session_scope(maker) as session:
        rows = await EventRepository(session).list_by_name("intake.received")
    assert len(rows) == 1
    assert rows[0].trace_id == "tr-intake-9"
    assert rows[0].payload["project_id"] == r.json()["project"]["id"]
    assert rows[0].payload["source"] == "api"
    assert rows[0].payload["deduplicated"] is False


@pytest.mark.asyncio
async def test_intake_emits_event_on_dedup_too(api_env):
    """Observers should see every attempt — dedup path still emits."""
    client, maker, _, _, _, _ = api_env
    payload = {"text": "dup emit", "source_event_id": "evt-emit-dup"}
    await client.post("/api/intake/message", json=payload)
    await client.post("/api/intake/message", json=payload)

    async with session_scope(maker) as session:
        rows = await EventRepository(session).list_by_name("intake.received")
    assert len(rows) == 2
    assert rows[0].payload["deduplicated"] is False
    assert rows[1].payload["deduplicated"] is True
