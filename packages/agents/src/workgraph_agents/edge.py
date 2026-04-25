"""EdgeAgent — Phase M (per-user sub-agent).

Each human on the platform has exactly one sub-agent identity. The EdgeAgent
owns three LLM-backed methods that correspond to the three legs of the
canonical interaction described in docs/north-star.md ("Sub-agent and
routing architecture"):

  * `respond(user_message, context)` — the agent's reply inside the user's
    personal project stream. Four output kinds: answer / clarify /
    route_proposal / silence. `silence` is first-class so acknowledgements
    don't flood the stream with empty edge turns.

  * `generate_options(routing_context)` — when a routed signal lands in the
    *target* user's stream, the target's sub-agent produces 2–4 rich option
    cards (label / background / reason / tradeoff / weight) the target can
    pick in one click. Weighting is sensitive to `target_response_profile`:
    if the target's history shows they usually counter rather than accept,
    counter-kind options are nudged higher so the surfaced options match
    how the target actually decides.

  * `frame_reply(signal, source_user_context)` — when the target replies,
    the source's sub-agent re-frames the reply in the source's voice and
    suggests the source's next action (accept / counter_back / info_only).

The agent is pure: it produces structured outputs the backend service
persists as RoutedSignalRow. Phase L owns persistence.

Recovery ladder matches every other phase-3+ agent (decision 2C4):
  1) JSON mode with Pydantic validation.
  2) On JSON / schema error: reprompt with the error, up to 3 attempts.
  3) After 3 attempts: deterministic manual-review fallback +
     outcome="manual_review" so the caller can surface a chip.

Prompt contracts stay provider-agnostic — DeepSeek in dev (per the
project memory), but nothing in the prompts or the client is DeepSeek-
specific, so caching / eval can re-benchmark on provider switch.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .citations import CitedClaim
from .llm import LLMClient, LLMResult, ParseFailure

_log = logging.getLogger("workgraph.agents.edge")

PROMPT_VERSION = "2026-04-23.phaseR.v1"
OPTIONS_PROMPT_VERSION = "2026-04-18.phaseQ.v1"
REPLY_FRAME_PROMPT_VERSION = "2026-04-21.phaseM.v2"

# Skill catalog exposed to the EdgeAgent respond prompt. Kept in code so
# the backend dispatcher and the prompt text reference the same list —
# anything outside this set is rejected at the service layer.
ALLOWED_SKILLS = frozenset(
    {
        "kb_search",
        "recent_decisions",
        "risk_scan",
        "member_profile",
        "why_chain",
        "routing_suggest",
        # `propose_wiki_entry` lets the edge agent nominate a chunk of
        # the current conversation as a group-scope KB (wiki) draft.
        # The dispatcher creates the row as status='draft' so the
        # owner approves before it joins the canonical group context.
        "propose_wiki_entry",
    }
)

_PROMPT_DIR = Path(__file__).parent / "prompts" / "edge"


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


Outcome = Literal["ok", "retry", "manual_review"]
EdgeKind = Literal["answer", "clarify", "tool_call", "route_proposal", "silence"]
OptionKind = Literal["accept", "counter", "escalate", "custom"]
ActionHint = Literal["accept", "counter_back", "info_only"]
SkillName = Literal[
    "kb_search",
    "recent_decisions",
    "risk_scan",
    "member_profile",
    "why_chain",
    "routing_suggest",
]
# Phase v4 — Scene 2 routing taxonomy. Only two kinds in v0:
#   'discovery' — graph-signal-grounded candidate surfacing (Scene 1)
#   'gated'     — decision-class sign-off (Scene 2; decision_class set)
RouteKind = Literal["discovery", "gated"]
# Mirrors gated_proposals.VALID_DECISION_CLASSES — kept in the agent
# package so edge prompt tests can reference it without importing the
# api package. Adding a class requires both edges to be in sync.
VALID_DECISION_CLASSES = frozenset({"budget", "legal", "hire", "scope_cut"})
DecisionClass = Literal["budget", "legal", "hire", "scope_cut"]


# ---------------------------------------------------------------------------
# respond()
# ---------------------------------------------------------------------------


class RouteTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    username: str = Field(min_length=1, max_length=120)
    display_name: str = Field(default="", max_length=200)
    rationale: str = Field(default="", max_length=240)


class ToolCall(BaseModel):
    """Structured skill invocation request emitted by EdgeAgent.respond().

    `name` must be one of ALLOWED_SKILLS; `args` is a shallow dict whose
    shape is validated at the SkillsService layer (the agent prompt
    documents the expected shape per skill, but we keep the Pydantic
    here permissive so prompt iterations don't have to reshape this
    class for every new argument).
    """

    model_config = ConfigDict(extra="forbid")

    name: SkillName
    args: dict[str, Any] = Field(default_factory=dict)


class EdgeResponse(BaseModel):
    """Structured output of EdgeAgent.respond().

    `body` is required for answer / clarify / route_proposal / tool_call;
    must be None for `silence`. `tool_call` is only populated when
    kind="tool_call"; `route_targets` only when kind="route_proposal".

    Phase 1.B — `claims` carries structured `{text, citations[]}` so every
    substantive sentence in the reply can be chip-linked to the graph/KB
    node that backs it. Empty / absent `claims` is tolerated: the service
    wraps the plain `body` and flags the turn `uncited` for the UI.
    """

    model_config = ConfigDict(extra="forbid")

    kind: EdgeKind
    body: str | None = Field(default=None, max_length=2000)
    reasoning: str = Field(default="", max_length=240)
    tool_call: ToolCall | None = None
    route_targets: list[RouteTarget] = Field(default_factory=list)
    # Phase v4 — Scene 2 routing. `route_kind` is only meaningful when
    # `kind == 'route_proposal'`. `decision_class` is only meaningful
    # when `route_kind == 'gated'`. Both null otherwise. Cross-field
    # invariants (gated → class-in-enum, gated → exactly 1 target)
    # live in `_coerce_response_invariants` so one-field mistakes
    # degrade cleanly instead of blowing up the whole response.
    route_kind: RouteKind | None = None
    decision_class: DecisionClass | None = None
    claims: list[CitedClaim] = Field(default_factory=list, max_length=8)

    @field_validator("route_targets")
    @classmethod
    def _cap_targets(cls, v: list[RouteTarget]) -> list[RouteTarget]:
        # v1: at most 3 targets. Keep it simple — prefer earlier items.
        if len(v) > 3:
            return v[:3]
        return v


@dataclass(slots=True)
class EdgeResponseOutcome:
    response: EdgeResponse
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


_RESPONSE_MANUAL_REVIEW_FALLBACK = EdgeResponse(
    kind="clarify",
    body=(
        "I hit a snag generating a reply. Could you rephrase or give me one "
        "more line of context?"
    ),
    reasoning="edge respond manual review fallback",
    route_targets=[],
)


# ---------------------------------------------------------------------------
# generate_options()
# ---------------------------------------------------------------------------


class RoutedOption(BaseModel):
    """One option card the target user sees in their routed-inbound turn.

    Shape comes from docs/north-star.md "Option design for routed inbound":
    label / background / reason / tradeoff + weight + kind. `id` is a UUID4
    the agent mints so downstream (backend service) can persist stable refs
    to the target's pick without reshaping the list.
    """

    model_config = ConfigDict(extra="forbid")

    # NOTE: empty `id` is tolerated at the Pydantic layer on purpose — the
    # options-prompt explicitly allows the LLM to hand back "" so the
    # RoutedOptionsBatch validator can mint stable UUID4s. `_ensure_ids`
    # guarantees every option in the public output has a non-empty id.
    id: str = Field(default="")
    label: str = Field(min_length=1, max_length=60)
    kind: OptionKind
    background: str = Field(default="", max_length=240)
    reason: str = Field(default="", max_length=120)
    tradeoff: str = Field(default="", max_length=120)
    weight: float = Field(ge=0.0, le=1.0)


class RoutedOptionsBatch(BaseModel):
    """Internal container the LLM populates. We expose `list[RoutedOption]`
    from the public method, but complete_structured needs a single root
    Pydantic class, so we wrap.
    """

    model_config = ConfigDict(extra="forbid")

    options: list[RoutedOption] = Field(min_length=2, max_length=4)

    @field_validator("options")
    @classmethod
    def _ensure_ids(cls, v: list[RoutedOption]) -> list[RoutedOption]:
        # If the LLM leaves ids blank or hands back duplicates, mint new
        # UUID4s. Stable ids are the contract the backend relies on.
        seen: set[str] = set()
        fixed: list[RoutedOption] = []
        for opt in v:
            oid = opt.id.strip() if isinstance(opt.id, str) else ""
            if not oid or oid in seen:
                oid = str(uuid.uuid4())
            seen.add(oid)
            if oid != opt.id:
                opt = opt.model_copy(update={"id": oid})
            fixed.append(opt)
        return fixed


@dataclass(slots=True)
class RoutedOptionsOutcome:
    options: list[RoutedOption]
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


def _options_manual_review_fallback() -> list[RoutedOption]:
    """Deterministic two-option fallback when option-generation fails.

    Lets the target user still respond (accept-minimal / decline-for-now)
    instead of blocking on a failed LLM call.
    """
    return [
        RoutedOption(
            id=str(uuid.uuid4()),
            label="Accept as proposed",
            kind="accept",
            background="Auto-generated options unavailable; review the source framing.",
            reason="Minimal action so the source is not blocked.",
            tradeoff="No negotiation applied; trust the source framing.",
            weight=0.5,
        ),
        RoutedOption(
            id=str(uuid.uuid4()),
            label="Need more context",
            kind="custom",
            background="Auto-generated options unavailable; review the source framing.",
            reason="Signals you need more before committing.",
            tradeoff="Adds one round-trip; delays the decision.",
            weight=0.5,
        ),
    ]


# ---------------------------------------------------------------------------
# frame_reply()
# ---------------------------------------------------------------------------


class FramedReply(BaseModel):
    """Structured output of EdgeAgent.frame_reply().

    The source's sub-agent summarizes the target's reply back to the source.
    `action_hint` drives which affordance the source's stream surfaces next;
    `attach_options` tells the UI to regenerate a fresh option set (e.g.
    when the target countered and the source now needs to pick
    accept/counter-back/escalate).

    Phase 1.B — `claims` carries structured `{text, citations[]}` so the
    framed summary's claims can be chip-linked to the graph/KB nodes
    that back them. Empty `claims` → service wraps `body` and flags
    the turn `uncited` for the UI.
    """

    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=1200)
    action_hint: ActionHint
    attach_options: bool = False
    reasoning: str = Field(default="", max_length=240)
    claims: list[CitedClaim] = Field(default_factory=list, max_length=8)


@dataclass(slots=True)
class FramedReplyOutcome:
    framed: FramedReply
    result: LLMResult
    outcome: Outcome
    attempts: int
    error: str | None = None


_FRAMED_REPLY_MANUAL_REVIEW_FALLBACK = FramedReply(
    body=(
        "Your peer replied, but I couldn't re-frame it cleanly. Open the "
        "routed signal to read it in the source form."
    ),
    action_hint="info_only",
    attach_options=False,
    reasoning="frame_reply manual review fallback",
)


# ---------------------------------------------------------------------------
# Helpers — user payload serialization.
# ---------------------------------------------------------------------------


def _dump_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _build_respond_payload(
    *,
    user_message: str,
    context: dict[str, Any],
) -> str:
    return _dump_json(
        {
            "user_message": user_message,
            "context": context,
        }
    )


def _build_options_payload(routing_context: dict[str, Any]) -> str:
    return _dump_json({"routing_context": routing_context})


def _build_reply_frame_payload(
    *,
    signal: dict[str, Any],
    source_user_context: dict[str, Any],
) -> str:
    return _dump_json(
        {
            "signal": signal,
            "source_user_context": source_user_context,
        }
    )


# ---------------------------------------------------------------------------
# EdgeAgent
# ---------------------------------------------------------------------------


class EdgeAgent:
    """The per-user sub-agent.

    One instance owns all three LLM legs — the concrete prompts are loaded
    from `prompts/edge/*.md` so they're swappable without touching the
    class body. Tests pass custom prompts (or stub the LLM) to keep
    behaviour deterministic without reaching the network.
    """

    prompt_version = PROMPT_VERSION
    options_prompt_version = OPTIONS_PROMPT_VERSION
    reply_frame_prompt_version = REPLY_FRAME_PROMPT_VERSION

    def __init__(
        self,
        llm: LLMClient | None = None,
        *,
        respond_prompt: str | None = None,
        options_prompt: str | None = None,
        reply_frame_prompt: str | None = None,
    ) -> None:
        self._llm = llm or LLMClient()
        self._respond_prompt = respond_prompt or _load_prompt("v1")
        self._options_prompt = options_prompt or _load_prompt("options_v1")
        self._reply_frame_prompt = reply_frame_prompt or _load_prompt(
            "reply_frame_v1"
        )

    # -- respond -----------------------------------------------------------

    async def respond(
        self,
        *,
        user_message: str,
        context: dict[str, Any],
    ) -> EdgeResponseOutcome:
        messages = [
            {"role": "system", "content": self._respond_prompt},
            {
                "role": "user",
                "content": _build_respond_payload(
                    user_message=user_message, context=context
                ),
            },
        ]
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=EdgeResponse,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "edge.respond failed — manual review",
                extra={
                    "prompt_version": self.prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return EdgeResponseOutcome(
                response=_RESPONSE_MANUAL_REVIEW_FALLBACK,
                result=last
                or LLMResult(
                    content="",
                    model=self._llm.settings.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0,
                ),
                outcome="manual_review",
                attempts=len(e.errors),
                error=e.errors[-1] if e.errors else "unknown",
            )

        assert isinstance(parsed, EdgeResponse)
        parsed = _coerce_response_invariants(parsed)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "edge.responded",
            extra={
                "prompt_version": self.prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "kind": parsed.kind,
                "route_targets": len(parsed.route_targets),
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return EdgeResponseOutcome(
            response=parsed,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )

    # -- generate_options --------------------------------------------------

    async def generate_options(
        self,
        *,
        routing_context: dict[str, Any],
    ) -> RoutedOptionsOutcome:
        messages = [
            {"role": "system", "content": self._options_prompt},
            {
                "role": "user",
                "content": _build_options_payload(routing_context),
            },
        ]
        try:
            batch, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=RoutedOptionsBatch,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "edge.options_generated failed — manual review",
                extra={
                    "options_prompt_version": self.options_prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return RoutedOptionsOutcome(
                options=_options_manual_review_fallback(),
                result=last
                or LLMResult(
                    content="",
                    model=self._llm.settings.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0,
                ),
                outcome="manual_review",
                attempts=len(e.errors),
                error=e.errors[-1] if e.errors else "unknown",
            )

        assert isinstance(batch, RoutedOptionsBatch)
        options = _apply_profile_weighting(
            batch.options,
            routing_context.get("target_response_profile") or {},
        )
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "edge.options_generated",
            extra={
                "options_prompt_version": self.options_prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "option_count": len(options),
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return RoutedOptionsOutcome(
            options=options,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )

    # -- frame_reply -------------------------------------------------------

    async def frame_reply(
        self,
        *,
        signal: dict[str, Any],
        source_user_context: dict[str, Any],
    ) -> FramedReplyOutcome:
        messages = [
            {"role": "system", "content": self._reply_frame_prompt},
            {
                "role": "user",
                "content": _build_reply_frame_payload(
                    signal=signal,
                    source_user_context=source_user_context,
                ),
            },
        ]
        try:
            parsed, result, attempts = await self._llm.complete_structured(
                messages,
                pydantic_cls=FramedReply,
                max_attempts=3,
            )
        except ParseFailure as e:
            last = e.last_result
            _log.error(
                "edge.reply_framed failed — manual review",
                extra={
                    "reply_frame_prompt_version": self.reply_frame_prompt_version,
                    "attempts": len(e.errors),
                    "last_error": e.errors[-1] if e.errors else None,
                },
            )
            return FramedReplyOutcome(
                framed=_FRAMED_REPLY_MANUAL_REVIEW_FALLBACK,
                result=last
                or LLMResult(
                    content="",
                    model=self._llm.settings.model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=0,
                ),
                outcome="manual_review",
                attempts=len(e.errors),
                error=e.errors[-1] if e.errors else "unknown",
            )

        assert isinstance(parsed, FramedReply)
        outcome: Outcome = "ok" if attempts == 1 else "retry"
        _log.info(
            "edge.reply_framed",
            extra={
                "reply_frame_prompt_version": self.reply_frame_prompt_version,
                "outcome": outcome,
                "attempts": attempts,
                "action_hint": parsed.action_hint,
                "attach_options": parsed.attach_options,
                "latency_ms": result.latency_ms,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "cache_read_tokens": result.cache_read_tokens,
            },
        )
        return FramedReplyOutcome(
            framed=parsed,
            result=result,
            outcome=outcome,
            attempts=attempts,
        )


# ---------------------------------------------------------------------------
# Helpers — invariants + profile-aware weighting.
# ---------------------------------------------------------------------------


def _coerce_response_invariants(resp: EdgeResponse) -> EdgeResponse:
    """Apply the cross-field rules Pydantic can't cleanly express.

    Rather than fail the whole response on a small shape issue (which would
    just burn a retry), we normalize:
      - `silence` must have `body=None`, no `tool_call`, empty `route_targets`
      - `answer` / `clarify` must not have `tool_call` or `route_targets`
      - `tool_call` must have a ToolCall populated and non-empty body
        (preamble); if the LLM missed either, degrade to `clarify`.
      - `route_proposal` must have at least one `route_targets` entry;
        if the LLM missed it, degrade to `clarify` so the user isn't
        shown an action they can't take.
    """
    # Non-routing kinds: route_kind + decision_class MUST both be null.
    # Tool_call / answer / clarify / silence don't carry routing state.
    if resp.kind != "route_proposal":
        updates: dict[str, Any] = {}
        if resp.route_kind is not None:
            updates["route_kind"] = None
        if resp.decision_class is not None:
            updates["decision_class"] = None

        if resp.kind == "silence":
            if (
                resp.body is not None
                or resp.tool_call is not None
                or resp.route_targets
            ):
                updates.update(
                    {"body": None, "tool_call": None, "route_targets": []}
                )
            return resp.model_copy(update=updates) if updates else resp
        if resp.kind in ("answer", "clarify"):
            if resp.tool_call is not None or resp.route_targets:
                updates.update({"tool_call": None, "route_targets": []})
            return resp.model_copy(update=updates) if updates else resp
        # tool_call
        if resp.tool_call is None or not (resp.body or "").strip():
            updates.update(
                {
                    "kind": "clarify",
                    "body": (
                        resp.body
                        or "I'd like to run a skill to answer this — what specifically should I look up?"
                    ),
                    "tool_call": None,
                    "route_targets": [],
                    "reasoning": (
                        (resp.reasoning or "")
                        + " [degraded: tool_call without name/args or preamble]"
                    )[:240],
                }
            )
            return resp.model_copy(update=updates)
        if resp.route_targets:
            updates["route_targets"] = []
        return resp.model_copy(update=updates) if updates else resp

    # ---- route_proposal path ------------------------------------------
    # Must carry at least one target.
    if not resp.route_targets:
        return resp.model_copy(
            update={
                "kind": "clarify",
                "tool_call": None,
                "route_targets": [],
                "route_kind": None,
                "decision_class": None,
                "reasoning": (
                    (resp.reasoning or "")
                    + " [degraded: route_proposal without targets]"
                )[:240],
            }
        )

    updates: dict[str, Any] = {}
    if resp.tool_call is not None:
        updates["tool_call"] = None

    # v4: route_kind MUST be set on route_proposal. Missing route_kind
    # is treated as 'discovery' (the backwards-compat default) so the
    # service still renders a routing card instead of dropping the turn.
    route_kind = resp.route_kind or "discovery"
    if resp.route_kind is None:
        updates["route_kind"] = "discovery"

    if route_kind == "gated":
        # Gated requires exactly one target + a valid decision_class.
        # Degrade to discovery if class is missing/invalid — we can't
        # safely dispatch a gated-proposal without knowing the class.
        if (
            resp.decision_class is None
            or resp.decision_class not in VALID_DECISION_CLASSES
        ):
            updates["route_kind"] = "discovery"
            updates["decision_class"] = None
            updates["reasoning"] = (
                (resp.reasoning or "")
                + " [degraded: gated route missing valid decision_class]"
            )[:240]
        elif len(resp.route_targets) != 1:
            # Keep only the first target — gated is single-target by
            # contract (the gate-keeper named in gate_keeper_map).
            updates["route_targets"] = resp.route_targets[:1]
    else:
        # discovery — class MUST be null (class only meaningful for gated).
        if resp.decision_class is not None:
            updates["decision_class"] = None

    return resp.model_copy(update=updates) if updates else resp


def _apply_profile_weighting(
    options: list[RoutedOption],
    profile: dict[str, Any],
) -> list[RoutedOption]:
    """Nudge weights using the target's response profile.

    Signal used:
      * `counter_rate` (0..1) — share of past routed signals the target
        countered. If >= 0.6 we nudge `counter` options up by +0.1
        (clamped to 1.0).
      * `accept_rate` (0..1) — if >= 0.6 we nudge `accept` options up
        by +0.1.
      * `preferred_kinds` (list[str]) — explicit preferred OptionKinds
        (e.g. ["escalate"]); each listed kind is nudged +0.05.

    The nudge is intentionally small (≤0.1) — the LLM already saw the
    profile in its system prompt, so this is a stable tie-breaker on
    top of the model's own judgement. An empty profile leaves weights
    untouched, which matches the "new target, no history" case.
    """
    if not profile:
        return options

    counter_rate = _as_float(profile.get("counter_rate"))
    accept_rate = _as_float(profile.get("accept_rate"))
    preferred = profile.get("preferred_kinds") or []
    if not isinstance(preferred, list):
        preferred = []
    preferred_set = {p for p in preferred if isinstance(p, str)}

    nudged: list[RoutedOption] = []
    for opt in options:
        delta = 0.0
        if counter_rate is not None and counter_rate >= 0.6 and opt.kind == "counter":
            delta += 0.1
        if accept_rate is not None and accept_rate >= 0.6 and opt.kind == "accept":
            delta += 0.1
        if opt.kind in preferred_set:
            delta += 0.05
        if delta == 0.0:
            nudged.append(opt)
            continue
        new_weight = max(0.0, min(1.0, opt.weight + delta))
        nudged.append(opt.model_copy(update={"weight": new_weight}))
    return nudged


def _as_float(v: Any) -> float | None:
    if isinstance(v, bool):  # bool is a subclass of int — guard first.
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


__all__ = [
    "PROMPT_VERSION",
    "OPTIONS_PROMPT_VERSION",
    "REPLY_FRAME_PROMPT_VERSION",
    "ALLOWED_SKILLS",
    "VALID_DECISION_CLASSES",
    "EdgeAgent",
    "EdgeResponse",
    "EdgeResponseOutcome",
    "RouteTarget",
    "ToolCall",
    "RoutedOption",
    "RoutedOptionsBatch",
    "RoutedOptionsOutcome",
    "FramedReply",
    "FramedReplyOutcome",
    "EdgeKind",
    "OptionKind",
    "ActionHint",
    "SkillName",
    "RouteKind",
    "DecisionClass",
]
