"""Phase R v1 — Scene 1 (discovery) + Scene 2 (gated) routing tests.

Unit-level coverage for the new `route_kind` / `decision_class` fields
on EdgeResponse and the coercion rules in `_coerce_response_invariants`.

These tests are prompt-text-free — they feed scripted JSON into the
agent and verify the schema + cross-field invariants behave as
specified in `prompts/edge/v1.md` §"Output schema". The backend-side
context injection (gate_keeper_map flowing into the LLM payload) has
its own tests under apps/api/tests/.
"""
from __future__ import annotations

import json

import pytest

from workgraph_agents import (
    VALID_DECISION_CLASSES,
    EdgeAgent,
    EdgeResponse,
)
from workgraph_agents.edge import (
    PROMPT_VERSION,
    _coerce_response_invariants,
)
from workgraph_agents.llm import LLMClient, LLMResult, LLMSettings


class _ScriptedLLM(LLMClient):
    """Scripted LLM stub — matches the ScriptedLLM shape already in use
    across the agents test suite. Signature mirrors LLMClient.complete
    so the structured-completion wrapper works without its usual
    DeepSeek-bound kwargs blowing up.
    """

    def __init__(self, script: list[str]) -> None:
        self._settings = LLMSettings.model_construct(
            api_key="test-not-used",
            base_url="http://stub",
            model="stub-model",
        )
        self._client = None
        self._script = list(script)

    async def complete(
        self,
        messages,
        *,
        model=None,
        temperature: float = 0.1,
        response_format=None,
    ) -> LLMResult:
        if not self._script:
            raise AssertionError("scripted LLM exhausted")
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


def _ctx(*, gate_keeper_map: dict | None = None) -> dict:
    return {
        "user": {
            "id": "u-maya",
            "username": "maya",
            "display_name": "Maya",
            "role": "pm",
            "declared_abilities": ["product"],
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
                    "abilities": ["systems"],
                }
            ],
            "recent_decisions": [],
            "open_risks": [],
            "active_tasks": [],
            "gate_keeper_map": gate_keeper_map or {},
            "valid_decision_classes": sorted(VALID_DECISION_CLASSES),
        },
        "recent_turns": [],
        "kb_slice": [],
    }


# ---- prompt version ----------------------------------------------------


def test_prompt_version_bumped_to_phase_r_v1():
    # v3 → v4 was the Scene 2 introduction. PROMPT_VERSION is pinned so
    # the agent_run_log correlates responses with the prompt that produced
    # them; if this constant drifts from prompts/edge/v1.md, split-brain
    # deployments stop being auditable.
    assert PROMPT_VERSION == "2026-04-23.phaseR.v1"


# ---- Scene 1: discovery route -----------------------------------------


@pytest.mark.asyncio
async def test_discovery_route_carries_route_kind_and_null_class():
    payload = {
        "kind": "route_proposal",
        "body": "Raj owns 5 of 7 permadeath-adjacent tasks.",
        "reasoning": "routing_suggest scored Raj at 0.87",
        "route_kind": "discovery",
        "decision_class": None,
        "route_targets": [
            {
                "user_id": "u-raj",
                "username": "raj",
                "display_name": "Raj",
                "rationale": "routing_suggest 0.87",
            }
        ],
    }
    agent = EdgeAgent(
        llm=_ScriptedLLM([_dump(payload)]),
        respond_prompt="(stub)",
        options_prompt="(stub)",
        reply_frame_prompt="(stub)",
    )
    out = await agent.respond(
        user_message="who owns permadeath?", context=_ctx()
    )
    assert out.response.kind == "route_proposal"
    assert out.response.route_kind == "discovery"
    assert out.response.decision_class is None
    assert len(out.response.route_targets) == 1
    assert out.response.route_targets[0].user_id == "u-raj"


# ---- Scene 2: gated route -----------------------------------------------


@pytest.mark.asyncio
async def test_gated_route_with_valid_class_and_mapped_gate_keeper():
    payload = {
        "kind": "route_proposal",
        "body": "Scope cut — Maya gates scope decisions. Want to send it for sign-off?",
        "reasoning": "scope_cut is gated; caller is Raj (not the gate-keeper)",
        "route_kind": "gated",
        "decision_class": "scope_cut",
        "route_targets": [
            {
                "user_id": "u-maya",
                "username": "maya",
                "display_name": "Maya",
                "rationale": "scope_cut gate-keeper",
            }
        ],
    }
    agent = EdgeAgent(
        llm=_ScriptedLLM([_dump(payload)]),
        respond_prompt="(stub)",
        options_prompt="(stub)",
        reply_frame_prompt="(stub)",
    )
    out = await agent.respond(
        user_message="cutting the airlock rework",
        context=_ctx(gate_keeper_map={"scope_cut": "u-maya"}),
    )
    assert out.response.kind == "route_proposal"
    assert out.response.route_kind == "gated"
    assert out.response.decision_class == "scope_cut"
    assert len(out.response.route_targets) == 1
    assert out.response.route_targets[0].user_id == "u-maya"


# ---- coercion: degradations --------------------------------------------


def test_coerce_gated_missing_class_degrades_to_discovery():
    """LLM emitted route_kind='gated' but didn't set decision_class.
    We cannot safely dispatch a gated proposal without the class, so
    degrade to 'discovery' + null class; the card still renders and
    the user gets a candidate to ask, just not a sign-off card.
    """
    resp = EdgeResponse(
        kind="route_proposal",
        body="x",
        route_kind="gated",
        decision_class=None,
        route_targets=[
            {"user_id": "u-raj", "username": "raj", "display_name": "Raj"}
        ],
    )
    coerced = _coerce_response_invariants(resp)
    assert coerced.route_kind == "discovery"
    assert coerced.decision_class is None
    assert "degraded" in coerced.reasoning.lower()


def test_coerce_gated_invalid_class_degrades_to_discovery():
    """Class not in VALID_DECISION_CLASSES (e.g. Pydantic might accept
    an unknown Literal on reprompt retry, or an older client could POST
    a stale one). Treated identically to missing — degrade to discovery.
    """
    resp = EdgeResponse(
        kind="route_proposal",
        body="x",
        route_kind="gated",
        # Force the invalid class past Pydantic by constructing via dict.
        # The coercion step is the last line of defense when the schema
        # accepts a value the service would reject.
        route_targets=[
            {"user_id": "u-raj", "username": "raj", "display_name": "Raj"}
        ],
    )
    # Manually poke in an invalid class to exercise the coercion path —
    # Pydantic's Literal validation would normally catch this, but we
    # want the coercion to behave safely even if Pydantic is bypassed
    # (e.g. a future prompt revision broadens the Literal).
    object.__setattr__(resp, "decision_class", "fiction")
    coerced = _coerce_response_invariants(resp)
    assert coerced.route_kind == "discovery"
    assert coerced.decision_class is None


def test_coerce_gated_multiple_targets_keeps_only_first():
    """Gated route must have exactly ONE target (the named gate-keeper).
    Multiple targets on a gated route is an LLM error — keep the first,
    drop the rest.
    """
    resp = EdgeResponse(
        kind="route_proposal",
        body="x",
        route_kind="gated",
        decision_class="legal",
        route_targets=[
            {"user_id": "u-maya", "username": "maya", "display_name": "Maya"},
            {"user_id": "u-raj", "username": "raj", "display_name": "Raj"},
        ],
    )
    coerced = _coerce_response_invariants(resp)
    assert coerced.route_kind == "gated"
    assert len(coerced.route_targets) == 1
    assert coerced.route_targets[0].user_id == "u-maya"


def test_coerce_route_proposal_without_kind_defaults_to_discovery():
    """LLM left route_kind out on a route_proposal. Default to discovery
    (the non-destructive interpretation — no decision is gated).
    """
    resp = EdgeResponse(
        kind="route_proposal",
        body="x",
        route_targets=[
            {"user_id": "u-raj", "username": "raj", "display_name": "Raj"}
        ],
    )
    coerced = _coerce_response_invariants(resp)
    assert coerced.route_kind == "discovery"


# ---- coercion: cleanup on non-routing kinds ---------------------------


def test_coerce_answer_with_stray_route_kind_clears_it():
    resp = EdgeResponse(
        kind="answer",
        body="Yes, D-12 settled it.",
        route_kind="gated",
        decision_class="budget",
    )
    coerced = _coerce_response_invariants(resp)
    assert coerced.kind == "answer"
    assert coerced.route_kind is None
    assert coerced.decision_class is None


def test_coerce_silence_with_stray_routing_state_clears_everything():
    resp = EdgeResponse(
        kind="silence",
        body=None,
        route_kind="discovery",
        decision_class="budget",
        route_targets=[
            {"user_id": "u-raj", "username": "raj", "display_name": "Raj"}
        ],
    )
    coerced = _coerce_response_invariants(resp)
    assert coerced.kind == "silence"
    assert coerced.route_kind is None
    assert coerced.decision_class is None
    assert coerced.route_targets == []
    assert coerced.body is None


def test_coerce_discovery_with_stray_decision_class_clears_class():
    """Discovery routes must have decision_class=None (class is only
    meaningful for gated). LLM mistake → clear the class, keep the
    route_kind.
    """
    resp = EdgeResponse(
        kind="route_proposal",
        body="x",
        route_kind="discovery",
        decision_class="scope_cut",  # invalid for discovery
        route_targets=[
            {"user_id": "u-raj", "username": "raj", "display_name": "Raj"}
        ],
    )
    coerced = _coerce_response_invariants(resp)
    assert coerced.route_kind == "discovery"
    assert coerced.decision_class is None
