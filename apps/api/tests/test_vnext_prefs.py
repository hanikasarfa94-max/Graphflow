"""Shell v-Next prefs router tests (E-6 / E-7 / E-9).

Covers:
  * GET returns defaults when nothing is persisted
  * PUT thinking_mode flips the persisted value; GET reads it back
  * PUT auto_dispatch enabled=False persists; enabled=True clears the
    override (default-on semantics)
  * PUT workbench replaces panel order for a stream_kind; empty list
    clears the override
  * Unknown stream_kind / panel_kind in PUT body are 422 (pydantic enum)
  * Invalid thinking_mode in PUT body is 422
  * Auth required — anonymous client gets 401
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _register(client: AsyncClient, username: str, password: str = "hunter22"):
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_get_returns_defaults_when_unset(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "vnext_prefs_default")

    r = await client.get("/api/vnext/prefs")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["thinking_mode"] == "deep"
    assert body["auto_dispatch_streams"] == {}
    layout = body["workbench_layout"]
    assert layout["personal"] == ["tasks", "knowledge", "skills"]
    assert layout["room"] == ["tasks", "knowledge", "requests"]
    assert layout["dm"] == []


@pytest.mark.asyncio
async def test_put_thinking_mode_persists(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "vnext_prefs_thinking")

    r = await client.put(
        "/api/vnext/prefs", json={"thinking_mode": "fast"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["thinking_mode"] == "fast"

    # Re-read.
    r = await client.get("/api/vnext/prefs")
    assert r.json()["thinking_mode"] == "fast"

    # Flip back.
    r = await client.put(
        "/api/vnext/prefs", json={"thinking_mode": "deep"}
    )
    assert r.json()["thinking_mode"] == "deep"


@pytest.mark.asyncio
async def test_put_auto_dispatch_default_on_semantics(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "vnext_prefs_auto_dispatch")

    # Disable for one stream.
    r = await client.put(
        "/api/vnext/prefs",
        json={
            "auto_dispatch": {"stream_id": "stream-abc", "enabled": False}
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["auto_dispatch_streams"] == {"stream-abc": False}

    # Disable for another. First stays.
    r = await client.put(
        "/api/vnext/prefs",
        json={
            "auto_dispatch": {"stream_id": "stream-def", "enabled": False}
        },
    )
    assert r.json()["auto_dispatch_streams"] == {
        "stream-abc": False,
        "stream-def": False,
    }

    # Re-enable stream-abc — the override is removed (default is on).
    r = await client.put(
        "/api/vnext/prefs",
        json={
            "auto_dispatch": {"stream_id": "stream-abc", "enabled": True}
        },
    )
    assert r.json()["auto_dispatch_streams"] == {"stream-def": False}


@pytest.mark.asyncio
async def test_put_workbench_layout_replace_and_clear(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "vnext_prefs_workbench")

    # Replace personal layout. Duplicates are de-duped.
    r = await client.put(
        "/api/vnext/prefs",
        json={
            "workbench": {
                "stream_kind": "personal",
                "panels": ["skills", "tasks", "tasks", "workflow"],
            }
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["workbench_layout"]["personal"] == [
        "skills",
        "tasks",
        "workflow",
    ]
    # Other kinds untouched (still defaults).
    assert r.json()["workbench_layout"]["room"] == [
        "tasks",
        "knowledge",
        "requests",
    ]

    # Empty list clears the override → default returns.
    r = await client.put(
        "/api/vnext/prefs",
        json={"workbench": {"stream_kind": "personal", "panels": []}},
    )
    assert r.json()["workbench_layout"]["personal"] == [
        "tasks",
        "knowledge",
        "skills",
    ]


@pytest.mark.asyncio
async def test_put_invalid_thinking_mode_is_422(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "vnext_prefs_bad_mode")

    r = await client.put(
        "/api/vnext/prefs", json={"thinking_mode": "ultra"}
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_put_invalid_panel_kind_is_422(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "vnext_prefs_bad_panel")

    r = await client.put(
        "/api/vnext/prefs",
        json={
            "workbench": {
                "stream_kind": "personal",
                "panels": ["telemetry"],
            }
        },
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_anonymous_is_401(api_env):
    client, _, _, _, _, _ = api_env
    client.cookies.clear()
    r = await client.get("/api/vnext/prefs")
    assert r.status_code == 401, r.text
    r = await client.put(
        "/api/vnext/prefs", json={"thinking_mode": "fast"}
    )
    assert r.status_code == 401, r.text
