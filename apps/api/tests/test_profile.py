"""Phase B (v2) — user profile tests.

North-star §"Profile as first-class primitive": UserRow gains a JSON
`profile` column (declared_abilities / role_hints / signal_tally) and a
`display_language` column. GET /api/users/me returns both; PATCH updates
a subset.
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
    return r.json()


# ---------- GET /api/users/me defaults ----------------------------------


@pytest.mark.asyncio
async def test_get_me_returns_profile_defaults(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "profile_reader")

    r = await client.get("/api/users/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == "profile_reader"
    assert body["display_language"] == "en"
    # Profile starts empty; shape stays stable whether the dict is empty
    # or has default keys.
    assert "profile" in body
    assert isinstance(body["profile"], dict)


# ---------- PATCH declared_abilities ------------------------------------


@pytest.mark.asyncio
async def test_patch_me_sets_declared_abilities(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "profile_writer")

    patch = await client.patch(
        "/api/users/me",
        json={"declared_abilities": ["design", "pm", "qa"]},
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["profile"]["declared_abilities"] == ["design", "pm", "qa"]

    # Round-trip through GET to confirm persistence.
    me = await client.get("/api/users/me")
    assert me.status_code == 200
    assert me.json()["profile"]["declared_abilities"] == ["design", "pm", "qa"]


@pytest.mark.asyncio
async def test_patch_me_merges_role_hints_into_profile(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "profile_merger")

    # Set declared_abilities first.
    await client.patch(
        "/api/users/me",
        json={"declared_abilities": ["frontend"]},
    )
    # Then add role_hints in a separate call — declared_abilities must stay.
    r = await client.patch(
        "/api/users/me",
        json={"role_hints": ["tech-lead"]},
    )
    assert r.status_code == 200, r.text
    profile = r.json()["profile"]
    assert profile["declared_abilities"] == ["frontend"]
    assert profile["role_hints"] == ["tech-lead"]


# ---------- display_language ---------------------------------------------


@pytest.mark.asyncio
async def test_display_language_persists(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "lang_picker")

    r = await client.patch(
        "/api/users/me",
        json={"display_language": "zh"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["display_language"] == "zh"

    # GET confirms persistence across requests.
    me = await client.get("/api/users/me")
    assert me.json()["display_language"] == "zh"


@pytest.mark.asyncio
async def test_invalid_display_language_rejected(api_env):
    client, _, _, _, _, _ = api_env
    await _register(client, "lang_invalid")

    r = await client.patch(
        "/api/users/me",
        json={"display_language": "klingon"},
    )
    # 422 matches FastAPI validation convention for rejected enum values.
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_patch_me_requires_auth(api_env):
    client, _, _, _, _, _ = api_env
    client.cookies.clear()
    r = await client.patch(
        "/api/users/me",
        json={"declared_abilities": ["stealth-mode"]},
    )
    assert r.status_code == 401
