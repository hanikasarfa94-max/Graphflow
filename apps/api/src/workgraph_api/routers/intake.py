from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from workgraph_domain import IntakeResult
from workgraph_feishu_adapter import verify_signature, verify_token

from workgraph_api.deps import get_intake_service, maybe_user
from workgraph_api.services import AuthenticatedUser, IntakeService
from workgraph_api.settings import load_settings

router = APIRouter(prefix="/api/intake", tags=["intake"])


def _default_title(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= 80:
        return cleaned or "Untitled project"
    return cleaned[:77] + "..."


# ---------- Direct API path -----------------------------------------------


class ApiIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="Raw requirement message.")
    title: str | None = Field(default=None, max_length=500)
    source_event_id: str | None = Field(
        default=None,
        description="Client-supplied idempotency key. Generated if omitted.",
    )


@router.post("/message", response_model=IntakeResult)
async def post_message(
    body: ApiIntakeRequest,
    service: IntakeService = Depends(get_intake_service),
    user: AuthenticatedUser | None = Depends(maybe_user),
) -> IntakeResult:
    source_event_id = body.source_event_id or f"api-{uuid4().hex}"
    return await service.receive(
        source="api",
        source_event_id=source_event_id,
        title=body.title or _default_title(body.text),
        raw_text=body.text,
        payload={"text": body.text, "title": body.title},
        creator_user_id=user.id if user else None,
    )


# ---------- Feishu webhook path -------------------------------------------
# Phase 2: accepts a normalized shape behind a webhook-authenticity gate.
# Real Feishu SDK signature verification + event envelope parsing lands in
# Phase 7 (Feishu State Sync). The pivot decision on Feishu-native vs
# custom collab surface is deferred to CEO review.


class FeishuWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, description="Feishu event UUID (idempotency key).")
    message_text: str = Field(min_length=1)
    sender_id: str | None = None
    chat_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


def _auth_gate(
    *,
    raw_body: bytes,
    headers,  # type: ignore[no-untyped-def]
) -> dict[str, Any]:
    """Verify webhook authenticity and return the parsed JSON payload.

    Raises HTTPException(401) on auth failure, HTTPException(503) when
    Feishu is not configured at all (safer than silently accepting
    unsigned traffic), HTTPException(400) on unparseable JSON.
    """
    settings = load_settings()
    secret = settings.feishu_app_secret
    token = settings.feishu_verification_token

    if not secret and not token:
        raise HTTPException(
            status_code=503, detail="feishu webhook not configured"
        )

    if secret:
        timestamp = headers.get("x-lark-request-timestamp")
        nonce = headers.get("x-lark-request-nonce")
        signature = headers.get("x-lark-signature")
        if not (timestamp and nonce and signature):
            raise HTTPException(
                status_code=401, detail="missing signature headers"
            )
        if not verify_signature(
            timestamp=timestamp,
            nonce=nonce,
            body=raw_body,
            signature=signature,
            secret=secret,
        ):
            raise HTTPException(status_code=401, detail="invalid signature")

    # Parse body regardless — we need it for the handshake + payload.
    try:
        payload = json.loads(raw_body.decode("utf-8") or "null")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid json body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")

    if not secret and token:
        if not verify_token(payload=payload, expected_token=token):
            raise HTTPException(status_code=401, detail="invalid token")

    return payload


@router.post("/feishu/webhook")
async def post_feishu_webhook(
    request: Request,
    service: IntakeService = Depends(get_intake_service),
):
    raw_body = await request.body()
    payload = _auth_gate(raw_body=raw_body, headers=request.headers)

    # Lark URL-verification handshake: once auth passes, echo the challenge.
    if payload.get("type") == "url_verification":
        challenge = payload.get("challenge")
        if not isinstance(challenge, str):
            raise HTTPException(
                status_code=400, detail="url_verification missing challenge"
            )
        return JSONResponse({"challenge": challenge})

    # Phase-2 normalized shape: validate after the auth gate. The `token`
    # key (used for token-mode auth above) and Lark envelope fields
    # (`type`, `header`) are stripped so they don't trip extra="forbid".
    normalized = {
        k: v
        for k, v in payload.items()
        if k not in {"token", "type", "header", "schema"}
    }
    try:
        body = FeishuWebhookRequest.model_validate(normalized)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    result = await service.receive(
        source="feishu",
        source_event_id=body.event_id,
        title=_default_title(body.message_text),
        raw_text=body.message_text,
        payload={
            "event_id": body.event_id,
            "message_text": body.message_text,
            "sender_id": body.sender_id,
            "chat_id": body.chat_id,
            "raw": body.raw,
        },
    )
    return JSONResponse(result.model_dump(mode="json"))
