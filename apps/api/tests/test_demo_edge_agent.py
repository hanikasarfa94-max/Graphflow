"""Unit tests for the deterministic demo EdgeAgent (demo/dev-only)."""
from __future__ import annotations

import pytest

from workgraph_api.demo_edge_agent import (
    DemoEdgeAgent,
    build_b_facing_draft,
    looks_like_question,
    pick_target,
)

_TEAMMATE = {
    "user_id": "u-raj",
    "username": "raj",
    "display_name": "Raj",
    "role": "backend",
    "abilities": ["backend", "data-export"],
}


def test_looks_like_question():
    assert looks_like_question("Who knows the export quirk?") is True
    assert looks_like_question("谁了解导出问题？") is True
    assert looks_like_question("ok") is False
    assert looks_like_question("just a statement") is False
    assert looks_like_question(None) is False


def test_pick_target_first_with_id():
    assert pick_target([_TEAMMATE])["user_id"] == "u-raj"
    assert pick_target([]) is None
    assert pick_target([{"display_name": "no id"}]) is None


def test_b_facing_draft_is_recipient_voiced():
    draft = build_b_facing_draft("Who owns the F export?", "Raj")
    assert draft.startswith("Raj —")
    assert "?" in draft


@pytest.mark.asyncio
async def test_respond_proposes_route_on_question_with_teammate():
    agent = DemoEdgeAgent()
    outcome = await agent.respond(
        user_message="Who knows the CRM export quirk?",
        context={"teammates": [_TEAMMATE]},
    )
    resp = outcome.response
    assert resp.kind == "route_proposal"
    assert len(resp.route_targets) == 1
    t = resp.route_targets[0]
    assert t.user_id == "u-raj"
    assert t.display_name == "Raj"
    assert t.b_facing_draft  # disclosure draft populated
    # default route_kind None → personal.py coerces to "discovery"
    assert resp.route_kind is None


@pytest.mark.asyncio
async def test_respond_silent_without_teammate_or_question():
    agent = DemoEdgeAgent()
    no_team = await agent.respond(
        user_message="Who knows this?", context={"teammates": []}
    )
    assert no_team.response.kind == "silence"
    not_question = await agent.respond(
        user_message="just a note", context={"teammates": [_TEAMMATE]}
    )
    assert not_question.response.kind == "silence"


@pytest.mark.asyncio
async def test_generate_options_and_frame_reply_are_deterministic():
    agent = DemoEdgeAgent()
    opts = await agent.generate_options(routing_context={})
    assert len(opts.options) >= 2
    assert {o.id for o in opts.options} == {"yes", "more"}
    framed = await agent.frame_reply(signal={}, source_user_context={})
    assert framed.framed.body
