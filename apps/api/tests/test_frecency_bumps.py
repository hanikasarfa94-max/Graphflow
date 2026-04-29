"""§7.4 frecency bump-on-touch regression tests.

Covers the three touch sites wired in pickup #3:

  * `SkillsService._kb_search` — every kb item returned to the caller
    is bumped once (search-hit access event).
  * `IMService.apply_suggestion` decision crystallize — the source
    message that triggered the suggestion is bumped (citation
    resolution event).
  * `PersonalStreamService` reply persistence — every CitedClaim
    citation node is bumped (cite-resolver event). Covers the kb /
    decision / task / risk citation kinds; commitment / goal /
    deliverable / milestone are no-ops by design (graph entities are
    structure, not content — see `_FrecencyColumnsMixin` docstring).

Each test seeds the row, captures pre-bump access_count, exercises the
real service path, then asserts access_count incremented and
last_accessed_at advanced.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from workgraph_agents import EdgeResponse, EdgeResponseOutcome
from workgraph_agents.citations import Citation, CitedClaim
from workgraph_agents.im_assist import IMProposal, IMSuggestion
from workgraph_agents.llm import LLMResult
from workgraph_api.main import app
from workgraph_api.services import PersonalStreamService, SkillsService
from workgraph_persistence import (
    DecisionRepository,
    DecisionRow,
    KbIngestRepository,
    KbItemRow,
    MessageRow,
    ProjectMemberRepository,
    ProjectRow,
    UserRepository,
    backfill_streams_from_projects,
    bump_citations,
    bump_frecency,
    session_scope,
)


CANONICAL_TEXT = (
    "We need to launch an event registration page next week. "
    "It needs invitation code validation, phone number validation, "
    "admin export, and conversion tracking."
)


# ---------------------------------------------------------------------------
# Helpers (lightweight; mirror test_skills.py / test_personal.py).
# ---------------------------------------------------------------------------


async def _mk_project(maker, title: str = "frecency test") -> str:
    async with session_scope(maker) as session:
        pid = str(uuid.uuid4())
        session.add(ProjectRow(id=pid, title=title))
        await session.flush()
    return pid


async def _mk_user(maker, username: str) -> str:
    async with session_scope(maker) as session:
        user = await UserRepository(session).create(
            username=username,
            password_hash="x",
            password_salt="y",
            display_name=username,
        )
        return user.id


async def _add_member(maker, project_id: str, user_id: str) -> None:
    async with session_scope(maker) as session:
        await ProjectMemberRepository(session).add(
            project_id=project_id, user_id=user_id
        )


async def _mk_kb_item(maker, project_id: str, *, content: str) -> str:
    async with session_scope(maker) as session:
        repo = KbIngestRepository(session)
        row = await repo.create(
            project_id=project_id,
            source_kind="user-drop",
            source_identifier=f"kb-{uuid.uuid4().hex[:6]}",
            raw_content=content,
        )
        await repo.set_classification(
            row.id,
            classification={
                "is_relevant": True,
                "tags": [],
                "summary": content[:80],
                "proposed_target_user_ids": [],
                "proposed_action": "ambient-log",
                "confidence": 0.8,
                "safety_notes": "",
            },
            status="approved",
        )
        return row.id


async def _read_frecency(maker, row_cls, row_id: str) -> tuple[int, datetime]:
    async with session_scope(maker) as session:
        row = (
            await session.execute(select(row_cls).where(row_cls.id == row_id))
        ).scalar_one()
        return row.access_count, row.last_accessed_at


async def _register(client: AsyncClient, username: str, password: str = "hunter22"):
    r = await client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert r.status_code == 200, r.text


async def _intake(client: AsyncClient, event_id: str) -> str:
    r = await client.post(
        "/api/intake/message",
        json={"text": CANONICAL_TEXT, "source_event_id": event_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["project"]["id"]


async def _me_id(client: AsyncClient) -> str:
    r = await client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ---------------------------------------------------------------------------
# Helper-level: bump_frecency + bump_citations behave as documented.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bump_frecency_increments_access_count(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    kb_id = await _mk_kb_item(maker, pid, content="alpha bravo charlie")

    before_count, _before_ts = await _read_frecency(maker, KbItemRow, kb_id)
    async with session_scope(maker) as session:
        counts = await bump_frecency(session, kbitem_ids=[kb_id])
    assert counts["kb_item"] == 1

    after_count, after_ts = await _read_frecency(maker, KbItemRow, kb_id)
    assert after_count == before_count + 1
    assert after_ts is not None


@pytest.mark.asyncio
async def test_bump_frecency_dedupes_within_call(api_env):
    """Same id passed twice in one call counts as one bump.

    A kb_search hit-list with a duplicate row is one access event,
    not two — and bump_frecency dedupes internally so the UPDATE rowcount
    matches the unique id set, not the input length.
    """
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    kb_id = await _mk_kb_item(maker, pid, content="dedupe me")

    async with session_scope(maker) as session:
        counts = await bump_frecency(session, kbitem_ids=[kb_id, kb_id, kb_id])
    assert counts["kb_item"] == 1

    after_count, _ = await _read_frecency(maker, KbItemRow, kb_id)
    assert after_count == 1


@pytest.mark.asyncio
async def test_bump_citations_buckets_by_kind_and_skips_unknown(api_env):
    """Mixed citation list lands on the right tables; graph kinds skip."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    kb_id = await _mk_kb_item(maker, pid, content="kb cite target")
    user_id = await _mk_user(maker, "frecency-resolver")
    await _add_member(maker, pid, user_id)

    async with session_scope(maker) as session:
        decision = await DecisionRepository(session).create(
            conflict_id=None,
            project_id=pid,
            resolver_id=user_id,
            option_index=None,
            custom_text="cited",
            rationale="cited",
            apply_actions=[],
            apply_outcome="advisory",
        )
        decision_id = decision.id

    citations = [
        Citation(node_id=kb_id, kind="kb"),
        Citation(node_id=decision_id, kind="decision"),
        # Graph entities skip silently — no row table to update.
        Citation(node_id="some-goal-id", kind="goal"),
        Citation(node_id="some-commitment-id", kind="commitment"),
    ]
    async with session_scope(maker) as session:
        counts = await bump_citations(session, citations)
    assert counts["kb_item"] == 1
    assert counts["decision"] == 1
    assert counts["task"] == 0
    assert counts["risk"] == 0

    kb_count, _ = await _read_frecency(maker, KbItemRow, kb_id)
    dec_count, _ = await _read_frecency(maker, DecisionRow, decision_id)
    assert kb_count == 1
    assert dec_count == 1


# ---------------------------------------------------------------------------
# Site 1: SkillsService._kb_search bumps every returned kb item.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kb_search_bumps_returned_items(api_env):
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    hit_id = await _mk_kb_item(
        maker, pid, content="boss 1 design notes: rage-quit 40%"
    )
    miss_id = await _mk_kb_item(maker, pid, content="inventory rework doc")

    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid,
        skill_name="kb_search",
        args={"query": "boss", "limit": 5},
    )
    assert out["ok"] is True
    assert {i["id"] for i in out["result"]} == {hit_id}

    hit_count, _ = await _read_frecency(maker, KbItemRow, hit_id)
    miss_count, _ = await _read_frecency(maker, KbItemRow, miss_id)
    assert hit_count == 1, "matched item should be bumped"
    assert miss_count == 0, "non-matched item must not be bumped"


@pytest.mark.asyncio
async def test_kb_search_empty_results_no_bump(api_env):
    """Failing search is not a touch — keeps cold rows cold."""
    _, maker, *_ = api_env
    pid = await _mk_project(maker)
    kb_id = await _mk_kb_item(maker, pid, content="nothing to see here")

    svc = SkillsService(maker)
    out = await svc.execute(
        project_id=pid,
        skill_name="kb_search",
        args={"query": "zzz_no_match"},
    )
    assert out["ok"] is True
    assert out["result"] == []

    count, _ = await _read_frecency(maker, KbItemRow, kb_id)
    assert count == 0


# ---------------------------------------------------------------------------
# Site 2: IMService decision crystallize bumps source message.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_im_decision_crystallize_bumps_source_message(api_env):
    """The IM message that triggered a high-confidence decision is the
    citation that backs the new DecisionRow. Crystallizing must bump it.

    Pins the stub im_agent to a `kind='decision'` suggestion at conf 0.8,
    posts a message, then accepts the suggestion. Asserts the message's
    access_count went 0 → 1.
    """
    client, maker, *_ = api_env
    im_agent = app.state.im_agent
    await _register(client, "frecency_owner")
    project_id = await _intake(client, "frecency-im-1")
    state = (await client.get(f"/api/projects/{project_id}/state")).json()
    deliverable_id = state["graph"]["deliverables"][0]["id"]

    # Pin a high-confidence decision suggestion so the apply path
    # crystallizes a DecisionRow.
    im_agent._suggestion = IMSuggestion(
        kind="decision",
        confidence=0.8,
        targets=[],
        proposal=IMProposal(
            action="drop_deliverable",
            summary="frecency-bump test crystallization",
            detail={"deliverable_id": deliverable_id},
        ),
        reasoning="frecency-bump test",
    )

    try:
        # Post the source message. The stub IM agent runs synchronously
        # via im_service.drain() on the message endpoint.
        r = await client.post(
            f"/api/projects/{project_id}/messages",
            json={"body": "let's drop this deliverable for the v1 launch"},
        )
        assert r.status_code == 200, r.text
        await app.state.im_service.drain()
        messages = (
            await client.get(f"/api/projects/{project_id}/messages")
        ).json()["messages"]
        msg = messages[-1]
        msg_id = msg["id"]
        suggestion_id = msg["suggestion"]["id"]

        # Pre-bump baseline. Source-message INSERT defaults
        # access_count=0, last_accessed_at=now. Capture both.
        before_count, before_ts = await _read_frecency(maker, MessageRow, msg_id)

        # Accept → crystallize → bump.
        r = await client.post(f"/api/im_suggestions/{suggestion_id}/accept")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["decision"] is not None, "decision should crystallize"

        after_count, after_ts = await _read_frecency(maker, MessageRow, msg_id)
        assert after_count == before_count + 1
        assert after_ts >= before_ts
    finally:
        im_agent._suggestion = None


# ---------------------------------------------------------------------------
# Site 3: PersonalStreamService reply persistence bumps cited claims.
# ---------------------------------------------------------------------------


class _ScriptableEdgeAgent:
    """Minimal scriptable EdgeAgent for the personal-side test.

    Same shape as test_personal._StubEdgeAgent but only the `respond`
    queue is needed here.
    """

    def __init__(self) -> None:
        self.respond_queue: list[EdgeResponse] = []

    def _result(self) -> LLMResult:
        return LLMResult(
            content="",
            model="stub",
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
        )

    async def respond(self, *, user_message, context):
        return EdgeResponseOutcome(
            response=self.respond_queue.pop(0),
            result=self._result(),
            outcome="ok",
            attempts=1,
        )

    async def generate_options(self, *, routing_context):  # pragma: no cover
        raise NotImplementedError

    async def frame_reply(self, *, signal, source_user_context):  # pragma: no cover
        raise NotImplementedError


def _install_edge_stub(api_env_tuple) -> _ScriptableEdgeAgent:
    _client, maker, bus, *_ = api_env_tuple
    stub = _ScriptableEdgeAgent()
    app.state.personal_service = PersonalStreamService(
        maker,
        app.state.stream_service,
        app.state.routing_service,
        stub,
        bus,
    )
    app.state.edge_agent = stub
    return stub


@pytest.mark.asyncio
async def test_personal_post_bumps_cited_kb_items(api_env):
    """Edge-LLM reply with structured citations bumps the cited rows.

    Covers the answer/clarify reply path — the simplest of the three
    citation-shipping sites in PersonalStreamService.
    """
    client, maker, *_ = api_env
    stub = _install_edge_stub(api_env)

    await _register(client, "frecency_personal")
    project_id = await _intake(client, "frecency-personal-1")
    await _me_id(client)
    await backfill_streams_from_projects(maker)

    cited_kb_id = await _mk_kb_item(maker, project_id, content="cited kb body")
    other_kb_id = await _mk_kb_item(maker, project_id, content="not cited")

    stub.respond_queue.append(
        EdgeResponse(
            kind="answer",
            body="here is the cited answer",
            route_targets=[],
            claims=[
                CitedClaim(
                    text="here is the cited answer",
                    citations=[Citation(node_id=cited_kb_id, kind="kb")],
                )
            ],
        )
    )

    r = await client.post(
        f"/api/personal/{project_id}/post",
        json={"body": "what is the answer?"},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["edge_response"]["kind"] == "answer"

    cited_count, _ = await _read_frecency(maker, KbItemRow, cited_kb_id)
    other_count, _ = await _read_frecency(maker, KbItemRow, other_kb_id)
    assert cited_count == 1, "cited kb item must be bumped"
    assert other_count == 0, "uncited kb item must stay cold"
