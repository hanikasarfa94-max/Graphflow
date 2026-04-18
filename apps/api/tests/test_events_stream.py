"""Phase 7' SSE event stream tests.

httpx ASGITransport + SSE is hard to drive cleanly in-process, so we split
the test surface in two:
  * HTTP gating tests (auth, membership, project-not-found) — go through
    the full request path and return before streaming, so they work with
    the normal client.
  * Generator-level tests — invoke `_tail_events` directly with a mocked
    Request so we can assert the hello frame + counter bookkeeping without
    fighting an open socket.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from workgraph_api.main import app
from workgraph_api.routers.events_stream import ACTIVE_STREAMS, _tail_events


CANONICAL_TEXT = "Build an event signup page with SMS and export."


async def _register(client, username: str) -> None:
    r = await client.post(
        "/api/auth/register", json={"username": username, "password": "hunter22"}
    )
    assert r.status_code == 200, r.text


async def _intake(client, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200
    return r.json()["project"]["id"]


class _FakeRequest:
    """Minimal stand-in for Starlette Request inside `_tail_events`.

    The generator only calls `await request.is_disconnected()`, which we
    stub so the loop bails out after a handful of ticks.
    """

    def __init__(self) -> None:
        self._ticks = 0

    async def is_disconnected(self) -> bool:
        self._ticks += 1
        return self._ticks > 2


@pytest.mark.asyncio
async def test_stream_requires_auth(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.get("/api/events/stream?project_id=nope")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_stream_rejects_unknown_project(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "creator-sse")
    r = await client.get("/api/events/stream?project_id=does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stream_rejects_non_member(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "creator-sse-2")
    project_id = await _intake(client, "sse-evt-2")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as outsider:
        await _register(outsider, "outsider-sse")
        r = await outsider.get(f"/api/events/stream?project_id={project_id}")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_tail_events_emits_hello_and_tracks_active_counter(api_env):
    _, maker, _, _, _, _ = api_env
    before = ACTIVE_STREAMS["count"]

    # Open the generator manually so we can observe the counter between ticks.
    req = _FakeRequest()
    agen = _tail_events(req, "proj-x", maker).__aiter__()
    first = await agen.__anext__()
    # Counter is now +1 while the generator is paused between yields.
    assert ACTIVE_STREAMS["count"] == before + 1

    # First frame is the hello payload.
    hello = first.decode("utf-8")
    data_line = next(
        line for line in hello.splitlines() if line.startswith("data:")
    )
    payload = json.loads(data_line[len("data:"):].strip())
    assert payload["type"] == "hello"
    assert payload["project_id"] == "proj-x"

    # Close the generator → finally clause runs, counter drops.
    await agen.aclose()
    assert ACTIVE_STREAMS["count"] == before


@pytest.mark.asyncio
async def test_tail_events_replays_db_event_after_append(api_env):
    """EventRepository.append(...) with a project_id payload lands in the tail."""
    _, maker, bus, _, _, _ = api_env
    await bus.emit("test.event", {"project_id": "proj-replay", "hello": "world"})

    req = _FakeRequest()
    agen = _tail_events(req, "proj-replay", maker).__aiter__()
    try:
        frames: list[bytes] = []
        # hello + at least one event — but tolerate ordering via a bounded loop.
        for _ in range(4):
            frames.append(await agen.__anext__())
            body = b"".join(frames).decode("utf-8")
            if "test.event" in body and "proj-replay" in body:
                break
        body = b"".join(frames).decode("utf-8")
        assert "test.event" in body
        assert "proj-replay" in body
    finally:
        await agen.aclose()
