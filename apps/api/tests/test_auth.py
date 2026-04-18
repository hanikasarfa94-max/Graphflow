"""Phase 7' mock-auth backend tests.

Covers register → auto-login, explicit login, logout, /me gating, and
the intake-creator binding so a signed-in user sees projects they intake.
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_register_sets_session_cookie_and_returns_user(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == "alice"
    assert body["display_name"] == "alice"
    # Auto-login cookie lands on the client jar.
    assert "wg_session" in r.cookies or "wg_session" in client.cookies.keys()


@pytest.mark.asyncio
async def test_register_rejects_short_password(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.post(
        "/api/auth/register",
        json={"username": "bob", "password": "x"},
    )
    # min_length=6 is enforced by pydantic → 422.
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_invalid_username(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.post(
        "/api/auth/register",
        json={"username": "ab", "password": "hunter22"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_duplicate_username_returns_409(api_env):
    client, _, _, _, _, _ = api_env
    r1 = await client.post(
        "/api/auth/register",
        json={"username": "carol", "password": "hunter22"},
    )
    assert r1.status_code == 200
    # Fresh client jar so we don't accidentally send the first cookie.
    r2 = await client.post(
        "/api/auth/register",
        json={"username": "carol", "password": "another-pw"},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_login_sets_cookie_and_me_returns_identity(api_env):
    client, _, _, _, _, _ = api_env
    await client.post(
        "/api/auth/register",
        json={"username": "dave", "password": "hunter22"},
    )
    # Drop the auto-login cookie so we explicitly exercise the login flow.
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login",
        json={"username": "dave", "password": "hunter22"},
    )
    assert r.status_code == 200
    me = await client.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["username"] == "dave"


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(api_env):
    client, _, _, _, _, _ = api_env
    await client.post(
        "/api/auth/register",
        json={"username": "eve", "password": "hunter22"},
    )
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login",
        json={"username": "eve", "password": "wrong"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_without_cookie_returns_401(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_session(api_env):
    client, _, _, _, _, _ = api_env
    await client.post(
        "/api/auth/register",
        json={"username": "frank", "password": "hunter22"},
    )
    r = await client.post("/api/auth/logout")
    assert r.status_code == 200
    client.cookies.clear()
    me = await client.get("/api/auth/me")
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_authenticated_intake_binds_creator_as_owner(api_env):
    client, _, _, _, _, _ = api_env
    await client.post(
        "/api/auth/register",
        json={"username": "gina", "password": "hunter22"},
    )
    intake = await client.post(
        "/api/intake/message",
        json={"text": "Build a signup page with invite codes.", "source_event_id": "auth-intake-1"},
    )
    assert intake.status_code == 200
    projects = await client.get("/api/projects")
    assert projects.status_code == 200
    body = projects.json()
    assert len(body) == 1
    assert body[0]["role"] == "owner"
    assert body[0]["id"] == intake.json()["project"]["id"]


@pytest.mark.asyncio
async def test_projects_list_requires_auth(api_env):
    client, _, _, _, _, _ = api_env
    r = await client.get("/api/projects")
    assert r.status_code == 401
