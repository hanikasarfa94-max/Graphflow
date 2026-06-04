"""Deterministic demo EdgeAgent — DEMO/DEV ONLY.

Gated behind WORKGRAPH_USE_STUBS=true AND WORKGRAPH_DEMO_ROUTING=true (see
main.py wiring). This is NOT production behavior: the real DeepSeek-backed
EdgeAgent runs whenever use_stubs is false. This fixture exists so the
disappearing-broker loop demos reliably without depending on LLM
non-determinism — it always proposes a route to a project teammate when the
user asks a question, and returns canned reply options + a framed reply so
the full send→reply→accept loop runs end to end.

The decision logic is intentionally trivial and pure-function-extracted so
it is unit-testable without booting the app.
"""
from __future__ import annotations

from typing import Any

from workgraph_agents import (
    EdgeResponse,
    EdgeResponseOutcome,
    FramedReply,
    FramedReplyOutcome,
    RoutedOption,
    RoutedOptionsOutcome,
    RouteTarget,
)
from workgraph_agents.llm import LLMResult


def _stub_result() -> LLMResult:
    return LLMResult(
        content="",
        model="demo-stub",
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=0,
    )


def looks_like_question(message: str | None) -> bool:
    """Trivial heuristic: long-enough text with a question mark (latin or CJK)."""
    m = (message or "").strip()
    return len(m) >= 8 and ("?" in m or "？" in m)


def pick_target(teammates: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """First teammate with a user_id. The broker demo seed ensures exactly
    one grounded recipient, so dispatch grounding can never 422."""
    for t in teammates or []:
        if t.get("user_id"):
            return t
    return None


def build_rationale(target: dict[str, Any]) -> str:
    abilities = [a for a in (target.get("abilities") or []) if a]
    if abilities:
        return f"Knows {', '.join(abilities[:2])}."
    role = target.get("role")
    if role and role not in ("member", "admin"):
        return f"Owns the {role} side."
    return "Came up as the person who'd know."


def build_b_facing_draft(message: str | None, display_name: str) -> str:
    q = (message or "").strip().rstrip("?？").strip()
    return f"{display_name} — quick one: {q}? You came up as the person who'd know."


class DemoEdgeAgent:
    """Deterministic stand-in EdgeAgent for the broker demo."""

    async def respond(self, *, user_message, context):
        teammates = (context or {}).get("teammates") or []
        target = pick_target(teammates)
        if target is not None and looks_like_question(user_message):
            display = (
                target.get("display_name")
                or target.get("username")
                or "Teammate"
            )
            rt = RouteTarget(
                user_id=target["user_id"],
                username=target.get("username") or "teammate",
                display_name=display,
                rationale=build_rationale(target),
                b_facing_draft=build_b_facing_draft(user_message, display),
            )
            return EdgeResponseOutcome(
                response=EdgeResponse(
                    kind="route_proposal",
                    body=(user_message or "").strip(),
                    route_targets=[rt],
                ),
                result=_stub_result(),
                outcome="ok",
                attempts=1,
            )
        # Non-question / no teammate → silence, matching the prior demo stub.
        return EdgeResponseOutcome(
            response=EdgeResponse(kind="silence", body=None, route_targets=[]),
            result=_stub_result(),
            outcome="ok",
            attempts=1,
        )

    async def generate_options(self, *, routing_context):
        options = [
            RoutedOption(
                id="yes",
                label="Yes, go ahead",
                kind="accept",
                background="",
                reason="Straightforward to do.",
                tradeoff="None notable.",
                weight=0.7,
            ),
            RoutedOption(
                id="more",
                label="Need a bit more detail",
                kind="custom",
                background="",
                reason="One clarification first.",
                tradeoff="Adds a round-trip.",
                weight=0.3,
            ),
        ]
        return RoutedOptionsOutcome(
            options=options,
            result=_stub_result(),
            outcome="ok",
            attempts=1,
        )

    async def frame_reply(self, *, signal, source_user_context):
        return FramedReplyOutcome(
            framed=FramedReply(
                body="They got back to you — you're clear to proceed.",
                action_hint="accept",
            ),
            result=_stub_result(),
            outcome="ok",
            attempts=1,
        )
