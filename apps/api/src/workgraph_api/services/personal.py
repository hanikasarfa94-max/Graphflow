"""PersonalStreamService — Phase N glue (user-post → EdgeAgent → reply).

North-star §"The canonical interaction":
    1. user types in their personal project stream
    2. their sub-agent (EdgeAgent) metabolizes → silence / answer / clarify
       / route_proposal
    3. if route_proposal, the source clicks "Ask X" → the target's sub-agent
       generates rich options → RoutingService dispatches + mirrors to DM
    4. when the target replies, the source's sub-agent re-frames the reply
       back into the source's personal stream

This service is the orchestrator. It does NOT own any persistence beyond
what's already in StreamService / RoutingService; route-proposal state is
encoded inline in the MessageRow body using a `<route-proposal>{...}</route-proposal>`
marker. That keeps the ORM untouched while still letting the frontend
read target_user_ids back when rendering "Ask X" buttons.

The EdgeAgent dependency is passed in — tests substitute a stub that
never calls an LLM. Prod wires a DeepSeek-backed instance.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import EdgeAgent
from workgraph_agents import (
    VALID_DECISION_CLASSES as EDGE_VALID_DECISION_CLASSES,
)
from workgraph_agents.citations import (
    CitedClaim,
    claims_payload,
    is_uncited,
    wrap_uncited,
)
from workgraph_domain import EventBus
from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    MessageRepository,
    ProjectMemberRepository,
    ProjectRow,
    UserRepository,
    session_scope,
)
from sqlalchemy import select

from .routing import RoutingService
from .skills import SkillsService
from .streams import StreamService

_log = logging.getLogger("workgraph.api.personal")

# Phase Q — cap how many tool calls one user turn may trigger. The
# agent loop is: user post → respond → tool_call → execute → respond →
# (maybe another tool_call) → execute → respond. Two tool calls is
# enough to answer compound questions ("what's our thinking on boss 1
# given recent decisions?") without runaway token use.
MAX_TOOL_CALLS_PER_TURN = 2


# "Why" pre-seed — when a user question starts with a why-word we
# invoke why_chain DETERMINISTICALLY before letting EdgeAgent decide.
# Rationale: the skill + card render is the product moment; DeepSeek
# occasionally chose `answer` / `clarify` kind instead of `tool_call`
# when it already had enough context in-prompt (direct answer), which
# is efficient but skips the lineage-card UX the user is paying for.
# The pre-seed makes the card render every time without second-guessing
# the LLM. The agent loop then synthesizes the final answer over the
# pre-seeded tool result.
_WHY_PREFIX_RE = re.compile(
    r"^\s*(?:why\b|why'd\b|whys\b|为什么|为何|为啥)",
    re.IGNORECASE,
)


def _is_why_question(body: str) -> bool:
    return bool(_WHY_PREFIX_RE.match(body or ""))

_ROUTE_PROPOSAL_MARKER_RE = re.compile(
    r"\n*<route-proposal>(?P<json>.*?)</route-proposal>\s*$",
    re.DOTALL,
)

# Phase 1.B — claims marker for edge-answer / edge-clarify / edge-reply-frame
# / edge-route-proposal message bodies. Same round-trip pattern as the route
# proposal marker so the ORM stays untouched. List-messages strips the
# marker and surfaces `claims` on the PersonalMessage payload.
_CLAIMS_MARKER_RE = re.compile(
    r"\n*<claims>(?P<json>.*?)</claims>\s*$",
    re.DOTALL,
)

# Pre-commit rehearsal (vision.md §5.3). Preview runs on every keystroke
# debounce — cap the blast radius to 1 LLM call per (user, project) per
# this many seconds. Short drafts short-circuit before touching the LLM.
PREVIEW_RATE_LIMIT_SECONDS = 2.0
PREVIEW_MIN_BODY_LENGTH = 10


def _encode_route_proposal_body(body: str, payload: dict[str, Any]) -> str:
    """Append the route-proposal JSON marker to a human-readable body.

    Round-trippable: `_parse_route_proposal` picks out the same JSON.
    """
    return f"{body}\n\n<route-proposal>{json.dumps(payload, ensure_ascii=False)}</route-proposal>"


def _encode_claims_body(body: str, claims: list[dict[str, Any]]) -> str:
    """Append the claims marker to a human-readable body.

    No-op when `claims` is empty so legacy replies (and tests that inspect
    raw body strings) stay untouched.
    """
    if not claims:
        return body
    return f"{body}\n\n<claims>{json.dumps(claims, ensure_ascii=False)}</claims>"


def _parse_claims(body: str) -> tuple[str, list[dict[str, Any]]]:
    """Split body into (human text, claims list). Returns (body, []) when
    the marker is absent or malformed.
    """
    match = _CLAIMS_MARKER_RE.search(body)
    if not match:
        return body, []
    raw = match.group("json")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return body, []
    if not isinstance(payload, list):
        return body, []
    # Shallow sanity filter so a corrupt marker doesn't blow up the UI.
    cleaned: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        citations = item.get("citations") or []
        if not isinstance(citations, list):
            citations = []
        cleaned.append({"text": text, "citations": citations})
    human = body[: match.start()].rstrip()
    return human, cleaned


def _parse_route_proposal(body: str) -> tuple[str, dict[str, Any] | None]:
    """Split a route-proposal message body into (human text, parsed payload).

    Returns (original_body, None) if the marker is absent or malformed.
    """
    match = _ROUTE_PROPOSAL_MARKER_RE.search(body)
    if not match:
        return body, None
    raw = match.group("json")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return body, None
    if not isinstance(payload, dict):
        return body, None
    human = body[: match.start()].rstrip()
    return human, payload


class PersonalStreamService:
    """Orchestrates user posts in their personal project stream.

    Methods:
      * `post`            — user → EdgeAgent.respond → persist
      * `confirm_route`   — source clicks "Ask X" → generate options +
                            dispatch via RoutingService
      * `handle_reply`    — after a routed reply, frame it + post into
                            the source's personal stream
    """

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        stream_service: StreamService,
        routing_service: RoutingService,
        edge_agent: EdgeAgent,
        event_bus: EventBus,
        skills_service: SkillsService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._stream_service = stream_service
        self._routing_service = routing_service
        self._edge_agent = edge_agent
        self._event_bus = event_bus
        # Skills service is optional for back-compat with existing tests
        # that construct PersonalStreamService without a skills dispatcher.
        # If None, tool_call responses degrade to the preamble body so the
        # stream still gets a sensible answer instead of a dead card.
        self._skills_service = skills_service or SkillsService(sessionmaker)
        # Per (user_id, project_id) -> last-preview monotonic timestamp.
        # In-memory is fine for v1: worst case on process restart one
        # keystroke-triggered preview slips through. Keyed by tuple so a
        # user rehearsing in parallel across two projects doesn't throttle
        # either.
        self._preview_last_seen: dict[tuple[str, str], float] = {}
        # Late-bound MembraneService — set via attach_membrane() once
        # both services are constructed (membrane needs StreamService
        # and is built after PersonalStreamService). When None, the
        # clarification-reply intercept degrades to a no-op and the
        # post follows the standard EdgeAgent path.
        self._membrane_service: Any = None

    def attach_membrane(self, membrane_service: Any) -> None:
        self._membrane_service = membrane_service

    # --------------------------------------------------------------- preview

    async def preview(
        self, *, user_id: str, project_id: str, body: str
    ) -> dict[str, Any]:
        """Pre-commit rehearsal (vision.md §5.3).

        Build the same EdgeAgent context `post()` would, call `respond`,
        and return the shaped EdgeResponse — but persist nothing. The
        frontend debounces this call on keystroke pause so the user sees
        how their draft would be classified before committing.

        Error codes:
          * 'project_not_found'
          * 'not_a_project_member'
          * 'rate_limited' — with `retry_after_ms`; the caller maps to 429
          * 'preview_failed' — underlying LLM/exception; surfaced as 502
        """
        # Short-circuit on trivial drafts before we touch anything. This
        # is the main token-budget guard: keystroke-debounce will fire for
        # every pause, and 8-char drafts aren't worth an LLM round-trip.
        if len(body) < PREVIEW_MIN_BODY_LENGTH:
            return {"ok": True, "preview": {"kind": "silent_preview"}}

        # Membership + project sanity check — preview is still a read on
        # the project's graph, so non-members don't get to peek.
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return {"ok": False, "error": "project_not_found"}

            pm_repo = ProjectMemberRepository(session)
            if not await pm_repo.is_member(project_id, user_id):
                return {"ok": False, "error": "not_a_project_member"}

            user_row = await UserRepository(session).get(user_id)
            project_title = project.title

        # Per-(user, project) rate limit. Checked AFTER membership so a
        # non-member probing isn't silently rate-limited into looking ok.
        now = time.monotonic()
        key = (user_id, project_id)
        last = self._preview_last_seen.get(key)
        if last is not None and (now - last) < PREVIEW_RATE_LIMIT_SECONDS:
            retry_after_ms = int(
                (PREVIEW_RATE_LIMIT_SECONDS - (now - last)) * 1000
            )
            return {
                "ok": False,
                "error": "rate_limited",
                "retry_after_ms": max(retry_after_ms, 0),
            }
        self._preview_last_seen[key] = now

        # Personal stream must exist so _build_respond_context has recent
        # messages to include (matches post()'s behaviour).
        stream_payload = await self._stream_service.ensure_personal_stream(
            user_id=user_id, project_id=project_id
        )
        stream_id = stream_payload["stream_id"]

        context = await self._build_respond_context(
            user_id=user_id,
            user_row=user_row,
            project_id=project_id,
            project_title=project_title,
            stream_id=stream_id,
        )

        try:
            outcome = await self._edge_agent.respond(
                user_message=body, context=context
            )
        except Exception:
            _log.exception(
                "edge.respond raised during preview — returning preview_failed",
                extra={"user_id": user_id, "project_id": project_id},
            )
            return {"ok": False, "error": "preview_failed"}

        response = outcome.response
        targets = [
            {
                "user_id": t.user_id,
                "username": t.username,
                "display_name": t.display_name,
                "rationale": t.rationale,
                "b_facing_draft": t.b_facing_draft,
            }
            for t in response.route_targets
        ]
        claims = list(response.claims) or wrap_uncited(response.body)
        return {
            "ok": True,
            "preview": {
                "kind": response.kind,
                "body": response.body,
                "reasoning": response.reasoning,
                "targets": targets,
                "claims": claims_payload(claims),
                "uncited": is_uncited(claims),
            },
        }

    # ------------------------------------------------------------------ post

    async def post(
        self,
        *,
        user_id: str,
        project_id: str,
        body: str,
        scope: dict[str, bool] | None = None,
        scope_tiers: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """User posts into their personal project stream. Edge sub-agent
        metabolizes and may post a follow-up system message.

        `scope_tiers` (N.2) carries the four-tier ScopeTierPills selection
        from the client (personal / group / department / enterprise, where
        group = Cell). Today it is accepted-and-logged plumbing; consumer
        wiring (LicenseContextService.allowed_scopes intersect) lands in
        N.4 — see PLAN-Next.md §"Top bar".

        Error codes:
          * 'project_not_found'
          * 'not_a_project_member'
          * 'stream_post_failed' — shouldn't happen once the personal stream
            exists but we pass through the StreamService error.
        """
        if scope_tiers is not None:
            _log.debug(
                "personal.post scope_tiers=%s user=%s project=%s",
                scope_tiers,
                user_id,
                project_id,
            )
        # Membership + project sanity check first so we don't spin up a
        # personal stream for a project the user cannot see.
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                return {"ok": False, "error": "project_not_found"}

            pm_repo = ProjectMemberRepository(session)
            if not await pm_repo.is_member(project_id, user_id):
                return {"ok": False, "error": "not_a_project_member"}

            user_row = await UserRepository(session).get(user_id)
            project_title = project.title

        # Ensure the personal stream + post the user's turn.
        stream_payload = await self._stream_service.ensure_personal_stream(
            user_id=user_id, project_id=project_id
        )
        stream_id = stream_payload["stream_id"]

        post_result = await self._stream_service.post_message(
            stream_id=stream_id, author_id=user_id, body=body
        )
        if not post_result.get("ok"):
            return {"ok": False, "error": post_result.get("error", "stream_post_failed")}
        message_id = post_result["id"]

        # Stage 5 — clarification reply intercept. If this post is the
        # answer to a recent membrane-clarify question, route it back
        # through review() and skip the normal EdgeAgent loop. The
        # intercept already posts an ack message in the stream so the
        # user sees what happened.
        if self._membrane_service is not None:
            try:
                intercepted = (
                    await self._membrane_service.handle_clarification_reply(
                        stream_id=stream_id,
                        project_id=project_id,
                        proposer_user_id=user_id,
                        reply_body=body,
                    )
                )
            except Exception:
                _log.exception(
                    "personal.post: clarification-reply handler raised — "
                    "falling through to EdgeAgent",
                    extra={"stream_id": stream_id, "user_id": user_id},
                )
                intercepted = False
            if intercepted:
                return {"ok": True, "message_id": message_id, "intercepted": True}

        # Build the EdgeAgent context.
        context = await self._build_respond_context(
            user_id=user_id,
            user_row=user_row,
            project_id=project_id,
            project_title=project_title,
            stream_id=stream_id,
            scope=scope,
        )

        # Agent loop — the EdgeAgent may request up to
        # MAX_TOOL_CALLS_PER_TURN skill executions before settling on a
        # terminal kind (answer / clarify / route_proposal / silence).
        # Each tool call produces two additional system messages that
        # flow through the normal stream so the frontend can render
        # them in-line.
        tool_messages: list[dict[str, Any]] = []
        effective_user_message = body
        tool_call_count = 0

        # "Why" pre-seed — deterministic why_chain fire. Persists a
        # tool_call + tool_result pair identical to what the loop below
        # would produce, then injects the result into context so the
        # next EdgeAgent.respond() produces a terminal kind (answer)
        # with the lineage already in hand. tool_call_count is bumped
        # to 1 so the cap accounting stays honest — the LLM still gets
        # one more tool call if it wants to chain.
        if _is_why_question(body):
            preamble_body = "Walking the decision lineage…"
            call_args = {"query": body, "limit": 3}
            call_payload = {
                "name": "why_chain",
                "args": call_args,
                "preamble": preamble_body,
                "reasoning": "auto-fire on 'why' prefix",
            }
            call_msg = await self._stream_service.post_system_message(
                stream_id=stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=json.dumps(call_payload, ensure_ascii=False),
                kind="edge-tool-call",
                linked_id=message_id,
            )
            skill_result = await self._skills_service.execute(
                project_id=project_id,
                skill_name="why_chain",
                args=call_args,
                caller_user_id=user_id,
            )
            result_msg = await self._stream_service.post_system_message(
                stream_id=stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=json.dumps(skill_result, ensure_ascii=False, default=str),
                kind="edge-tool-result",
                linked_id=call_msg.get("id"),
            )
            tool_messages.append(
                {
                    "kind": "edge-tool-call",
                    "message_id": call_msg.get("id"),
                    "name": "why_chain",
                    "args": call_args,
                    "preamble": preamble_body,
                }
            )
            tool_messages.append(
                {
                    "kind": "edge-tool-result",
                    "message_id": result_msg.get("id"),
                    "name": "why_chain",
                    "result": skill_result,
                }
            )
            tool_call_count += 1
            tool_turn_entry = {
                "author_id": EDGE_AGENT_SYSTEM_USER_ID,
                "kind": "edge-tool-result",
                "body": json.dumps(
                    {"name": "why_chain", "result": skill_result},
                    ensure_ascii=False,
                    default=str,
                ),
                "created_at": None,
            }
            recent = list(context.get("recent_messages") or [])
            recent.append(tool_turn_entry)
            context = {**context, "recent_messages": recent}

        while True:
            try:
                outcome = await self._edge_agent.respond(
                    user_message=effective_user_message, context=context
                )
            except Exception:
                _log.exception(
                    "edge.respond raised — degrading to silence",
                    extra={
                        "user_id": user_id,
                        "project_id": project_id,
                        "tool_call_count": tool_call_count,
                    },
                )
                return {
                    "ok": True,
                    "message_id": message_id,
                    "edge_response": None,
                    "tool_messages": tool_messages,
                }

            response = outcome.response
            kind = response.kind

            if kind != "tool_call":
                break

            if tool_call_count >= MAX_TOOL_CALLS_PER_TURN:
                # Agent wants another tool call after the cap — turn it
                # into a clarify so the user isn't stuck in a silent
                # loop. This is the runaway-guard invariant.
                _log.info(
                    "edge: tool_call cap hit; degrading to clarify",
                    extra={
                        "user_id": user_id,
                        "project_id": project_id,
                        "cap": MAX_TOOL_CALLS_PER_TURN,
                    },
                )
                reply_msg = await self._stream_service.post_system_message(
                    stream_id=stream_id,
                    author_id=EDGE_AGENT_SYSTEM_USER_ID,
                    body=(
                        response.body
                        or "I've run a couple of lookups — can you sharpen the question a bit?"
                    ),
                    kind="edge-clarify",
                    linked_id=None,
                )
                return {
                    "ok": True,
                    "message_id": message_id,
                    "edge_response": {
                        "kind": "clarify",
                        "body": response.body,
                        "reply_message_id": reply_msg.get("id"),
                        "degraded": "tool_call_cap_exceeded",
                    },
                    "tool_messages": tool_messages,
                }

            tc = response.tool_call
            assert tc is not None  # coercer guarantees this for kind="tool_call"

            preamble = response.body or "Running skill…"
            call_payload = {
                "name": tc.name,
                "args": dict(tc.args or {}),
                "preamble": preamble,
                "reasoning": response.reasoning,
            }
            call_msg = await self._stream_service.post_system_message(
                stream_id=stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=json.dumps(call_payload, ensure_ascii=False),
                kind="edge-tool-call",
                linked_id=message_id,
            )
            tool_messages.append(
                {
                    "kind": "edge-tool-call",
                    "message_id": call_msg.get("id"),
                    "name": tc.name,
                    "args": call_payload["args"],
                    "preamble": preamble,
                }
            )

            # Execute the skill — scoped to this project. Most skills
            # are read-only; propose_wiki_entry is the lone write
            # (status='draft', not graph mutation). caller_user_id
            # flows in so write skills know whose row to attribute.
            skill_result = await self._skills_service.execute(
                project_id=project_id,
                skill_name=tc.name,
                args=dict(tc.args or {}),
                caller_user_id=user_id,
            )
            result_msg = await self._stream_service.post_system_message(
                stream_id=stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=json.dumps(skill_result, ensure_ascii=False, default=str),
                kind="edge-tool-result",
                linked_id=call_msg.get("id"),
            )
            tool_messages.append(
                {
                    "kind": "edge-tool-result",
                    "message_id": result_msg.get("id"),
                    "name": tc.name,
                    "result": skill_result,
                }
            )

            tool_call_count += 1

            # Re-invoke the agent with the tool result appended to
            # `recent_messages` so the next respond() sees what we got.
            # Mirrors how Claude Code threads tool output back into the
            # following completion.
            tool_turn_entry = {
                "author_id": EDGE_AGENT_SYSTEM_USER_ID,
                "kind": "edge-tool-result",
                "body": json.dumps(
                    {"name": tc.name, "result": skill_result},
                    ensure_ascii=False,
                    default=str,
                ),
                "created_at": None,
            }
            recent = list(context.get("recent_messages") or [])
            recent.append(tool_turn_entry)
            context = {**context, "recent_messages": recent}
            # After the first tool call the user message is the tool
            # result for the agent's purposes — keep the original body
            # though, so the prompt still knows what the user asked.
            # effective_user_message stays as `body`.

        # ---- terminal kinds ----------------------------------------------

        # 'silence' — no follow-up turn. First-class so acknowledgements
        # don't flood the stream with empty edge turns.
        if kind == "silence":
            return {
                "ok": True,
                "message_id": message_id,
                "edge_response": {
                    "kind": "silence",
                    "body": None,
                },
                "tool_messages": tool_messages,
            }

        # answer / clarify — simple system message, no extra state.
        if kind in ("answer", "clarify"):
            reply_kind = "edge-answer" if kind == "answer" else "edge-clarify"
            reply_body = response.body or ""
            # Phase 1.B — wrap uncited when the model skipped `claims`.
            claims = list(response.claims) or wrap_uncited(reply_body)
            claims_json = claims_payload(claims)
            uncited_flag = is_uncited(claims)
            persisted_body = _encode_claims_body(reply_body, claims_json)
            reply_msg = await self._stream_service.post_system_message(
                stream_id=stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=persisted_body,
                kind=reply_kind,
                linked_id=None,
            )
            return {
                "ok": True,
                "message_id": message_id,
                "edge_response": {
                    "kind": kind,
                    "body": reply_body,
                    "reply_message_id": reply_msg.get("id"),
                    "claims": claims_json,
                    "uncited": uncited_flag,
                },
                "tool_messages": tool_messages,
            }

        # route_proposal — encode targets inline in body so the frontend
        # can render "Ask X" / "Send for sign-off" buttons without a new
        # ORM table. `route_kind` + `decision_class` (Phase v4, Scene 2)
        # go into the marker so the frontend picks the right variant
        # and the right click-target endpoint:
        #   route_kind='discovery'  → POST /api/routing/confirm
        #   route_kind='gated'      → POST /api/projects/{id}/gated-proposals
        if kind == "route_proposal":
            # Backfill empty b_facing_draft via a small second LLM
            # call. The respond prompt asks for the field but DeepSeek
            # is inconsistent about emitting it, so we paper over the
            # gap server-side. Parallel via asyncio.gather so a 3-way
            # discovery route doesn't pay 3× latency.
            framing_for_rewrite = (response.body or body or "").strip()
            empty_targets = [
                t for t in response.route_targets if not (t.b_facing_draft or "").strip()
            ]
            # Tests / stub agents may not implement rewrite_for_target;
            # in that case we just skip the backfill and let the frontend
            # fall through to its A-voice seed. Production EdgeAgent
            # always has it.
            rewrite_fn = getattr(self._edge_agent, "rewrite_for_target", None)
            if empty_targets and framing_for_rewrite and rewrite_fn is not None:
                rewrites = await asyncio.gather(
                    *(
                        rewrite_fn(
                            framing=framing_for_rewrite,
                            target_display_name=t.display_name,
                        )
                        for t in empty_targets
                    ),
                    return_exceptions=True,
                )
                for t, rewrite in zip(empty_targets, rewrites):
                    if isinstance(rewrite, str) and rewrite.strip():
                        # Mutate in place — RouteTarget is a pydantic model
                        # so attribute assignment is allowed and the
                        # subsequent serialization picks it up.
                        object.__setattr__(t, "b_facing_draft", rewrite.strip())
            targets_payload = [
                {
                    "user_id": t.user_id,
                    "username": t.username,
                    "display_name": t.display_name,
                    "rationale": t.rationale,
                    "b_facing_draft": t.b_facing_draft,
                }
                for t in response.route_targets
            ]
            human_body = response.body or ""
            # Phase 1.B — wrap uncited claims and append marker alongside
            # the route-proposal marker. Order matters: claims marker goes
            # FIRST, route-proposal marker LAST, so the route-proposal
            # parser (which anchors to end of string) keeps working.
            claims = list(response.claims) or wrap_uncited(human_body)
            claims_json = claims_payload(claims)
            uncited_flag = is_uncited(claims)
            route_kind_value = response.route_kind or "discovery"
            decision_class_value = (
                response.decision_class
                if route_kind_value == "gated"
                else None
            )
            # v0.5 — carry the user's raw utterance alongside the
            # agent's framing so the gate-keeper card can surface both.
            # Only meaningful for gated routes; discovery routes don't
            # need it (no sign-off step in between).
            decision_text_value = (
                (body or "").strip()
                if route_kind_value == "gated"
                else None
            ) or None
            # Phase S — the [🗳 Open to vote] button affordance on the
            # proposer's card. True when ≥2 authority holders exist
            # for this class on this project (owners ∪ gate_keeper).
            # Computed at context-build time from
            # project.authority_pool_sizes. Conservative mode: LLM
            # doesn't infer authority from profile; pool is declared
            # via roles + gate_keeper_map.
            project_pool_sizes = (
                (context.get("project") or {}).get("authority_pool_sizes")
                or {}
            )
            can_open_to_vote = (
                route_kind_value == "gated"
                and isinstance(decision_class_value, str)
                and int(project_pool_sizes.get(decision_class_value, 0)) >= 2
            )
            marker = {
                "message_id": message_id,  # self-pointer back to the user turn
                "source_user_id": user_id,
                "project_id": project_id,
                "framing": human_body,
                "background": context.get("background", []),
                "targets": targets_payload,
                "status": "pending",
                "route_kind": route_kind_value,
                "decision_class": decision_class_value,
                "decision_text": decision_text_value,
                "can_open_to_vote": can_open_to_vote,
            }
            body_with_claims = _encode_claims_body(human_body, claims_json)
            encoded = _encode_route_proposal_body(body_with_claims, marker)
            reply_msg = await self._stream_service.post_system_message(
                stream_id=stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=encoded,
                kind="edge-route-proposal",
                linked_id=message_id,
            )
            proposal_id = reply_msg.get("id")
            return {
                "ok": True,
                "message_id": message_id,
                "edge_response": {
                    "kind": "route_proposal",
                    "body": human_body,
                    "route_proposal_id": proposal_id,
                    "targets": targets_payload,
                    "route_kind": route_kind_value,
                    "decision_class": decision_class_value,
                    "claims": claims_json,
                    "uncited": uncited_flag,
                },
                "tool_messages": tool_messages,
            }

        # Defensive default (shouldn't hit — EdgeKind is a Literal).
        return {
            "ok": True,
            "message_id": message_id,
            "edge_response": None,
            "tool_messages": tool_messages,
        }

    # -------------------------------------------------------- confirm_route

    async def confirm_route(
        self,
        *,
        proposal_id: str,
        source_user_id: str,
        target_user_id: str,
        refined_framing: str | None = None,
    ) -> dict[str, Any]:
        """Source clicks "Ask X" on a route-proposal card. Generate options
        from the target's sub-agent, dispatch, and post a follow-up
        "✓ asked X" ambient turn so the source stream shows the routed
        state (since we don't mutate the original proposal row).

        `refined_framing` (optional) replaces the proposal's stored framing
        with a B-facing draft the user edited in the route card. Reframing
        the question in A→B voice fixes the dogfood complaint that B saw
        prose written for A's perspective ("your question…") with
        self-pointing pronouns. Empty / None falls back to proposal.framing.

        Error codes:
          * 'proposal_not_found'
          * 'proposal_not_ours' — caller isn't the proposal's source_user
          * 'target_not_in_proposal'
          * dispatch error codes pass through
        """
        async with session_scope(self._sessionmaker) as session:
            proposal = await self._load_proposal(session, proposal_id)
            if proposal is None:
                return {"ok": False, "error": "proposal_not_found"}

            if proposal["source_user_id"] != source_user_id:
                return {"ok": False, "error": "proposal_not_ours"}

            target_ids = {t.get("user_id") for t in proposal.get("targets", [])}
            if target_user_id not in target_ids:
                return {"ok": False, "error": "target_not_in_proposal"}

            source_user = await UserRepository(session).get(source_user_id)
            target_user = await UserRepository(session).get(target_user_id)
            source_profile = (
                dict(source_user.profile) if source_user and source_user.profile else {}
            )
            target_profile = (
                dict(target_user.profile) if target_user and target_user.profile else {}
            )
            source_display = (
                source_user.display_name or source_user.username
                if source_user
                else source_user_id
            )
            target_display = (
                target_user.display_name or target_user.username
                if target_user
                else target_user_id
            )
            project_id = proposal["project_id"]

        # User's refined draft (B-facing) overrides the proposal's
        # original A-facing framing when present + non-empty.
        effective_framing = (refined_framing or "").strip() or proposal.get(
            "framing", ""
        )

        # Build routing_context for option generation. Keys follow the
        # EdgeAgent.options prompt contract.
        routing_context = {
            "framing": effective_framing,
            "background": proposal.get("background", []),
            "source_user": {
                "id": source_user_id,
                "display_name": source_display,
                "profile": source_profile,
            },
            "target_user": {
                "id": target_user_id,
                "display_name": target_display,
            },
            "project_id": project_id,
            "target_response_profile": target_profile or {},
        }

        try:
            options_outcome = await self._edge_agent.generate_options(
                routing_context=routing_context
            )
        except Exception:
            _log.exception(
                "edge.generate_options raised — aborting route confirm",
                extra={"proposal_id": proposal_id},
            )
            return {"ok": False, "error": "option_generation_failed"}

        options_payload = [opt.model_dump() for opt in options_outcome.options]

        dispatch_result = await self._routing_service.dispatch(
            source_user_id=source_user_id,
            target_user_id=target_user_id,
            framing=effective_framing,
            background=proposal.get("background", []),
            options=options_payload,
            project_id=project_id,
        )
        if not dispatch_result.get("ok"):
            return dispatch_result

        signal = dispatch_result["signal"]

        # Post a "✓ routed to X" ambient follow-up into the source's
        # personal stream so the source's timeline reflects the action
        # without mutating the original proposal row.
        source_stream_id = signal["source_stream_id"]
        follow_up = f"✓ asked {target_display}"
        await self._stream_service.post_system_message(
            stream_id=source_stream_id,
            author_id=EDGE_AGENT_SYSTEM_USER_ID,
            body=follow_up,
            kind="edge-route-confirmed",
            linked_id=signal["id"],
        )

        await self._event_bus.emit(
            "personal.route_confirmed",
            {
                "proposal_id": proposal_id,
                "signal_id": signal["id"],
                "source_user_id": source_user_id,
                "target_user_id": target_user_id,
                "project_id": project_id,
            },
        )
        return {"ok": True, "signal_id": signal["id"], "signal": signal}

    # ---------------------------------------------------------- handle_reply

    async def handle_reply(
        self,
        *,
        signal_id: str,
        replier_user_id: str,
        option_id: str | None = None,
        custom_text: str | None = None,
    ) -> dict[str, Any]:
        """After a routed reply persists, frame it in the source's voice
        and post into the source's personal stream.

        Delegates the actual persistence + DM mirror to RoutingService.reply.
        On top of that, calls edge_agent.frame_reply and posts an
        `edge-reply-frame` system message in the source's personal stream.
        """
        reply_result = await self._routing_service.reply(
            signal_id=signal_id,
            replier_user_id=replier_user_id,
            option_id=option_id,
            custom_text=custom_text,
            # Suppress the routed-reply summary in source's stream; we
            # post the richer `edge-reply-frame` below. Without this,
            # source saw the same reply rendered twice as RoutedReplyCard
            # (frontend deduped, but the dual-write was the real bug).
            skip_source_post=True,
        )
        if not reply_result.get("ok"):
            return reply_result

        signal = reply_result["signal"]
        source_stream_id = signal["source_stream_id"]

        async with session_scope(self._sessionmaker) as session:
            source_user = await UserRepository(session).get(signal["source_user_id"])
            source_profile = (
                dict(source_user.profile) if source_user and source_user.profile else {}
            )
            source_display = (
                source_user.display_name or source_user.username
                if source_user
                else signal["source_user_id"]
            )

        source_user_context = {
            "id": signal["source_user_id"],
            "display_name": source_display,
            "profile": source_profile,
        }

        try:
            framed_outcome = await self._edge_agent.frame_reply(
                signal=signal, source_user_context=source_user_context
            )
        except Exception:
            _log.exception(
                "edge.frame_reply raised — skipping frame card",
                extra={"signal_id": signal_id},
            )
            return {"ok": True, "signal": signal, "framed": None}

        framed = framed_outcome.framed
        # Phase 1.B — wrap uncited when the model skipped claims.
        framed_claims = list(framed.claims) or wrap_uncited(framed.body)
        framed_claims_json = claims_payload(framed_claims)
        framed_uncited = is_uncited(framed_claims)
        persisted_frame_body = _encode_claims_body(framed.body, framed_claims_json)
        frame_msg = await self._stream_service.post_system_message(
            stream_id=source_stream_id,
            author_id=EDGE_AGENT_SYSTEM_USER_ID,
            body=persisted_frame_body,
            kind="edge-reply-frame",
            linked_id=signal["id"],
        )
        return {
            "ok": True,
            "signal": signal,
            "framed": {
                "body": framed.body,
                "action_hint": framed.action_hint,
                "attach_options": framed.attach_options,
                "message_id": frame_msg.get("id"),
                "claims": framed_claims_json,
                "uncited": framed_uncited,
            },
        }

    # --------------------------------------------------------- list_messages

    async def list_messages(
        self, *, user_id: str, project_id: str, limit: int = 100
    ) -> dict[str, Any]:
        """Return the caller's personal-stream messages with route-proposal
        targets parsed out of the body marker.
        """
        stream_payload = await self._stream_service.ensure_personal_stream(
            user_id=user_id, project_id=project_id
        )
        stream_id = stream_payload["stream_id"]

        async with session_scope(self._sessionmaker) as session:
            rows = await MessageRepository(session).list_for_stream(
                stream_id, limit=limit
            )
            user_repo = UserRepository(session)
            authors: dict[str, str] = {}
            for r in rows:
                if r.author_id not in authors:
                    u = await user_repo.get(r.author_id)
                    if u is not None:
                        authors[r.author_id] = u.username

        messages: list[dict[str, Any]] = []
        for r in rows:
            body = r.body
            metadata: dict[str, Any] = {}
            if r.kind == "edge-route-proposal":
                human, payload = _parse_route_proposal(body)
                if payload is not None:
                    body = human
                    metadata = {
                        "route_proposal": {
                            "framing": payload.get("framing", ""),
                            "targets": payload.get("targets", []),
                            "background": payload.get("background", []),
                            "status": payload.get("status", "pending"),
                        }
                    }
            # Phase 1.B — strip the claims marker (if any) and surface the
            # parsed claims on the payload. Applies to every edge-* kind
            # that carries prose (answer / clarify / route-proposal /
            # reply-frame); other kinds pass through untouched.
            if r.kind in (
                "edge-answer",
                "edge-clarify",
                "edge-route-proposal",
                "edge-reply-frame",
            ):
                body_no_claims, claims_list = _parse_claims(body)
                body = body_no_claims
                if claims_list:
                    metadata["claims"] = claims_list
                    metadata["uncited"] = all(
                        not (c.get("citations") or []) for c in claims_list
                    )
            messages.append(
                {
                    "id": r.id,
                    "stream_id": stream_id,
                    "project_id": r.project_id,
                    "author_id": r.author_id,
                    "author_username": authors.get(r.author_id),
                    "body": body,
                    "kind": r.kind,
                    "linked_id": r.linked_id,
                    "created_at": r.created_at.isoformat(),
                    **metadata,
                }
            )
        return {"ok": True, "stream_id": stream_id, "messages": messages}

    # ----------------------------------------------------------- internals

    async def _build_respond_context(
        self,
        *,
        user_id: str,
        user_row: Any,
        project_id: str,
        project_title: str,
        stream_id: str,
        scope: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Shape the EdgeAgent.respond context. See edge.py prompt contract.

        Keys:
          * `user` — id / display name / profile
          * `project` — id + title
          * `recent_messages` — last ~5 messages in this personal stream
          * `teammates` — project members (id + display_name) so the LLM
            can name route targets
          * `background` — placeholder slot the respond step can enrich;
            kept empty in v1 so tests don't depend on downstream KB wiring
        """
        async with session_scope(self._sessionmaker) as session:
            pm_repo = ProjectMemberRepository(session)
            members = await pm_repo.list_for_project(project_id)
            user_repo = UserRepository(session)
            member_summaries: list[dict[str, Any]] = []
            caller_project_role = "member"
            for m in members:
                if m.user_id == EDGE_AGENT_SYSTEM_USER_ID:
                    continue
                u = await user_repo.get(m.user_id)
                if u is None:
                    continue
                profile = dict(u.profile) if u.profile else {}
                abilities = list(profile.get("declared_abilities") or [])
                role_hints = list(profile.get("role_hints") or [])
                # Prefer profile role_hints (which are richer, e.g.
                # "design-lead") over the coarse ProjectMemberRow.role
                # (which defaults to "member"/"admin"). Fall back to
                # project role when profile is empty.
                role = role_hints[0] if role_hints else m.role
                if m.user_id == user_id:
                    caller_project_role = role
                    continue
                member_summaries.append(
                    {
                        "user_id": u.id,
                        "username": u.username,
                        "display_name": u.display_name,
                        "role": role,
                        "abilities": abilities,
                    }
                )

            # Phase v4 — Scene 2 routing context. Pull the project's
            # gate_keeper_map so the prompt knows which decision classes
            # are gated and by whom. Filter out stale entries where the
            # gate-keeper is no longer a project member; filter out a
            # self-gate (caller == gate-keeper) so the prompt doesn't try
            # to emit a gated route to the reader. Empty map falls through
            # — no gated routing can fire without a class mapping.
            project_row = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            raw_map = (
                dict(project_row.gate_keeper_map)
                if project_row and project_row.gate_keeper_map
                else {}
            )
            current_member_ids = {
                m.user_id
                for m in members
                if m.user_id != EDGE_AGENT_SYSTEM_USER_ID
            }
            gate_keeper_map: dict[str, str] = {
                cls: uid
                for cls, uid in raw_map.items()
                if cls in EDGE_VALID_DECISION_CLASSES
                and isinstance(uid, str)
                and uid in current_member_ids
                and uid != user_id
            }

            # Phase S — per-class authority pool size. A gated class is
            # eligible for "open to vote" when the pool of current
            # authority holders is ≥ 2. Pool = project owners ∪
            # {gate_keeper if mapped}; same derivation as
            # GatedProposalService.open_to_vote.
            owner_ids = {
                m.user_id
                for m in members
                if m.role == "owner" and m.user_id != EDGE_AGENT_SYSTEM_USER_ID
            }
            authority_pool_sizes: dict[str, int] = {}
            for cls in EDGE_VALID_DECISION_CLASSES:
                pool = set(owner_ids)
                gk = raw_map.get(cls)
                if (
                    isinstance(gk, str)
                    and gk in current_member_ids
                ):
                    pool.add(gk)
                authority_pool_sizes[cls] = len(pool)

            msg_rows = await MessageRepository(session).list_for_stream(
                stream_id, limit=5
            )
            recent_messages = [
                {
                    "author_id": r.author_id,
                    "kind": r.kind,
                    "body": r.body,
                    "created_at": r.created_at.isoformat(),
                }
                for r in msg_rows
            ]

        user_profile = (
            dict(user_row.profile) if user_row and user_row.profile else {}
        )
        # Apply StreamContextPanel scope. Default = graph + kb on, dms +
        # audit off (matches the panel defaults). When graph is off, the
        # agent still gets the user, recent messages, and the project
        # title — but no member abilities, no gate-keeper map, no
        # authority pool sizes. KB / DMs / audit are accepted but no-op
        # for now (those sources aren't loaded in this builder yet).
        graph_on = scope.get("graph", True) if scope else True
        if graph_on:
            project_block: dict[str, Any] = {
                "id": project_id,
                "title": project_title,
                "member_summaries": member_summaries,
                "gate_keeper_map": gate_keeper_map,
                "valid_decision_classes": sorted(EDGE_VALID_DECISION_CLASSES),
                "authority_pool_sizes": authority_pool_sizes,
            }
            teammates = member_summaries
        else:
            project_block = {
                "id": project_id,
                "title": project_title,
                "member_summaries": [],
                "gate_keeper_map": {},
                "valid_decision_classes": sorted(EDGE_VALID_DECISION_CLASSES),
                "authority_pool_sizes": {},
            }
            teammates = []
        return {
            "user": {
                "id": user_id,
                "username": user_row.username if user_row else "",
                "display_name": user_row.display_name if user_row else "",
                "role": (
                    (user_profile.get("role_hints") or [None])[0]
                    or caller_project_role
                ),
                "declared_abilities": list(
                    user_profile.get("declared_abilities") or []
                ),
                "profile": user_profile,
            },
            "project": project_block,
            "teammates": teammates,  # legacy alias; keep until tests migrate
            "recent_messages": recent_messages,
            "background": [],
        }

    async def _load_proposal(
        self, session, proposal_id: str
    ) -> dict[str, Any] | None:
        """Read the proposal back from the stored MessageRow body marker."""
        from workgraph_persistence import MessageRow  # local to avoid cycles

        row = (
            await session.execute(
                select(MessageRow).where(MessageRow.id == proposal_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if row.kind != "edge-route-proposal":
            return None
        _, payload = _parse_route_proposal(row.body)
        if payload is None:
            return None
        # Fill in canonical fields from the row in case the marker is stale.
        payload.setdefault("project_id", row.project_id)
        payload.setdefault("stream_id", row.stream_id)
        return payload


__all__ = ["PersonalStreamService"]
