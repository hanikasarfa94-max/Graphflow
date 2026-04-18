from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from workgraph_domain import IntakeResult

from workgraph_api.deps import get_intake_service, maybe_user
from workgraph_api.services import AuthenticatedUser, IntakeService

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
# Phase 2: accepts a normalized shape. Real Feishu SDK signature verification
# + event envelope parsing lands in Phase 7 (Feishu State Sync). The pivot
# decision on Feishu-native vs custom collab surface is deferred to CEO review.


class FeishuWebhookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, description="Feishu event UUID (idempotency key).")
    message_text: str = Field(min_length=1)
    sender_id: str | None = None
    chat_id: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


@router.post("/feishu/webhook", response_model=IntakeResult)
async def post_feishu_webhook(
    body: FeishuWebhookRequest,
    service: IntakeService = Depends(get_intake_service),
) -> IntakeResult:
    return await service.receive(
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
