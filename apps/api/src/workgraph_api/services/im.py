"""IM service — wraps MessageService + IMAssistAgent.

Flow:
  1) user posts a message → MessageService persists + broadcasts
  2) if body is ≥5 words, IMAssistAgent runs asynchronously
  3) suggestion row is written, event emitted, delta broadcast so the UI
     can render a chip inline with the message

Accepting a suggestion is a separate call that mutates the graph or opens
a risk; we never auto-apply (per Phase 7'' AC).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import IMAssistAgent
from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    AgentRunLogRepository,
    ConstraintRow,
    DecisionRepository,
    DecisionRow,
    DeliverableRow,
    IMSuggestionRepository,
    IMSuggestionRow,
    MessageRepository,
    PlanRepository,
    ProjectGraphRepository,
    ProjectMemberRepository,
    ProjectRow,
    RequirementRepository,
    RiskRow,
    StatusTransitionRepository,
    StreamRepository,
    TaskRow,
    UserRepository,
    session_scope,
)

from .collab import MessageService, NotificationService
from .collab_hub import CollabHub

_log = logging.getLogger("workgraph.api.im")

MIN_WORDS_FOR_CLASSIFICATION = 5


def _word_count(body: str) -> int:
    return len([w for w in body.strip().split() if w.strip()])


class IMService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
        notifications: NotificationService,
        messages: MessageService,
        agent: IMAssistAgent,
        kb_item_service: Any | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub
        self._notifications = notifications
        self._messages = messages
        self._agent = agent
        # Optional — only the wiki_entry apply branch needs it. Other
        # apply branches don't touch KB. Tests construct without it.
        self._kb_item_service = kb_item_service
        # Late-bound MembraneService — set via attach_membrane(). The
        # accept handler routes IM-suggestion-derived decisions through
        # the membrane for advisory review (Stage A). When None, the
        # crystallization proceeds without review (existing behavior).
        self._membrane_service: Any = None
        # Keep in-flight classification tasks so tests + shutdown can await.
        self._pending: set[asyncio.Task] = set()

    def attach_membrane(self, membrane_service: Any) -> None:
        self._membrane_service = membrane_service

    async def post_message(
        self,
        *,
        project_id: str,
        author_id: str,
        body: str,
        scope: dict[str, bool] | None = None,
        scope_tiers: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        # `scope_tiers` (N.2) carries the four-tier ScopeTierPills selection
        # from the client (personal / group / department / enterprise, where
        # group = Cell). Today it is accepted-and-logged plumbing; consumer
        # wiring (LicenseContextService.allowed_scopes intersect) lands in
        # N.4 — see PLAN-Next.md §"Top bar".
        if scope_tiers is not None:
            _log.debug(
                "im.post_message scope_tiers=%s author=%s project=%s",
                scope_tiers,
                author_id,
                project_id,
            )
        post_result = await self._messages.post(
            project_id=project_id, author_id=author_id, body=body
        )
        if not post_result.get("ok"):
            return post_result

        message_id = post_result["id"]
        if _word_count(body) < MIN_WORDS_FOR_CLASSIFICATION:
            return post_result

        task = asyncio.create_task(
            self._classify_and_persist(
                project_id=project_id,
                author_id=author_id,
                message_id=message_id,
                body=body,
                scope=scope,
            ),
            name=f"im-classify-{message_id}",
        )
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return post_result

    async def drain(self) -> None:
        if not self._pending:
            return
        await asyncio.gather(*list(self._pending), return_exceptions=True)

    async def _project_snapshot(
        self,
        project_id: str,
        *,
        recent_msgs_limit: int = 5,
        scope: dict[str, bool] | None = None,
    ) -> tuple[dict, dict, list[dict]]:
        # Resolve effective scope flags. Defaults match StreamContextPanel:
        # graph + kb on, dms + audit off. Absent dict → all defaults.
        # Today only `graph` is gateable here (KB/DMs/audit aren't
        # wired into IM context yet); the other flags are accepted as
        # forward-compat scaffolding so a future enrichment doesn't need
        # a fresh request-model migration.
        graph_on = scope.get("graph", True) if scope else True
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                raise ValueError(f"project not found: {project_id}")

            req = await RequirementRepository(session).latest_for_project(project_id)
            deliverables: list[DeliverableRow] = []
            tasks: list[TaskRow] = []
            risks: list[RiskRow] = []
            goal_text = project.title
            # Skip the graph fan-out entirely when the user toggled it off
            # in StreamContextPanel — we still keep title + recent_messages
            # so the agent can reply, just without the structural context.
            if req is not None and graph_on:
                graph_repo = ProjectGraphRepository(session)
                deliverables = await graph_repo.list_deliverables(req.id)
                risks = await graph_repo.list_risks(req.id)
                tasks = await PlanRepository(session).list_tasks(req.id)
                parsed = req.parsed_json or {}
                if isinstance(parsed, dict) and parsed.get("goal"):
                    goal_text = parsed["goal"]

            recent = list(
                await MessageRepository(session).list_recent(
                    project_id, limit=recent_msgs_limit
                )
            )
            user_repo = UserRepository(session)
            recent_authors: dict[str, str] = {}
            for r in recent:
                if r.author_id not in recent_authors:
                    u = await user_repo.get(r.author_id)
                    if u is not None:
                        recent_authors[r.author_id] = u.username

            project_snapshot = {
                "id": project.id,
                "title": project.title,
                "goal": goal_text,
                "deliverables": [
                    {"id": d.id, "title": d.title, "kind": d.kind} for d in deliverables
                ],
                "tasks": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "assignee_role": t.assignee_role,
                    }
                    for t in tasks
                ],
                "risks": [
                    {"id": r.id, "title": r.title, "severity": r.severity}
                    for r in risks
                ],
            }
            author_row = await user_repo.get_by_username("")  # noop for type hint
            # Fetch message author last so we don't hit the in-thread session twice.
            return (
                project_snapshot,
                {},
                [
                    {
                        "author": recent_authors.get(r.author_id, "unknown"),
                        "body": r.body,
                        "ts": r.created_at.isoformat(),
                    }
                    for r in recent
                    # Don't feed the current message back — we already classify it.
                ],
            )

    async def _classify_and_persist(
        self,
        *,
        project_id: str,
        author_id: str,
        message_id: str,
        body: str,
        scope: dict[str, bool] | None = None,
    ) -> None:
        try:
            project_snapshot, _, recent_msgs = await self._project_snapshot(
                project_id, scope=scope
            )
            async with session_scope(self._sessionmaker) as session:
                user = await UserRepository(session).get(author_id)
                author_payload = (
                    {
                        "id": user.id,
                        "username": user.username,
                        "display_name": user.display_name,
                    }
                    if user is not None
                    else {"id": author_id}
                )

            outcome = await self._agent.classify(
                message=body,
                author=author_payload,
                project=project_snapshot,
                recent_messages=recent_msgs,
            )
            suggestion = outcome.suggestion

            async with session_scope(self._sessionmaker) as session:
                row = await IMSuggestionRepository(session).append(
                    project_id=project_id,
                    message_id=message_id,
                    kind=suggestion.kind,
                    confidence=suggestion.confidence,
                    targets=list(suggestion.targets),
                    proposal=suggestion.proposal.model_dump()
                    if suggestion.proposal
                    else None,
                    reasoning=suggestion.reasoning,
                    prompt_version=self._agent.prompt_version,
                    outcome=outcome.outcome,
                    attempts=outcome.attempts,
                )
                await AgentRunLogRepository(session).append(
                    agent="im_assist",
                    prompt_version=self._agent.prompt_version,
                    project_id=project_id,
                    trace_id=get_trace_id(),
                    outcome=outcome.outcome,
                    attempts=outcome.attempts,
                    latency_ms=outcome.result.latency_ms,
                    prompt_tokens=outcome.result.prompt_tokens,
                    completion_tokens=outcome.result.completion_tokens,
                    cache_read_tokens=outcome.result.cache_read_tokens,
                    error=outcome.error,
                )

                payload = self._suggestion_payload(row)

            await self._event_bus.emit("im_suggestion.produced", payload)
            await self._hub.publish(
                project_id, {"type": "suggestion", "payload": payload}
            )
        except Exception:
            _log.exception(
                "im_assist classification failed", extra={"message_id": message_id}
            )

    def _suggestion_payload(self, row: IMSuggestionRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "message_id": row.message_id,
            "kind": row.kind,
            "confidence": row.confidence,
            "targets": row.targets or [],
            "proposal": row.proposal,
            "reasoning": row.reasoning,
            "status": row.status,
            "outcome": row.outcome,
            "attempts": row.attempts,
            "counter_of_id": row.counter_of_id,
            "decision_id": row.decision_id,
            "escalation_state": row.escalation_state,
            "created_at": row.created_at.isoformat(),
            "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
        }

    def _decision_payload(self, row: DecisionRow) -> dict[str, Any]:
        """Mirror DecisionService._decision_payload so WS frames stay identical.

        Local to IMService so the crystallization path doesn't need to reach
        into DecisionService internals, which would create a reverse import.
        """
        return {
            "id": row.id,
            "conflict_id": row.conflict_id,
            "source_suggestion_id": row.source_suggestion_id,
            "project_id": row.project_id,
            "resolver_id": row.resolver_id,
            "option_index": row.option_index,
            "custom_text": row.custom_text,
            "rationale": row.rationale,
            "apply_actions": row.apply_actions or [],
            "apply_outcome": row.apply_outcome,
            "apply_detail": row.apply_detail or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "applied_at": row.applied_at.isoformat() if row.applied_at else None,
        }

    async def get_suggestion(self, suggestion_id: str) -> dict | None:
        async with session_scope(self._sessionmaker) as session:
            row = await IMSuggestionRepository(session).get(suggestion_id)
            if row is None:
                return None
            return self._suggestion_payload(row)

    async def list_for_project(
        self, project_id: str, *, limit: int = 100
    ) -> list[dict]:
        """Suggestions attached to team-room messages only.

        Post-Phase-L: same leak concern as MessageService.list_recent —
        suggestions tied to personal-stream messages must not surface
        in the team-room view. Scope to the project's team-room stream.
        """
        async with session_scope(self._sessionmaker) as session:
            team_stream = await StreamRepository(session).get_for_project(project_id)
            if team_stream is None:
                return []
            messages = await MessageRepository(session).list_for_stream(
                team_stream.id, limit=limit
            )
            suggestions: list[IMSuggestionRow] = []
            for m in messages:
                row = await IMSuggestionRepository(session).get_for_message(m.id)
                if row is not None:
                    suggestions.append(row)
            return [self._suggestion_payload(s) for s in suggestions]

    async def accept(
        self,
        *,
        suggestion_id: str,
        actor_id: str,
    ) -> dict:
        async with session_scope(self._sessionmaker) as session:
            row = await IMSuggestionRepository(session).get(suggestion_id)
            if row is None:
                return {"ok": False, "error": "suggestion_not_found"}
            if row.status != "pending":
                return {"ok": False, "error": "already_resolved"}

            project_id = row.project_id
            kind = row.kind
            confidence = row.confidence

            # Owner-gate on membrane_review accept. The whole point of
            # the membrane review queue is "the proposer can't ship
            # their own staged write without an owner review." Members
            # accepting their own membrane drafts would defeat the
            # purpose. Other suggestion kinds (decision/blocker/tag/
            # wiki_entry) keep the looser "any member can accept"
            # rule — those don't carry the same authority concern.
            if kind == "membrane_review":
                role = await ProjectMemberRepository(session).get_role(
                    project_id, actor_id
                )
                if role != "owner":
                    return {"ok": False, "error": "owner_only"}

            applied = await self._apply_proposal(session, row, actor_id=actor_id)

            # Signal-chain crystallization (vision §6): when a high-confidence
            # decision-kind suggestion is accepted, persist a DecisionRow that
            # links back to the suggestion. "apply_outcome" mirrors whether
            # the associated graph mutation actually landed.
            decision_payload: dict[str, Any] | None = None
            membrane_warnings: list[str] = []
            if kind == "decision" and confidence >= 0.6:
                proposal = row.proposal or {}
                action = (
                    proposal.get("action") if isinstance(proposal, dict) else None
                )
                detail = (
                    proposal.get("detail", {}) if isinstance(proposal, dict) else {}
                )
                # Stage A — membrane review for IM-derived decisions.
                # Always advisory (auto_merge with warnings) in v0; the
                # path completes as before, warnings surface in the
                # response. The review opens its own session for the
                # recent-decisions scan; aiosqlite serializes reads
                # cleanly so nesting under our outer session is safe.
                if self._membrane_service is not None:
                    from .membrane import MembraneCandidate

                    review_title = (
                        proposal.get("summary", "") if isinstance(proposal, dict) else ""
                    )[:200]
                    review = await self._membrane_service.review(
                        MembraneCandidate(
                            kind="decision_crystallize",
                            project_id=project_id,
                            proposer_user_id=actor_id,
                            title=review_title,
                            content="",
                            metadata={
                                "source": "im_apply",
                                "suggestion_id": suggestion_id,
                                "rationale": row.reasoning or "",
                            },
                        )
                    )
                    membrane_warnings = list(review.warnings)
                crystallize_outcome = (
                    "ok" if applied.get("graph_touched") else "advisory"
                )
                # B3 (N-Next §6.11 + Correction R.2): stamp the smallest-relevant
                # vote scope. The source message's stream is the room/team-room
                # where the suggestion was raised; that membership defines the
                # quorum the decision applies to. None when the source message
                # predates stream_id backfill.
                source_msg = await MessageRepository(session).get(row.message_id)
                source_stream_id = source_msg.stream_id if source_msg else None
                decision_row = await DecisionRepository(session).create(
                    conflict_id=None,
                    project_id=project_id,
                    resolver_id=actor_id,
                    option_index=None,
                    custom_text=None,
                    rationale=row.reasoning or "",
                    apply_actions=[{"kind": action, "detail": detail}],
                    source_suggestion_id=suggestion_id,
                    apply_outcome=crystallize_outcome,
                    apply_detail={"applied": applied},
                    scope_stream_id=source_stream_id,
                )
                # applied_at mirrors create_at since crystallization is synchronous.
                decision_row.applied_at = datetime.now(timezone.utc)
                await IMSuggestionRepository(session).set_decision_id(
                    suggestion_id, decision_row.id
                )
                # Refresh the decision row inside the session so applied_at
                # shows up in the payload.
                decision_payload = self._decision_payload(decision_row)

            await IMSuggestionRepository(session).resolve(suggestion_id, "accepted")
            refreshed = await IMSuggestionRepository(session).get(suggestion_id)
            payload = self._suggestion_payload(refreshed) if refreshed else None

        await self._event_bus.emit(
            "im_suggestion.resolved",
            {
                "suggestion_id": suggestion_id,
                "status": "accepted",
                "actor_id": actor_id,
                "applied": applied,
                "project_id": project_id,
            },
        )
        if payload is not None:
            await self._hub.publish(
                project_id,
                {"type": "suggestion", "payload": payload},
            )
        if decision_payload is not None:
            await self._event_bus.emit(
                "decision.crystallized",
                {
                    "decision_id": decision_payload["id"],
                    "source_suggestion_id": suggestion_id,
                    "project_id": project_id,
                    "resolver": actor_id,
                },
            )
            await self._hub.publish(
                project_id, {"type": "decision", "payload": decision_payload}
            )
        if applied.get("graph_touched"):
            await self._hub.publish(
                project_id, {"type": "graph", "payload": {"reason": "im_accept"}}
            )
        return {
            "ok": True,
            "applied": applied,
            "suggestion": payload,
            "decision": decision_payload,
            "warnings": membrane_warnings,
        }

    async def dismiss(self, *, suggestion_id: str, actor_id: str) -> dict:
        async with session_scope(self._sessionmaker) as session:
            row = await IMSuggestionRepository(session).get(suggestion_id)
            if row is None:
                return {"ok": False, "error": "suggestion_not_found"}
            if row.status != "pending":
                return {"ok": False, "error": "already_resolved"}
            project_id = row.project_id
            await IMSuggestionRepository(session).resolve(suggestion_id, "dismissed")
            refreshed = await IMSuggestionRepository(session).get(suggestion_id)
            payload = self._suggestion_payload(refreshed) if refreshed else None
        await self._event_bus.emit(
            "im_suggestion.resolved",
            {
                "suggestion_id": suggestion_id,
                "status": "dismissed",
                "actor_id": actor_id,
                "project_id": project_id,
            },
        )
        if payload is not None:
            await self._hub.publish(
                project_id, {"type": "suggestion", "payload": payload}
            )
        return {"ok": True, "suggestion": payload}

    async def counter(
        self, *, suggestion_id: str, text: str, user_id: str
    ) -> dict:
        """Signal-chain counter (vision §6 step 4).

        Original suggestion flips to `countered`; the counterer's framing is
        persisted as a fresh MessageRow authored by user_id; IMAssist runs on
        the new message (synchronously, unlike post_message which fires-and-
        forgets, so the route response can include the new suggestion); the
        new suggestion's `counter_of_id` points back at the original.
        """
        async with session_scope(self._sessionmaker) as session:
            original = await IMSuggestionRepository(session).get(suggestion_id)
            if original is None:
                return {"ok": False, "error": "suggestion_not_found"}
            if original.status != "pending":
                return {"ok": False, "error": "already_resolved"}
            project_id = original.project_id

            # Flip the original + capture its post-flip payload for the WS
            # fanout and the HTTP response.
            await IMSuggestionRepository(session).mark_countered(suggestion_id)
            refreshed_original = await IMSuggestionRepository(session).get(
                suggestion_id
            )
            original_payload = (
                self._suggestion_payload(refreshed_original)
                if refreshed_original
                else None
            )

        # Post the counter message through the existing MessageService so
        # member notifications + rate-limit + broadcast stay consistent.
        post_result = await self._messages.post(
            project_id=project_id, author_id=user_id, body=text
        )
        if not post_result.get("ok"):
            # Roll back the status flip? The signal chain treats the counter
            # as atomic with the status change — but we chose to flip first
            # so concurrent writers see the countered state quickly. If
            # message post fails (rate-limit), the status flip persists and
            # the caller can retry with a fresh message. Flag it.
            return {"ok": False, "error": post_result.get("error", "message_post_failed")}

        new_message_id = post_result["id"]
        new_suggestion_payload: dict[str, Any] | None = None

        # Classify synchronously (instead of fire-and-forget) so the caller
        # can include the new suggestion in the response body. Word-count
        # gate mirrors post_message.
        if _word_count(text) >= MIN_WORDS_FOR_CLASSIFICATION:
            try:
                project_snapshot, _, recent_msgs = await self._project_snapshot(
                    project_id
                )
                async with session_scope(self._sessionmaker) as session:
                    user = await UserRepository(session).get(user_id)
                    author_payload = (
                        {
                            "id": user.id,
                            "username": user.username,
                            "display_name": user.display_name,
                        }
                        if user is not None
                        else {"id": user_id}
                    )
                outcome = await self._agent.classify(
                    message=text,
                    author=author_payload,
                    project=project_snapshot,
                    recent_messages=recent_msgs,
                )
                suggestion = outcome.suggestion
                async with session_scope(self._sessionmaker) as session:
                    new_row = await IMSuggestionRepository(session).append(
                        project_id=project_id,
                        message_id=new_message_id,
                        kind=suggestion.kind,
                        confidence=suggestion.confidence,
                        targets=list(suggestion.targets),
                        proposal=suggestion.proposal.model_dump()
                        if suggestion.proposal
                        else None,
                        reasoning=suggestion.reasoning,
                        prompt_version=self._agent.prompt_version,
                        outcome=outcome.outcome,
                        attempts=outcome.attempts,
                        counter_of_id=suggestion_id,
                    )
                    await AgentRunLogRepository(session).append(
                        agent="im_assist",
                        prompt_version=self._agent.prompt_version,
                        project_id=project_id,
                        trace_id=get_trace_id(),
                        outcome=outcome.outcome,
                        attempts=outcome.attempts,
                        latency_ms=outcome.result.latency_ms,
                        prompt_tokens=outcome.result.prompt_tokens,
                        completion_tokens=outcome.result.completion_tokens,
                        cache_read_tokens=outcome.result.cache_read_tokens,
                        error=outcome.error,
                    )
                    new_suggestion_payload = self._suggestion_payload(new_row)

                await self._event_bus.emit(
                    "im_suggestion.produced", new_suggestion_payload
                )
            except Exception:
                _log.exception(
                    "counter classification failed",
                    extra={"message_id": new_message_id},
                )

        # Fanout order per plan doc: original-suggestion update, message,
        # then the new suggestion (if any).
        if original_payload is not None:
            await self._hub.publish(
                project_id, {"type": "suggestion", "payload": original_payload}
            )
        # The MessageService already fired `{type:"message"}` during post()
        # so we do NOT re-emit here to avoid duplicate bubbles.
        if new_suggestion_payload is not None:
            await self._hub.publish(
                project_id,
                {"type": "suggestion", "payload": new_suggestion_payload},
            )

        await self._event_bus.emit(
            "im_suggestion.countered",
            {
                "suggestion_id": suggestion_id,
                "actor_id": user_id,
                "project_id": project_id,
                "new_message_id": new_message_id,
                "new_suggestion_id": (
                    new_suggestion_payload["id"]
                    if new_suggestion_payload
                    else None
                ),
            },
        )

        # Shape mirrors the plan doc's counter response.
        new_message_payload = {
            k: post_result[k]
            for k in (
                "id",
                "project_id",
                "author_id",
                "author_username",
                "body",
                "created_at",
            )
            if k in post_result
        }
        return {
            "ok": True,
            "original_suggestion": original_payload,
            "new_message": new_message_payload,
            "new_suggestion": new_suggestion_payload,
        }

    async def escalate(self, *, suggestion_id: str, user_id: str) -> dict:
        """Signal-chain escalate (vision §6 step 4 / §5.6 ladder).

        Flip status→'escalated', set escalation_state='requested'. No meeting
        is scheduled — v0 is just a flag the UI renders as an amber badge.
        """
        async with session_scope(self._sessionmaker) as session:
            row = await IMSuggestionRepository(session).get(suggestion_id)
            if row is None:
                return {"ok": False, "error": "suggestion_not_found"}
            if row.status != "pending":
                return {"ok": False, "error": "already_resolved"}
            project_id = row.project_id
            await IMSuggestionRepository(session).mark_escalated(suggestion_id)
            refreshed = await IMSuggestionRepository(session).get(suggestion_id)
            payload = self._suggestion_payload(refreshed) if refreshed else None

        await self._event_bus.emit(
            "im_suggestion.escalated",
            {
                "suggestion_id": suggestion_id,
                "actor_id": user_id,
                "project_id": project_id,
            },
        )
        if payload is not None:
            await self._hub.publish(
                project_id, {"type": "suggestion", "payload": payload}
            )
        return {"ok": True, "suggestion": payload}

    async def _apply_proposal(
        self, session, row: IMSuggestionRow, *, actor_id: str | None = None
    ) -> dict[str, Any]:
        """Execute the proposal in `row`. Idempotent where possible.

        Returns a dict describing what actually changed. Graph-touching
        actions set `graph_touched=True` so the caller can rebroadcast.

        Sprint 1b: any status mutation is accompanied by a
        StatusTransitionRow so the time-cursor can replay history.
        """
        trace_id = get_trace_id()
        proposal = row.proposal or {}
        action = proposal.get("action") if isinstance(proposal, dict) else None
        detail = proposal.get("detail", {}) if isinstance(proposal, dict) else {}

        if row.kind == "blocker" or action == "open_risk":
            project_id = row.project_id
            req = await RequirementRepository(session).latest_for_project(project_id)
            if req is None:
                return {"ok": False, "error": "no_requirement"}
            existing_count = len(
                await ProjectGraphRepository(session).list_risks(req.id)
            )
            title = detail.get("title") if isinstance(detail, dict) else None
            severity = (
                detail.get("severity", "medium") if isinstance(detail, dict) else "medium"
            )
            risk_title = (title or row.reasoning or "IM-reported blocker")[:480]
            risk_content = proposal.get("summary", "") if isinstance(proposal, dict) else ""
            new_row = RiskRow(
                id=_new_uuid(),
                project_id=project_id,
                requirement_id=req.id,
                sort_order=existing_count,
                title=risk_title,
                content=risk_content,
                severity=severity if severity in {"low", "medium", "high"} else "medium",
                status="open",
            )
            session.add(new_row)
            await session.flush()
            return {
                "ok": True,
                "graph_touched": True,
                "risk_id": new_row.id,
                "action": "open_risk",
            }

        if action == "drop_deliverable":
            deliverable_id = (
                detail.get("deliverable_id") if isinstance(detail, dict) else None
            )
            if not deliverable_id:
                return {"ok": False, "error": "missing_deliverable_id"}
            deliverable = (
                await session.execute(
                    select(DeliverableRow).where(DeliverableRow.id == deliverable_id)
                )
            ).scalar_one_or_none()
            if deliverable is None:
                return {"ok": False, "error": "deliverable_not_found"}
            old_status = deliverable.status
            deliverable.status = "dropped"
            await session.flush()
            # Sprint 1b: record so graph-at can reconstruct the pre-drop
            # state when the user scrubs back past this moment.
            await StatusTransitionRepository(session).record(
                project_id=deliverable.project_id,
                entity_kind="deliverable",
                entity_id=deliverable.id,
                old_status=old_status,
                new_status="dropped",
                changed_by_user_id=actor_id,
                trace_id=trace_id,
            )
            return {
                "ok": True,
                "graph_touched": True,
                "deliverable_id": deliverable.id,
                "action": "drop_deliverable",
            }

        if action == "mark_task_done":
            task_id = detail.get("task_id") if isinstance(detail, dict) else None
            if not task_id:
                return {"ok": False, "error": "missing_task_id"}
            task = (
                await session.execute(select(TaskRow).where(TaskRow.id == task_id))
            ).scalar_one_or_none()
            if task is None:
                return {"ok": False, "error": "task_not_found"}
            old_status = task.status
            task.status = "done"
            await session.flush()
            await StatusTransitionRepository(session).record(
                project_id=task.project_id,
                entity_kind="task",
                entity_id=task.id,
                old_status=old_status,
                new_status="done",
                changed_by_user_id=actor_id,
                trace_id=trace_id,
            )
            return {
                "ok": True,
                "graph_touched": True,
                "task_id": task.id,
                "action": "mark_task_done",
            }

        if action == "update_constraint":
            constraint_id = (
                detail.get("constraint_id") if isinstance(detail, dict) else None
            )
            new_status = (
                detail.get("status", "resolved") if isinstance(detail, dict) else "resolved"
            )
            if not constraint_id:
                return {"ok": False, "error": "missing_constraint_id"}
            constraint = (
                await session.execute(
                    select(ConstraintRow).where(ConstraintRow.id == constraint_id)
                )
            ).scalar_one_or_none()
            if constraint is None:
                return {"ok": False, "error": "constraint_not_found"}
            old_status = constraint.status
            constraint.status = new_status
            await session.flush()
            await StatusTransitionRepository(session).record(
                project_id=constraint.project_id,
                entity_kind="constraint",
                entity_id=constraint.id,
                old_status=old_status,
                new_status=new_status,
                changed_by_user_id=actor_id,
                trace_id=trace_id,
            )
            return {
                "ok": True,
                "graph_touched": True,
                "constraint_id": constraint.id,
                "action": "update_constraint",
            }

        if row.kind == "wiki_entry" or action == "save_to_wiki":
            # Promote nominated content into a group-scope KB entry. The
            # IM-assist prompt puts the title in proposal.summary and the
            # body in proposal.detail.content_md. Fall back to the source
            # message body when detail is missing.
            title_raw = (
                proposal.get("summary") if isinstance(proposal, dict) else ""
            ) or ""
            content_md = ""
            if isinstance(detail, dict):
                content_md = (detail.get("content_md") or "").strip()
            if not content_md and row.message_id:
                src = await MessageRepository(session).get(row.message_id)
                if src is not None:
                    content_md = (src.body or "").strip()
            title = (title_raw or content_md.splitlines()[0] if content_md else "Untitled")[:160].strip() or "Untitled"
            if not content_md:
                return {"ok": False, "error": "empty_wiki_proposal"}
            if self._kb_item_service is None:
                return {"ok": False, "error": "kb_service_unavailable"}
            try:
                item = await self._kb_item_service.create(
                    project_id=row.project_id,
                    owner_user_id=actor_id or row.project_id,
                    title=title,
                    content_md=content_md,
                    scope="group",
                    source="llm",
                    status="published",
                )
            except Exception as e:  # noqa: BLE001 — surface code
                code = getattr(e, "code", None) or "create_failed"
                return {"ok": False, "error": code}
            return {
                "ok": True,
                "graph_touched": True,
                "kb_item_id": item.get("id"),
                "action": "save_to_wiki",
            }

        if (
            row.kind == "membrane_review"
            or action == "approve_membrane_candidate"
        ):
            # Stage 4 of docs/membrane-reorg.md. The membrane staged a
            # candidate + queued this suggestion; the owner just clicked
            # accept. Branch on candidate_kind because the cell-side
            # write differs:
            #   * kb_item_group  → flip the linked draft to published
            #   * task_promote   → promote the personal task to plan
            candidate_kind = (
                detail.get("candidate_kind")
                if isinstance(detail, dict)
                else None
            ) or "kb_item_group"  # legacy: pre-T+1 only kb_item_group
                                  # ever queued, no field was set.

            if candidate_kind == "kb_item_group":
                kb_item_id = (
                    detail.get("kb_item_id")
                    if isinstance(detail, dict)
                    else None
                )
                if not kb_item_id:
                    return {"ok": False, "error": "missing_kb_item_id"}
                from workgraph_persistence import KbItemRepository

                updated = await KbItemRepository(session).update(
                    item_id=kb_item_id, status="published"
                )
                if updated is None:
                    return {"ok": False, "error": "kb_item_not_found"}
                return {
                    "ok": True,
                    "graph_touched": True,
                    "kb_item_id": kb_item_id,
                    "action": "approve_membrane_candidate",
                }

            if candidate_kind == "task_promote":
                task_id = (
                    detail.get("task_id")
                    if isinstance(detail, dict)
                    else None
                )
                if not task_id:
                    return {"ok": False, "error": "missing_task_id"}
                req = await RequirementRepository(session).latest_for_project(
                    row.project_id
                )
                if req is None:
                    return {"ok": False, "error": "no_requirement_to_attach_to"}
                existing = await PlanRepository(session).list_tasks(req.id)
                next_sort = (
                    max((t.sort_order or 0) for t in existing) + 1
                    if existing
                    else 0
                )
                promoted = await PlanRepository(session).promote_personal_to_plan(
                    task_id=task_id,
                    requirement_id=req.id,
                    sort_order=next_sort,
                )
                if promoted is None:
                    return {"ok": False, "error": "promote_failed"}
                return {
                    "ok": True,
                    "graph_touched": True,
                    "task_id": task_id,
                    "action": "approve_membrane_candidate",
                }

            return {"ok": False, "error": f"unknown_candidate_kind:{candidate_kind}"}

        # tag or `none` kinds have nothing to apply.
        return {"ok": True, "graph_touched": False, "action": action or "noop"}


def _new_uuid() -> str:
    # Local import to avoid circular concerns.
    from uuid import uuid4

    return str(uuid4())


__all__ = ["IMService", "MIN_WORDS_FOR_CLASSIFICATION"]
