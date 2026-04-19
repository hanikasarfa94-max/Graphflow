"""EdgeAgent unit tests (Phase M).

The LLM is stubbed end-to-end — these tests never call a real provider.
Each test drives the agent with a scripted sequence of raw completions
and then asserts on the parsed structured output, the recovery ladder,
and the profile-aware option weighting.
"""
from __future__ import annotations

import json
from typing import Iterable

import pytest
from pydantic import ValidationError

from workgraph_agents.edge import (
    ALLOWED_SKILLS,
    EdgeAgent,
    EdgeResponse,
    FramedReply,
    RoutedOption,
    RoutedOptionsBatch,
    ToolCall,
)
from workgraph_agents.llm import LLMClient, LLMResult, LLMSettings


# ---------------------------------------------------------------------------
# Stub LLM — scriptable content queue.
# ---------------------------------------------------------------------------


class ScriptedLLM(LLMClient):
    """Returns the next scripted completion per call, cycling through a
    list of strings. Never opens a network connection.

    Matches the `_AlwaysMalformedLLM` pattern used in
    apps/api/tests/test_clarification_fault_injection.py.
    """

    def __init__(self, script: Iterable[str]) -> None:
        self._settings = LLMSettings.model_construct(
            api_key="test-not-used",
            base_url="http://stub",
            model="stub-model",
        )
        self._client = None
        self._script: list[str] = list(script)
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
            cache_read_tokens=0,
        )


def _dump(obj: dict) -> str:
    return json.dumps(obj)


def _ctx() -> dict:
    """Minimal but realistic respond() context the prompt would see."""
    return {
        "user": {
            "id": "u-maya",
            "username": "maya",
            "display_name": "Maya",
            "role": "pm",
            "declared_abilities": ["product"],
            "recent_signal_tally": {"asked": 1, "routed": 1, "decided": 0},
        },
        "project": {
            "id": "p-roguelike",
            "title": "Roguelike v2",
            "member_summaries": [
                {
                    "user_id": "u-raj",
                    "username": "raj",
                    "display_name": "Raj",
                    "role": "game-design",
                    "abilities": ["systems", "combat"],
                }
            ],
            "recent_decisions": [
                {"id": "D-12", "headline": "Keep permadeath; revisit after playtest"}
            ],
            "open_risks": [],
            "active_tasks": [],
        },
        "recent_turns": [],
        "kb_slice": [],
    }


def _routing_ctx(
    *,
    target_response_profile: dict | None = None,
) -> dict:
    return {
        "source_user": {
            "id": "u-maya",
            "username": "maya",
            "display_name": "Maya",
            "role": "pm",
        },
        "target_user": {
            "id": "u-raj",
            "username": "raj",
            "display_name": "Raj",
            "role": "game-design",
        },
        "framing": "Should we drop permadeath given the 40% rage-quit rate?",
        "project_context": {
            "id": "p-roguelike",
            "title": "Roguelike v2",
            "member_summaries": [],
            "recent_decisions": [
                {"id": "D-12", "headline": "Keep permadeath; revisit after playtest"}
            ],
            "open_risks": [],
            "active_tasks": [],
        },
        "target_recent_decisions": [],
        "target_response_profile": target_response_profile or {},
    }


# ---------------------------------------------------------------------------
# respond() — one test per kind.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_respond_answer_kind():
    payload = {
        "kind": "answer",
        "body": "Yes — D-12 committed permadeath three weeks ago.",
        "reasoning": "matches recent_decisions",
        "route_targets": [],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="(prompt stub)",
        options_prompt="(options stub)",
        reply_frame_prompt="(reply frame stub)",
    )
    out = await agent.respond(user_message="did we decide on permadeath?", context=_ctx())
    assert out.outcome == "ok"
    assert out.attempts == 1
    assert out.response.kind == "answer"
    assert out.response.body and "D-12" in out.response.body
    assert out.response.route_targets == []


@pytest.mark.asyncio
async def test_respond_clarify_kind():
    payload = {
        "kind": "clarify",
        "body": "Drop which — permadeath or the inventory rework?",
        "reasoning": "ambiguous referent",
        "route_targets": [],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(user_message="can we drop it?", context=_ctx())
    assert out.response.kind == "clarify"
    assert out.response.body
    assert out.response.route_targets == []


@pytest.mark.asyncio
async def test_respond_route_proposal_kind():
    payload = {
        "kind": "route_proposal",
        "body": "Raj owns permadeath thesis — ask him?",
        "reasoning": "design call",
        "route_targets": [
            {
                "user_id": "u-raj",
                "username": "raj",
                "display_name": "Raj",
                "rationale": "owns game-design",
            }
        ],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(
        user_message="should we cut permadeath?", context=_ctx()
    )
    assert out.response.kind == "route_proposal"
    assert len(out.response.route_targets) == 1
    assert out.response.route_targets[0].user_id == "u-raj"


@pytest.mark.asyncio
async def test_respond_silence_kind_has_null_body():
    payload = {
        "kind": "silence",
        "body": None,
        "reasoning": "acknowledgement",
        "route_targets": [],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(user_message="ok thanks", context=_ctx())
    assert out.response.kind == "silence"
    assert out.response.body is None
    assert out.response.route_targets == []


@pytest.mark.asyncio
async def test_respond_invariants_route_proposal_without_targets_degrades_to_clarify():
    # LLM claimed route_proposal but omitted targets — we must not surface
    # a route affordance the user cannot act on. Expected: kind auto-
    # downgrades to "clarify" with a note in reasoning.
    payload = {
        "kind": "route_proposal",
        "body": "I think this should go to someone.",
        "reasoning": "x",
        "route_targets": [],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(user_message="who owns this?", context=_ctx())
    assert out.response.kind == "clarify"
    assert "degraded" in out.response.reasoning


@pytest.mark.asyncio
async def test_respond_pydantic_forbids_extra_fields():
    # Inject an unexpected top-level field three times — the agent should
    # fail all three JSON-mode attempts and surface manual_review.
    bad = {
        "kind": "answer",
        "body": "ok",
        "reasoning": "x",
        "route_targets": [],
        "extra_surprise_field": "not allowed",
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(bad)] * 3),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(user_message="x", context=_ctx())
    assert out.outcome == "manual_review"
    assert out.attempts == 3
    assert out.error is not None
    # Fallback is a friendly clarify so the stream isn't broken.
    assert out.response.kind == "clarify"


@pytest.mark.asyncio
async def test_respond_recovery_ladder_three_bad_jsons():
    agent = EdgeAgent(
        llm=ScriptedLLM(["not json", "still not json", "nope"]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(user_message="x", context=_ctx())
    assert out.outcome == "manual_review"
    assert out.attempts == 3


# ---------------------------------------------------------------------------
# generate_options() — schema + profile weighting.
# ---------------------------------------------------------------------------


def _options_payload(options: list[dict]) -> str:
    return json.dumps({"options": options})


_BASELINE_OPTIONS = [
    {
        "id": "",
        "label": "Keep permadeath; add memento revive",
        "kind": "counter",
        "background": "D-12 committed permadeath; Sofia's playtest shows rage-quit spike.",
        "reason": "preserves genre stakes while softening rage-quit",
        "tradeoff": "one new system; ~1 sprint",
        "weight": 0.6,
    },
    {
        "id": "",
        "label": "Drop permadeath entirely",
        "kind": "accept",
        "background": "Maya's framing cites 40% rage-quit.",
        "reason": "fastest path to a playable game",
        "tradeoff": "reverts thesis of D-12",
        "weight": 0.6,
    },
    {
        "id": "",
        "label": "Escalate to founder",
        "kind": "escalate",
        "background": "Permadeath is in the thesis-commit.",
        "reason": "decision reshapes genre positioning",
        "tradeoff": "adds a meeting",
        "weight": 0.4,
    },
]


@pytest.mark.asyncio
async def test_generate_options_returns_valid_batch():
    agent = EdgeAgent(
        llm=ScriptedLLM([_options_payload(_BASELINE_OPTIONS)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.generate_options(routing_context=_routing_ctx())
    assert out.outcome == "ok"
    assert 2 <= len(out.options) <= 4
    for opt in out.options:
        assert opt.id  # non-empty (minted if LLM handed back "")
        assert 0.0 <= opt.weight <= 1.0
        assert opt.label
        assert opt.kind in ("accept", "counter", "escalate", "custom")


@pytest.mark.asyncio
async def test_generate_options_counter_preference_profile_lifts_counter_weight():
    # Same LLM output — only the target_response_profile changes.
    agent = EdgeAgent(
        llm=ScriptedLLM(
            [
                _options_payload(_BASELINE_OPTIONS),
                _options_payload(_BASELINE_OPTIONS),
            ]
        ),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    baseline = await agent.generate_options(routing_context=_routing_ctx())
    with_profile = await agent.generate_options(
        routing_context=_routing_ctx(
            target_response_profile={
                "counter_rate": 0.75,
                "accept_rate": 0.1,
                "preferred_kinds": ["counter"],
            }
        )
    )

    def _weight_by_kind(options: list[RoutedOption], kind: str) -> float:
        for o in options:
            if o.kind == kind:
                return o.weight
        raise AssertionError(f"no {kind} option")

    # counter weight should be strictly higher when the profile favours it.
    assert _weight_by_kind(with_profile.options, "counter") > _weight_by_kind(
        baseline.options, "counter"
    )
    # accept weight should not be lifted (profile says accept_rate is low).
    assert _weight_by_kind(with_profile.options, "accept") == _weight_by_kind(
        baseline.options, "accept"
    )


@pytest.mark.asyncio
async def test_generate_options_accept_preference_profile_lifts_accept_weight():
    agent = EdgeAgent(
        llm=ScriptedLLM([_options_payload(_BASELINE_OPTIONS)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.generate_options(
        routing_context=_routing_ctx(
            target_response_profile={
                "counter_rate": 0.1,
                "accept_rate": 0.8,
            }
        )
    )
    accept_weight = next(o.weight for o in out.options if o.kind == "accept")
    # Baseline accept weight is 0.6; with accept_rate >= 0.6 we expect +0.1.
    assert accept_weight == pytest.approx(0.7, abs=1e-6)


@pytest.mark.asyncio
async def test_generate_options_empty_profile_leaves_weights_untouched():
    agent = EdgeAgent(
        llm=ScriptedLLM([_options_payload(_BASELINE_OPTIONS)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.generate_options(routing_context=_routing_ctx())
    weights_by_label = {o.label: o.weight for o in out.options}
    assert weights_by_label["Keep permadeath; add memento revive"] == pytest.approx(0.6)
    assert weights_by_label["Drop permadeath entirely"] == pytest.approx(0.6)
    assert weights_by_label["Escalate to founder"] == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_generate_options_mints_ids_for_blank_or_duplicates():
    raw = [
        {**_BASELINE_OPTIONS[0], "id": ""},
        {**_BASELINE_OPTIONS[1], "id": "dup"},
        {**_BASELINE_OPTIONS[2], "id": "dup"},
    ]
    agent = EdgeAgent(
        llm=ScriptedLLM([_options_payload(raw)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.generate_options(routing_context=_routing_ctx())
    ids = [o.id for o in out.options]
    assert len(set(ids)) == len(ids)
    assert all(i for i in ids)  # no blanks


@pytest.mark.asyncio
async def test_generate_options_rejects_extra_fields():
    bad = [
        {**_BASELINE_OPTIONS[0], "surprise": "nope"},
        _BASELINE_OPTIONS[1],
    ]
    agent = EdgeAgent(
        llm=ScriptedLLM([_options_payload(bad)] * 3),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.generate_options(routing_context=_routing_ctx())
    assert out.outcome == "manual_review"
    assert out.attempts == 3
    # Fallback gives the target *some* way to respond.
    assert 2 <= len(out.options) <= 4


@pytest.mark.asyncio
async def test_generate_options_rejects_under_minimum():
    # Only one option — violates min_length=2 on the batch.
    one = _options_payload([_BASELINE_OPTIONS[0]])
    agent = EdgeAgent(
        llm=ScriptedLLM([one, one, one]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.generate_options(routing_context=_routing_ctx())
    assert out.outcome == "manual_review"


# ---------------------------------------------------------------------------
# frame_reply() — schema + invariants.
# ---------------------------------------------------------------------------


def _signal(reply_kind: str = "counter", custom_text: str | None = None) -> dict:
    return {
        "id": "rs-1",
        "source_user_id": "u-maya",
        "target_user_id": "u-raj",
        "framing": "Drop permadeath?",
        "background_json": [],
        "options_json": _BASELINE_OPTIONS,
        "reply_json": {
            "picked_option_id": "opt-1",
            "picked_label": "Keep permadeath; add memento revive",
            "picked_kind": reply_kind,
            "custom_text": custom_text,
            "time_to_respond_ms": 12345,
        },
        "status": "replied",
    }


def _source_ctx() -> dict:
    return {
        "user": {
            "id": "u-maya",
            "username": "maya",
            "display_name": "Maya",
            "role": "pm",
        },
        "project": {
            "id": "p-roguelike",
            "title": "Roguelike v2",
            "member_summaries": [],
            "recent_decisions": [],
        },
        "recent_turns": [],
    }


@pytest.mark.asyncio
async def test_frame_reply_counter_back():
    payload = {
        "body": "Raj countered — keep permadeath, add memento revive.",
        "action_hint": "counter_back",
        "attach_options": True,
        "reasoning": "target picked counter",
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.frame_reply(signal=_signal(), source_user_context=_source_ctx())
    assert out.outcome == "ok"
    assert out.framed.action_hint == "counter_back"
    assert out.framed.attach_options is True


@pytest.mark.asyncio
async def test_frame_reply_accept():
    payload = {
        "body": "Raj approved as proposed.",
        "action_hint": "accept",
        "attach_options": False,
        "reasoning": "target accepted",
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.frame_reply(
        signal=_signal(reply_kind="accept"),
        source_user_context=_source_ctx(),
    )
    assert out.framed.action_hint == "accept"
    assert out.framed.attach_options is False


@pytest.mark.asyncio
async def test_frame_reply_rejects_extra_fields():
    bad = {
        "body": "something",
        "action_hint": "info_only",
        "attach_options": False,
        "reasoning": "x",
        "hidden_field": "nope",
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(bad)] * 3),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.frame_reply(signal=_signal(), source_user_context=_source_ctx())
    assert out.outcome == "manual_review"
    assert out.attempts == 3
    assert out.framed.action_hint == "info_only"


@pytest.mark.asyncio
async def test_frame_reply_recovery_ladder():
    agent = EdgeAgent(
        llm=ScriptedLLM(["bad", "still bad", "nope"]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.frame_reply(signal=_signal(), source_user_context=_source_ctx())
    assert out.outcome == "manual_review"
    assert out.attempts == 3


# ---------------------------------------------------------------------------
# Schema-level Pydantic guards.
# ---------------------------------------------------------------------------


def test_edge_response_schema_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        EdgeResponse.model_validate(
            {
                "kind": "explode",
                "body": "x",
                "reasoning": "",
                "route_targets": [],
            }
        )


def test_edge_response_schema_rejects_extras():
    with pytest.raises(ValidationError):
        EdgeResponse.model_validate(
            {
                "kind": "answer",
                "body": "x",
                "reasoning": "",
                "route_targets": [],
                "extra": 1,
            }
        )


def test_routed_options_batch_rejects_too_few():
    with pytest.raises(ValidationError):
        RoutedOptionsBatch.model_validate(
            {"options": [_BASELINE_OPTIONS[0]]}
        )


def test_routed_options_batch_rejects_too_many():
    five = [dict(_BASELINE_OPTIONS[0]) for _ in range(5)]
    with pytest.raises(ValidationError):
        RoutedOptionsBatch.model_validate({"options": five})


def test_routed_option_weight_bounds():
    with pytest.raises(ValidationError):
        RoutedOption.model_validate(
            {**_BASELINE_OPTIONS[0], "id": "x", "weight": 1.5}
        )


def test_framed_reply_rejects_unknown_action_hint():
    with pytest.raises(ValidationError):
        FramedReply.model_validate(
            {
                "body": "x",
                "action_hint": "do_something_unknown",
                "attach_options": False,
            }
        )


# ---------------------------------------------------------------------------
# Prompt-file hygiene — PROMPT_VERSION header format is part of the contract.
# ---------------------------------------------------------------------------


def test_prompt_files_have_prompt_version_header():
    from pathlib import Path
    import re

    root = (
        Path(__file__).parent.parent
        / "src"
        / "workgraph_agents"
        / "prompts"
        / "edge"
    )
    # phaseM still valid for reply_frame; v1.md + options_v1.md moved to
    # phaseQ in Phase Q (tool_call + self-route bug fix).
    pattern = re.compile(
        r"^PROMPT_VERSION: \d{4}-\d{2}-\d{2}\.phase[A-Z]\.v\d+$", re.M
    )
    for name in ("v1.md", "options_v1.md", "reply_frame_v1.md"):
        text = (root / name).read_text(encoding="utf-8")
        assert pattern.search(text), f"{name} missing PROMPT_VERSION header"


# ---------------------------------------------------------------------------
# Phase Q — tool_call kind + tightened routing + options anti-self-route.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_respond_tool_call_kb_search():
    """Agent can emit a structured kb_search tool call with preamble."""
    payload = {
        "kind": "tool_call",
        "body": "Let me check the KB for boss-1 notes.",
        "reasoning": "recall across KB items",
        "tool_call": {
            "name": "kb_search",
            "args": {"query": "boss 1 design", "limit": 3},
        },
        "route_targets": [],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(
        user_message="what's our current thinking on boss 1?", context=_ctx()
    )
    assert out.outcome == "ok"
    assert out.response.kind == "tool_call"
    assert out.response.tool_call is not None
    assert out.response.tool_call.name == "kb_search"
    assert out.response.tool_call.args == {"query": "boss 1 design", "limit": 3}
    assert out.response.body
    assert out.response.route_targets == []


@pytest.mark.asyncio
async def test_respond_tool_call_must_be_in_allowed_skills():
    """Unknown skill names fail the SkillName Literal — the recovery
    ladder either rescues (no retry content → manual_review) or the
    invariant coercer degrades to clarify on a malformed attempt.
    Either way, no tool_call with an unknown name surfaces."""
    payload = {
        "kind": "tool_call",
        "body": "Running fake_skill…",
        "reasoning": "x",
        "tool_call": {"name": "fake_skill", "args": {}},
        "route_targets": [],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)] * 3),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(user_message="x", context=_ctx())
    assert out.outcome == "manual_review"


@pytest.mark.asyncio
async def test_respond_tool_call_without_body_degrades_to_clarify():
    """tool_call kind without a preamble body is meaningless to the
    stream — degrade to clarify so the user isn't shown a silent spinner.
    """
    payload = {
        "kind": "tool_call",
        "body": "",
        "reasoning": "x",
        "tool_call": {"name": "kb_search", "args": {"query": "x"}},
        "route_targets": [],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(user_message="anything", context=_ctx())
    # Empty body via Pydantic default is None for the schema, so the LLM
    # attempt should succeed structurally and we fall into the coercer.
    assert out.response.kind == "clarify"


@pytest.mark.asyncio
async def test_respond_answer_prefers_over_route_for_factual():
    """Trigger-tightening: a factual recall question that the graph
    context already answers should produce `answer`, not
    `route_proposal`. This verifies the LLM behaviour is guided by the
    prompt — we pass a scripted answer (no route_proposal) and confirm
    the pipeline propagates it untouched.
    """
    payload = {
        "kind": "answer",
        "body": "D-12 says keep permadeath, revisit after playtest.",
        "reasoning": "factual lookup resolvable from recent_decisions",
        "route_targets": [],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(
        user_message="what did we decide on permadeath?", context=_ctx()
    )
    assert out.response.kind == "answer"
    assert out.response.route_targets == []
    assert out.response.tool_call is None


@pytest.mark.asyncio
async def test_respond_answer_strips_stray_tool_call():
    """If the LLM sets kind=answer but also fills tool_call, the invariant
    coercer should null out tool_call rather than accept the mixed shape.
    """
    payload = {
        "kind": "answer",
        "body": "Here's the answer.",
        "reasoning": "x",
        "tool_call": {"name": "kb_search", "args": {"query": "x"}},
        "route_targets": [],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(user_message="x", context=_ctx())
    assert out.response.kind == "answer"
    assert out.response.tool_call is None


@pytest.mark.asyncio
async def test_respond_silence_strips_stray_tool_call():
    """silence + stray tool_call collapses to clean silence."""
    payload = {
        "kind": "silence",
        "body": None,
        "reasoning": "ack",
        "tool_call": {"name": "kb_search", "args": {"query": "x"}},
        "route_targets": [],
    }
    agent = EdgeAgent(
        llm=ScriptedLLM([_dump(payload)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.respond(user_message="thx", context=_ctx())
    assert out.response.kind == "silence"
    assert out.response.tool_call is None
    assert out.response.body is None


def test_allowed_skills_contains_expected_four():
    assert ALLOWED_SKILLS == {
        "kb_search",
        "recent_decisions",
        "risk_scan",
        "member_profile",
    }


def test_tool_call_schema_rejects_unknown_name():
    with pytest.raises(ValidationError):
        ToolCall.model_validate({"name": "fake", "args": {}})


def test_tool_call_schema_accepts_each_allowed_skill():
    for name in ("kb_search", "recent_decisions", "risk_scan", "member_profile"):
        tc = ToolCall.model_validate({"name": name, "args": {"k": 1}})
        assert tc.name == name
        assert tc.args == {"k": 1}


def test_edge_response_schema_accepts_tool_call_kind():
    resp = EdgeResponse.model_validate(
        {
            "kind": "tool_call",
            "body": "preamble",
            "reasoning": "x",
            "tool_call": {"name": "kb_search", "args": {"query": "x"}},
            "route_targets": [],
        }
    )
    assert resp.kind == "tool_call"
    assert resp.tool_call is not None
    assert resp.tool_call.name == "kb_search"


# ---------------------------------------------------------------------------
# Options — anti-self-route + anti-re-route invariants (Phase Q.2).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_options_allowed_kinds_only():
    """Allowed kinds are exactly {accept, counter, escalate, custom}.
    Any batch whose options all stay in that set is fine — `route` is
    NOT a kind, so it is unrepresentable at the schema level."""
    agent = EdgeAgent(
        llm=ScriptedLLM([_options_payload(_BASELINE_OPTIONS)]),
        respond_prompt="p",
        options_prompt="o",
        reply_frame_prompt="r",
    )
    out = await agent.generate_options(routing_context=_routing_ctx())
    for opt in out.options:
        assert opt.kind in ("accept", "counter", "escalate", "custom")
        # Phase Q bug fix: options are replies, not routes. The label
        # should not be a routing dispatch verb. We allow "Escalate ..."
        # (escalate kind is fine) but not "Route to ...".
        assert not opt.label.lower().startswith("route to ")
        assert not opt.label.lower().startswith("forward to ")


def test_routed_option_kind_rejects_route():
    """Schema-level guard — `route` is not an OptionKind. Even a
    hypothetical "route" label would have to pick a legal kind, so
    self-route options cannot slip past the Pydantic layer."""
    with pytest.raises(ValidationError):
        RoutedOption.model_validate(
            {
                "id": "x",
                "label": "Route to aiko",
                "kind": "route",  # not in the Literal
                "background": "",
                "reason": "",
                "tradeoff": "",
                "weight": 0.5,
            }
        )
