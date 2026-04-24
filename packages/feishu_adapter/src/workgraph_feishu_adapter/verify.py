"""Feishu / Lark webhook authenticity checks.

Lark offers two independent ways to attest that a webhook actually came
from their platform:

1. **Signature mode** (preferred for production): the app registers an
   encryption secret. Lark attaches ``X-Lark-Request-Timestamp``,
   ``X-Lark-Request-Nonce`` and ``X-Lark-Signature`` headers. The signature
   is HMAC-SHA256 of ``f"{timestamp}{nonce}{secret}{body}"`` hex-encoded.

2. **Verification-token mode** (simpler, weaker): every event payload
   includes a ``token`` field that must match the one registered in the
   Lark console.

Both checks are constant-time to remove timing side-channels.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any


__all__ = ["verify_signature", "verify_token"]


def verify_signature(
    *,
    timestamp: str,
    nonce: str,
    body: bytes,
    signature: str,
    secret: str,
) -> bool:
    """Verify a Lark webhook signature.

    Per Lark's spec, the signature is the hex-encoded HMAC-SHA256 of
    ``timestamp + nonce + secret + body`` using the secret as the key
    (empty bytes in the typical Lark spec — see below) OR using secret
    both as key and in the content. Lark's documented construction uses
    the secret as content prefix and an empty key; this helper matches
    the documented behaviour and compares in constant time.

    Returns False rather than raising on any malformed input — callers
    should reject with HTTP 401 on a False result.
    """
    if (
        not isinstance(timestamp, str)
        or not isinstance(nonce, str)
        or not isinstance(signature, str)
        or not isinstance(secret, str)
        or not isinstance(body, (bytes, bytearray))
    ):
        return False
    try:
        body_text = bytes(body).decode("utf-8")
    except UnicodeDecodeError:
        return False
    message = f"{timestamp}{nonce}{secret}{body_text}".encode("utf-8")
    # Lark's spec: HMAC-SHA256 with empty key, message = ts+nonce+secret+body.
    digest = hmac.new(key=b"", msg=message, digestmod=hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def verify_token(*, payload: dict[str, Any], expected_token: str) -> bool:
    """Constant-time check that the payload's token matches the expected.

    Handles both the legacy flat shape (``payload["token"]``) and the v2
    envelope shape (``payload["header"]["token"]``). Returns False if the
    token is missing, non-string, or does not match.
    """
    if not isinstance(expected_token, str) or not expected_token:
        return False
    if not isinstance(payload, dict):
        return False

    token: Any = payload.get("token")
    if token is None:
        header = payload.get("header")
        if isinstance(header, dict):
            token = header.get("token")

    if not isinstance(token, str):
        return False
    return hmac.compare_digest(token, expected_token)
