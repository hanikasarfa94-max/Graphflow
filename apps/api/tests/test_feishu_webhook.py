"""Tests for Feishu webhook authenticity gate.

Scope: the auth gate only. The happy-path domain shape is covered in
test_intake.py — here we confirm that unsigned / unknown requests are
rejected and that Lark's URL-verification handshake round-trips when
auth passes.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest


CANONICAL_TEXT = "Launch registration page next week with invite-code validation."
SECRET = "test-secret-xyz"
TOKEN = "test-token-abc"


def _lark_sign(*, timestamp: str, nonce: str, secret: str, body: bytes) -> str:
    """Mirror the verify_signature construction so tests build correct sigs."""
    message = f"{timestamp}{nonce}{secret}{body.decode('utf-8')}".encode("utf-8")
    return hmac.new(key=b"", msg=message, digestmod=hashlib.sha256).hexdigest()


def _clear_feishu_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_VERIFICATION_TOKEN"):
        monkeypatch.delenv(key, raising=False)


# ---------- No config -----------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_unconfigured_returns_503(api_env, monkeypatch):
    client, _, _, _, _, _ = api_env
    _clear_feishu_env(monkeypatch)

    r = await client.post(
        "/api/intake/feishu/webhook",
        json={"event_id": "e1", "message_text": "hi"},
    )
    assert r.status_code == 503, r.text
    assert "feishu webhook not configured" in r.text.lower()


# ---------- Signature mode ------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_signature_valid_returns_200(api_env, monkeypatch):
    client, _, _, _, _, _ = api_env
    _clear_feishu_env(monkeypatch)
    monkeypatch.setenv("FEISHU_APP_SECRET", SECRET)

    body_obj = {
        "event_id": "fs-sig-ok-1",
        "message_text": CANONICAL_TEXT,
        "sender_id": "ou_signed",
        "chat_id": "oc_signed",
        "raw": {},
    }
    body = json.dumps(body_obj).encode("utf-8")
    timestamp = "1700000000"
    nonce = "nonce-1"
    signature = _lark_sign(
        timestamp=timestamp, nonce=nonce, secret=SECRET, body=body
    )

    r = await client.post(
        "/api/intake/feishu/webhook",
        content=body,
        headers={
            "content-type": "application/json",
            "x-lark-request-timestamp": timestamp,
            "x-lark-request-nonce": nonce,
            "x-lark-signature": signature,
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["source"] == "feishu"
    assert data["source_event_id"] == "fs-sig-ok-1"


@pytest.mark.asyncio
async def test_webhook_signature_invalid_returns_401(api_env, monkeypatch):
    client, _, _, _, _, _ = api_env
    _clear_feishu_env(monkeypatch)
    monkeypatch.setenv("FEISHU_APP_SECRET", SECRET)

    body = json.dumps(
        {"event_id": "fs-bad-sig", "message_text": CANONICAL_TEXT}
    ).encode("utf-8")

    r = await client.post(
        "/api/intake/feishu/webhook",
        content=body,
        headers={
            "content-type": "application/json",
            "x-lark-request-timestamp": "1700000000",
            "x-lark-request-nonce": "n",
            "x-lark-signature": "deadbeef" * 8,
        },
    )
    assert r.status_code == 401
    assert "invalid signature" in r.text.lower()


@pytest.mark.asyncio
async def test_webhook_signature_missing_headers_returns_401(
    api_env, monkeypatch
):
    client, _, _, _, _, _ = api_env
    _clear_feishu_env(monkeypatch)
    monkeypatch.setenv("FEISHU_APP_SECRET", SECRET)

    r = await client.post(
        "/api/intake/feishu/webhook",
        json={"event_id": "fs-nohdr", "message_text": CANONICAL_TEXT},
    )
    assert r.status_code == 401
    assert "missing signature headers" in r.text.lower()


# ---------- Token mode ----------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_token_valid_returns_200(api_env, monkeypatch):
    """Token mode: valid token + normalized shape → 200, project created.

    The router strips ``token`` from the payload before running the
    Phase-2 shape validator, so the normalized fields pass through
    untouched.
    """
    client, _, _, _, _, _ = api_env
    _clear_feishu_env(monkeypatch)
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", TOKEN)

    r = await client.post(
        "/api/intake/feishu/webhook",
        json={
            "token": TOKEN,
            "event_id": "fs-tok-ok",
            "message_text": CANONICAL_TEXT,
            "sender_id": "ou_tok",
            "chat_id": "oc_tok",
            "raw": {},
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["source"] == "feishu"
    assert data["source_event_id"] == "fs-tok-ok"


@pytest.mark.asyncio
async def test_webhook_token_url_verification_handshake(
    api_env, monkeypatch
):
    """Token mode: URL-verification handshake passes when token matches."""
    client, _, _, _, _, _ = api_env
    _clear_feishu_env(monkeypatch)
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", TOKEN)

    r = await client.post(
        "/api/intake/feishu/webhook",
        json={
            "token": TOKEN,
            "type": "url_verification",
            "challenge": "abc-123",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"challenge": "abc-123"}


@pytest.mark.asyncio
async def test_webhook_token_wrong_returns_401(api_env, monkeypatch):
    client, _, _, _, _, _ = api_env
    _clear_feishu_env(monkeypatch)
    monkeypatch.setenv("FEISHU_VERIFICATION_TOKEN", TOKEN)

    r = await client.post(
        "/api/intake/feishu/webhook",
        json={
            "token": "nope",
            "event_id": "fs-tok-bad",
            "message_text": CANONICAL_TEXT,
        },
    )
    assert r.status_code == 401
    assert "invalid token" in r.text.lower()


# ---------- URL-verification handshake ------------------------------------


@pytest.mark.asyncio
async def test_url_verification_handshake_echoes_challenge_signed(
    api_env, monkeypatch
):
    client, _, _, _, _, _ = api_env
    _clear_feishu_env(monkeypatch)
    monkeypatch.setenv("FEISHU_APP_SECRET", SECRET)

    body_obj = {"type": "url_verification", "challenge": "handshake-xyz"}
    body = json.dumps(body_obj).encode("utf-8")
    timestamp = "1700000001"
    nonce = "nonce-handshake"
    signature = _lark_sign(
        timestamp=timestamp, nonce=nonce, secret=SECRET, body=body
    )

    r = await client.post(
        "/api/intake/feishu/webhook",
        content=body,
        headers={
            "content-type": "application/json",
            "x-lark-request-timestamp": timestamp,
            "x-lark-request-nonce": nonce,
            "x-lark-signature": signature,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"challenge": "handshake-xyz"}


@pytest.mark.asyncio
async def test_url_verification_handshake_unsigned_rejected(
    api_env, monkeypatch
):
    """Auth must happen before the handshake echo — no free challenge echo."""
    client, _, _, _, _, _ = api_env
    _clear_feishu_env(monkeypatch)
    monkeypatch.setenv("FEISHU_APP_SECRET", SECRET)

    r = await client.post(
        "/api/intake/feishu/webhook",
        json={"type": "url_verification", "challenge": "handshake-xyz"},
    )
    assert r.status_code == 401
