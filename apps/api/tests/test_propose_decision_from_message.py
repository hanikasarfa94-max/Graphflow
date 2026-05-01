"""User-driven decision crystallization (subjective override).

Per north-star room flow: "if users think some message is hard to
understand, allow users to subjectively click clarify etc, and
decision crystallize if meet conflict." This file covers the
crystallize half:

  * member proposes → IMSuggestion with kind=decision, confidence=1.0,
    outcome=user_proposed, source=user_proposed in proposal
  * idempotent — second propose returns the existing suggestion
  * non-member of the project → 404 (not 403; we don't tell the actor
    whether the message exists)
  * unknown message_id → 404
  * empty message body still allowed (the user is the signal)
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from workgraph_api.main import app
from workgraph_persistence import (
    IMSuggestionRow,
    session_scope,
)


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


async def _register(client: AsyncClient, username: str) -> str:
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _login(client: AsyncClient, username: str) -> None:
    client.cookies.clear()
    r = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "hunter22"},
    )
    assert r.status_code == 200, r.text


async def _intake(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


async def _post_message(client: AsyncClient, pid: str, body: str) -> str:
    r = await client.post(
        f"/api/projects/{pid}/messages",
        json={"body": body},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_member_can_propose_decision_from_message(api_env):
    """A project member subjectively flags a message → IMSuggestion lands.

    Confidence is 1.0 (deliberate human signal). outcome is user_proposed
    so AgentRunLog can distinguish from classifier output.
    """
    client, maker, *_ = api_env
    await _register(client, "pdfm_owner")
    pid = await _intake(client, "pdfm-1")

    msg_id = await _post_message(client, pid, "Hmm I think we should drop X.")

    r = await client.post(
        f"/api/messages/{msg_id}/propose_decision",
        json={"rationale": "Conflict with the v1 cut."},
    )
    assert r.status_code == 200, r.text
    suggestion = r.json()["suggestion"]
    assert suggestion["kind"] == "decision"
    assert suggestion["status"] == "pending"
    assert suggestion["confidence"] == 1.0
    assert suggestion["message_id"] == msg_id

    async with session_scope(maker) as session:
        row = (
            await session.execute(
                select(IMSuggestionRow).where(
                    IMSuggestionRow.message_id == msg_id
                )
            )
        ).scalar_one()
    assert row.outcome == "user_proposed"
    assert row.kind == "decision"
    proposal = row.proposal or {}
    assert proposal.get("source") == "user_proposed"
    assert "Conflict with the v1 cut" in proposal.get("summary", "")


@pytest.mark.asyncio
async def test_propose_decision_is_idempotent(api_env):
    """Second propose on the same message returns the existing suggestion."""
    client, maker, *_ = api_env
    await _register(client, "pdfm_idem")
    pid = await _intake(client, "pdfm-2")

    msg_id = await _post_message(client, pid, "Drop deliverable X.")

    r1 = await client.post(
        f"/api/messages/{msg_id}/propose_decision",
        json={},
    )
    assert r1.status_code == 200, r1.text
    first = r1.json()["suggestion"]

    r2 = await client.post(
        f"/api/messages/{msg_id}/propose_decision",
        json={"rationale": "second attempt — should be ignored"},
    )
    assert r2.status_code == 200, r2.text
    second = r2.json()["suggestion"]

    # Same id; no second row created.
    assert first["id"] == second["id"]
    async with session_scope(maker) as session:
        rows = (
            await session.execute(
                select(IMSuggestionRow).where(
                    IMSuggestionRow.message_id == msg_id
                )
            )
        ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_non_member_cannot_propose(api_env):
    """A user who isn't a project member gets 404 (not 403 — we don't
    leak existence)."""
    client, maker, *_ = api_env
    # Owner registers + creates project + posts a message.
    await _register(client, "pdfm_owner_nm")
    pid = await _intake(client, "pdfm-3")
    msg_id = await _post_message(
        client, pid, "Owner's message in their own project."
    )

    # Outsider registers, never invited.
    await _register(client, "pdfm_outsider")
    # Outsider is now logged in (registration logs you in).

    r = await client.post(
        f"/api/messages/{msg_id}/propose_decision",
        json={},
    )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_unknown_message_returns_404(api_env):
    client, maker, *_ = api_env
    await _register(client, "pdfm_404")
    await _intake(client, "pdfm-4")

    r = await client.post(
        "/api/messages/does-not-exist/propose_decision",
        json={},
    )
    assert r.status_code == 404, r.text
