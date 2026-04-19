"""DriftAgent unit tests — vision.md §5.8.

LLM is stubbed end-to-end — these tests never call DeepSeek. Same
`ScriptedLLM` pattern as test_edge.py: scripted raw completions, then
assertions on parsed structured output + the recovery ladder.
"""
from __future__ import annotations

import json
from typing import Iterable

import pytest
from pydantic import ValidationError

from workgraph_agents.drift import (
    DriftAgent,
    DriftCheckResult,
    DriftItem,
)
from workgraph_agents.llm import LLMClient, LLMResult, LLMSettings


# ---------------------------------------------------------------------------
# Stub LLM — scriptable content queue.
# ---------------------------------------------------------------------------


class ScriptedLLM(LLMClient):
    """Returns the next scripted completion per call, cycling through a
    list of strings. Never opens a network connection.
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
    """Minimal realistic drift-check context."""
    return {
        "project_id": "p-roguelike",
        "title": "Roguelike v2",
        "committed_thesis": (
            "Goal: Ship a permadeath roguelike with 3 biomes by March. "
            "Scope: core combat, boss rooms, permadeath, 3 biomes."
        ),
        "recent_decisions": [
            {
                "id": "D-12",
                "option_index": 0,
                "custom_text": None,
                "rationale": "Keep permadeath — core to genre",
                "resolver_id": "u-maya",
                "created_at": "2026-04-10T12:00:00Z",
                "apply_outcome": "ok",
            }
        ],
        "active_tasks": [
            {
                "id": "T-7",
                "title": "Add memento revive system",
                "description": "Softens permadeath via per-run revive tokens",
                "status": "in_progress",
                "assignee_role": "backend",
                "assignee_user_id": "u-raj",
            }
        ],
        "recent_completed_deliverables": [],
        "members": [
            {
                "user_id": "u-maya",
                "username": "maya",
                "display_name": "Maya",
                "role": "pm",
            },
            {
                "user_id": "u-raj",
                "username": "raj",
                "display_name": "Raj",
                "role": "game-design",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Happy paths — drift + clean.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_surfaces_drift_item():
    payload = {
        "has_drift": True,
        "drift_items": [
            {
                "headline": "Memento revive system weakens committed permadeath",
                "severity": "medium",
                "what_drifted": (
                    "Task T-7 in progress; adds per-run revive tokens."
                ),
                "vs_thesis_or_decision": (
                    "Decision D-12 committed to keeping permadeath."
                ),
                "suggested_next_step": "Raise with Maya this week.",
                "affected_user_ids": ["u-maya", "u-raj"],
            }
        ],
        "reasoning": "Active task contradicts explicit decision.",
    }
    agent = DriftAgent(llm=ScriptedLLM([_dump(payload)]), prompt="(prompt stub)")
    out = await agent.check(_ctx())
    assert out.outcome == "ok"
    assert out.attempts == 1
    assert out.result_payload.has_drift is True
    assert len(out.result_payload.drift_items) == 1
    item = out.result_payload.drift_items[0]
    assert item.severity == "medium"
    assert "permadeath" in item.headline.lower()
    assert item.affected_user_ids == ["u-maya", "u-raj"]


@pytest.mark.asyncio
async def test_check_clean_project_returns_no_drift():
    payload = {
        "has_drift": False,
        "drift_items": [],
        "reasoning": "Tasks cover scope items; no divergence.",
    }
    agent = DriftAgent(llm=ScriptedLLM([_dump(payload)]), prompt="(prompt stub)")
    out = await agent.check(_ctx())
    assert out.outcome == "ok"
    assert out.result_payload.has_drift is False
    assert out.result_payload.drift_items == []


# ---------------------------------------------------------------------------
# Cross-field invariants — has_drift must match drift_items emptiness.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_drift_false_with_items_is_normalised_to_empty():
    # Model says "no drift" but hands back items — coerce to [] rather
    # than burn a retry. Keeps the ladder smooth.
    payload = {
        "has_drift": False,
        "drift_items": [
            {
                "headline": "Phantom drift",
                "severity": "low",
                "what_drifted": "shouldn't be here",
                "vs_thesis_or_decision": "shouldn't be here",
                "suggested_next_step": "ignore",
                "affected_user_ids": [],
            }
        ],
        "reasoning": "x",
    }
    agent = DriftAgent(llm=ScriptedLLM([_dump(payload)]), prompt="p")
    out = await agent.check(_ctx())
    assert out.outcome == "ok"
    assert out.result_payload.has_drift is False
    assert out.result_payload.drift_items == []


@pytest.mark.asyncio
async def test_has_drift_true_with_no_items_is_normalised_to_false():
    # Symmetric: claims drift but no items → normalise to clean.
    payload = {
        "has_drift": True,
        "drift_items": [],
        "reasoning": "model mistake",
    }
    agent = DriftAgent(llm=ScriptedLLM([_dump(payload)]), prompt="p")
    out = await agent.check(_ctx())
    assert out.result_payload.has_drift is False
    assert out.result_payload.drift_items == []


# ---------------------------------------------------------------------------
# Recovery ladder — 3 bad responses → manual_review fallback.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_ladder_three_bad_jsons():
    agent = DriftAgent(
        llm=ScriptedLLM(["not json", "still not json", "nope"]),
        prompt="p",
    )
    out = await agent.check(_ctx())
    assert out.outcome == "manual_review"
    assert out.attempts == 3
    # Fallback is no-drift — never fabricate alerts on parse failure.
    assert out.result_payload.has_drift is False
    assert out.result_payload.drift_items == []


@pytest.mark.asyncio
async def test_pydantic_forbids_extra_fields():
    bad = {
        "has_drift": False,
        "drift_items": [],
        "reasoning": "x",
        "extra_field": "not allowed",
    }
    agent = DriftAgent(
        llm=ScriptedLLM([_dump(bad)] * 3),
        prompt="p",
    )
    out = await agent.check(_ctx())
    assert out.outcome == "manual_review"
    assert out.attempts == 3
    assert out.error is not None
    # Safe no-drift fallback.
    assert out.result_payload.has_drift is False


# ---------------------------------------------------------------------------
# Schema-level Pydantic guards.
# ---------------------------------------------------------------------------


def test_drift_item_rejects_unknown_severity():
    with pytest.raises(ValidationError):
        DriftItem.model_validate(
            {
                "headline": "x",
                "severity": "catastrophic",  # not in Literal
                "what_drifted": "x",
                "vs_thesis_or_decision": "x",
                "suggested_next_step": "x",
                "affected_user_ids": [],
            }
        )


def test_drift_item_rejects_extras():
    with pytest.raises(ValidationError):
        DriftItem.model_validate(
            {
                "headline": "x",
                "severity": "low",
                "what_drifted": "x",
                "vs_thesis_or_decision": "x",
                "suggested_next_step": "x",
                "affected_user_ids": [],
                "hidden": 1,
            }
        )


def test_drift_check_result_caps_items_at_five():
    # max_length=5 on drift_items.
    items = [
        {
            "headline": f"h{i}",
            "severity": "low",
            "what_drifted": "x",
            "vs_thesis_or_decision": "x",
            "suggested_next_step": "x",
            "affected_user_ids": [],
        }
        for i in range(6)
    ]
    with pytest.raises(ValidationError):
        DriftCheckResult.model_validate(
            {"has_drift": True, "drift_items": items, "reasoning": ""}
        )


# ---------------------------------------------------------------------------
# Prompt file hygiene.
# ---------------------------------------------------------------------------


def test_prompt_file_has_prompt_version_header():
    from pathlib import Path
    import re

    root = (
        Path(__file__).parent.parent
        / "src"
        / "workgraph_agents"
        / "prompts"
        / "drift"
    )
    pattern = re.compile(r"^PROMPT_VERSION: \d{4}-\d{2}-\d{2}\.drift\.v\d+$", re.M)
    text = (root / "v1.md").read_text(encoding="utf-8")
    assert pattern.search(text), "drift/v1.md missing PROMPT_VERSION header"
