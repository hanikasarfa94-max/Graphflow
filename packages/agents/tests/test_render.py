"""RenderAgent unit tests (Phase R).

The LLM is stubbed end-to-end — these tests never call a real provider.
We drive the agent with scripted completions and assert on:
  * structured output shape (Pydantic)
  * recovery ladder (3 bad attempts → manual_review fallback)
  * decision-citation grounding (unknown ids get unbolded)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pytest

from workgraph_agents.llm import LLMClient, LLMResult, LLMSettings
from workgraph_agents.render import (
    HandoffDoc,
    PostmortemDoc,
    RenderAgent,
)


# ---------------------------------------------------------------------------
# ScriptedLLM — same pattern as test_edge.py.
# ---------------------------------------------------------------------------


class ScriptedLLM(LLMClient):
    def __init__(self, script: Iterable[str]) -> None:
        self._settings = LLMSettings.model_construct(
            api_key="test", base_url="http://stub", model="stub-model"
        )
        self._client = None
        self._script = list(script)
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages,
        *,
        model=None,
        temperature: float = 0.1,
        response_format=None,
    ) -> LLMResult:
        self.calls.append(list(messages))
        if not self._script:
            raise AssertionError("ScriptedLLM: script exhausted")
        content = self._script.pop(0)
        return LLMResult(
            content=content,
            model=self._settings.model,
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=1,
        )


def _dump(obj: dict) -> str:
    return json.dumps(obj)


# ---------------------------------------------------------------------------
# Postmortem context fixtures.
# ---------------------------------------------------------------------------


def _postmortem_ctx() -> dict:
    return {
        "project": {"id": "p-rogue", "title": "Roguelike v2"},
        "requirement": {
            "goal": "Ship roguelike MVP",
            "scope_items": ["permadeath", "inventory"],
            "deadline": None,
            "open_questions": [],
        },
        "graph": {
            "goals": [],
            "deliverables": [],
            "constraints": [],
            "risks": [],
        },
        "plan": {"tasks": [], "milestones": []},
        "decisions": [
            {
                "id": "d-100",
                "conflict_id": None,
                "option_index": 0,
                "custom_text": None,
                "rationale": "Keep permadeath; softened with memento revive.",
                "apply_outcome": "advisory",
                "created_at": "2026-04-12T10:00:00Z",
                "lineage": [
                    {
                        "kind": "signal",
                        "summary": "Maya asked if permadeath should be cut",
                        "by_display_name": "Maya",
                    }
                ],
            }
        ],
        "resolved_risks": [],
        "active_tasks": [],
        "delivered_tasks": [],
        "undelivered_tasks": [],
        "key_turns": [],
    }


def _valid_postmortem_payload() -> dict:
    return {
        "title": "Roguelike v2 postmortem",
        "one_line_summary": "Permadeath preserved with memento revive; inventory deferred.",
        "sections": [
            {
                "heading": "What happened",
                "body_markdown": "Shipped permadeath; inventory deferred.",
            },
            {
                "heading": "Key decisions (lineage)",
                "body_markdown": (
                    "- **D-d-100** — Keep permadeath; softened with memento "
                    "revive. Lineage: Maya asked → Raj countered → crystallized."
                ),
            },
            {
                "heading": "What we got right",
                "body_markdown": "- Scoped early",
            },
            {"heading": "What drifted", "body_markdown": "- Inventory slipped"},
            {"heading": "Lessons", "body_markdown": "- Scope ruthlessly"},
        ],
    }


# ---------------------------------------------------------------------------
# Postmortem — happy path and shape.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_postmortem_happy_path():
    agent = RenderAgent(
        llm=ScriptedLLM([_dump(_valid_postmortem_payload())]),
        postmortem_prompt="(stub)",
        handoff_prompt="(stub)",
    )
    out = await agent.render_postmortem(_postmortem_ctx())
    assert out.outcome == "ok"
    assert out.attempts == 1
    assert isinstance(out.doc, PostmortemDoc)
    assert out.doc.title == "Roguelike v2 postmortem"
    assert len(out.doc.sections) == 5
    headings = [s.heading for s in out.doc.sections]
    assert "Key decisions (lineage)" in headings


@pytest.mark.asyncio
async def test_render_postmortem_decision_citations_grounded():
    # Payload cites d-100 (known) AND d-999 (fabricated) — the agent's
    # grounding pass should unbold d-999 but leave d-100 intact.
    payload = _valid_postmortem_payload()
    payload["sections"][1]["body_markdown"] = (
        "- **D-d-100** — real decision.\n"
        "- **D-d-999** — invented decision that should be unbolded."
    )
    agent = RenderAgent(
        llm=ScriptedLLM([_dump(payload)]),
        postmortem_prompt="(stub)",
        handoff_prompt="(stub)",
    )
    out = await agent.render_postmortem(_postmortem_ctx())
    body = out.doc.sections[1].body_markdown
    assert "**D-d-100**" in body, "known id must keep bold markup"
    assert "**D-d-999**" not in body, "unknown id must lose bold markup"
    assert "*D-d-999*" in body, "unknown id stays visible in plain italics"


@pytest.mark.asyncio
async def test_render_postmortem_manual_review_after_three_bad_jsons():
    agent = RenderAgent(
        llm=ScriptedLLM(["not json", "still not json", "nope"]),
        postmortem_prompt="(stub)",
        handoff_prompt="(stub)",
    )
    out = await agent.render_postmortem(_postmortem_ctx())
    assert out.outcome == "manual_review"
    assert out.attempts == 3
    # Fallback must still carry the shape.
    assert isinstance(out.doc, PostmortemDoc)
    assert len(out.doc.sections) == 5
    # Fallback cites real decision id in the "Key decisions" body.
    kd_section = next(
        s for s in out.doc.sections if s.heading == "Key decisions (lineage)"
    )
    assert "d-100" in kd_section.body_markdown


@pytest.mark.asyncio
async def test_render_postmortem_rejects_extra_fields():
    bad = _valid_postmortem_payload()
    bad["surprise_field"] = "nope"
    agent = RenderAgent(
        llm=ScriptedLLM([_dump(bad)] * 3),
        postmortem_prompt="(stub)",
        handoff_prompt="(stub)",
    )
    out = await agent.render_postmortem(_postmortem_ctx())
    assert out.outcome == "manual_review"
    assert out.attempts == 3


# ---------------------------------------------------------------------------
# Handoff tests.
# ---------------------------------------------------------------------------


def _handoff_ctx() -> dict:
    return {
        "user": {
            "id": "u-maya",
            "username": "maya",
            "display_name": "Maya",
            "role": "pm",
            "declared_abilities": ["product"],
        },
        "project": {"id": "p-rogue", "title": "Roguelike v2"},
        "active_tasks": [
            {
                "id": "t-1",
                "title": "Run playtest cohort B",
                "status": "in_progress",
                "description": "Collect rage-quit rates for permadeath variant.",
                "deliverable_title": "Playtest report",
            }
        ],
        "shaped_decisions": [
            {
                "id": "d-100",
                "headline": "Keep permadeath",
                "rationale": "Preserves genre stakes.",
                "role": "author",
            }
        ],
        "recent_signals": [
            {
                "framing": "Should we drop permadeath?",
                "role": "source",
                "resolution": "countered",
            }
        ],
        "adjacent_teammates": [
            {
                "user_id": "u-raj",
                "display_name": "Raj",
                "role": "game-design",
                "shared_context": "Owns permadeath thesis.",
            }
        ],
        "open_items": [
            {
                "kind": "routing",
                "framing": "Is the memento revive scoped for sprint 3?",
                "from_display_name": "Raj",
                "age_days": 2,
            }
        ],
        "response_profile": {
            "counter_rate": 0.2,
            "accept_rate": 0.6,
            "preferred_kinds": ["accept"],
        },
    }


def _valid_handoff_payload() -> dict:
    return {
        "title": "Maya's handoff — Roguelike v2",
        "sections": [
            {
                "heading": "Role summary",
                "body_markdown": "Maya owns the PM slice on Roguelike v2.",
            },
            {
                "heading": "Active tasks I own",
                "body_markdown": (
                    "- **Run playtest cohort B** (in_progress). "
                    "Collect rage-quit rates. Next step: review data with Raj."
                ),
            },
            {
                "heading": "Recurring decisions I make",
                "body_markdown": "- Scope calls — usually accepts with one clarification.",
            },
            {
                "heading": "Key relationships",
                "body_markdown": "- **Raj** (game-design) — permadeath thesis channel.",
            },
            {
                "heading": "Open items / pending routings",
                "body_markdown": "- Is memento revive scoped for sprint 3? (from Raj, 2d)",
            },
            {
                "heading": "Style notes (how I reply to common asks)",
                "body_markdown": "- Accepts quickly when there's a playtest number attached.",
            },
        ],
    }


@pytest.mark.asyncio
async def test_render_handoff_happy_path():
    agent = RenderAgent(
        llm=ScriptedLLM([_dump(_valid_handoff_payload())]),
        postmortem_prompt="(stub)",
        handoff_prompt="(stub)",
    )
    out = await agent.render_handoff(_handoff_ctx())
    assert out.outcome == "ok"
    assert isinstance(out.doc, HandoffDoc)
    assert "Maya" in out.doc.title
    assert len(out.doc.sections) == 6


@pytest.mark.asyncio
async def test_render_handoff_manual_review_fallback_shape():
    agent = RenderAgent(
        llm=ScriptedLLM(["bad", "still bad", "nope"]),
        postmortem_prompt="(stub)",
        handoff_prompt="(stub)",
    )
    out = await agent.render_handoff(_handoff_ctx())
    assert out.outcome == "manual_review"
    # Fallback still carries the right section count + grounded from ctx.
    assert len(out.doc.sections) == 6
    role_summary = out.doc.sections[0].body_markdown
    assert "Maya" in role_summary


@pytest.mark.asyncio
async def test_render_handoff_rejects_extras():
    bad = _valid_handoff_payload()
    bad["extra_field"] = "nope"
    agent = RenderAgent(
        llm=ScriptedLLM([_dump(bad)] * 3),
        postmortem_prompt="(stub)",
        handoff_prompt="(stub)",
    )
    out = await agent.render_handoff(_handoff_ctx())
    assert out.outcome == "manual_review"


# ---------------------------------------------------------------------------
# Prompt-file hygiene.
# ---------------------------------------------------------------------------


def test_prompt_files_have_prompt_version_header():
    import re

    root = (
        Path(__file__).parent.parent
        / "src"
        / "workgraph_agents"
        / "prompts"
        / "render"
    )
    pattern = re.compile(r"^PROMPT_VERSION: \d{4}-\d{2}-\d{2}\.phaseR\.v\d+$", re.M)
    for name in ("postmortem_v1.md", "handoff_v1.md"):
        text = (root / name).read_text(encoding="utf-8")
        assert pattern.search(text), f"{name} missing PROMPT_VERSION header"
