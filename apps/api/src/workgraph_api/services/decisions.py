"""Phase 9 — Human Decision Loop.

Turns a conflict resolution into a first-class audit record + (best-effort)
graph mutation. Flow:

  1. validate — must have exactly one of (option_index, custom_text), the
     conflict must be open, option must be in range.
  2. plan — map the chosen option/action into a structured `apply_actions`
     list. Only `missing_owner` gets a mechanical path today (assign a task
     to a user); everything else is audit-only (`apply_outcome="advisory"`).
  3. persist — create DecisionRow with outcome="pending", emit
     `decision.submitted`.
  4. apply — run the structured actions. Currently:
        * `assign_task` → AssignmentService.set_assignment
     Failure on one action marks the whole decision `partial`/`failed`.
  5. finalize — mark_applied, mark the conflict resolved with resolver +
     option_index, emit `decision.applied`, publish WS `conflict` frame +
     fresh conflict list, kick a recheck if we changed ownership.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    ConflictRepository,
    DecisionRepository,
    DecisionRow,
    session_scope,
)


from .collab import AssignmentService
from .collab_hub import CollabHub
from .conflicts import ConflictService
from .signal_tally import SignalTallyService

_log = logging.getLogger("workgraph.api.decisions")


class DecisionError(Exception):
    """Raised for validation failures — mapped to 4xx by the router."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class DecisionService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        hub: CollabHub,
        conflict_service: ConflictService,
        assignment_service: AssignmentService,
        signal_tally: SignalTallyService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._hub = hub
        self._conflicts = conflict_service
        self._assignments = assignment_service
        self._signal_tally = signal_tally
        # Late-bound MembraneService — set via attach_membrane() once
        # built (membrane construction happens after DecisionService
        # because the membrane needs StreamService). When None, the
        # decision-crystallize review degrades to a no-op so existing
        # boot orders + tests stay working.
        self._membrane_service: Any = None

    def attach_membrane(self, membrane_service: Any) -> None:
        self._membrane_service = membrane_service

    async def submit(
        self,
        *,
        conflict_id: str,
        actor_id: str,
        option_index: int | None,
        custom_text: str | None,
        rationale: str,
        assignee_user_id: str | None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        # ---- validate --------------------------------------------------
        if option_index is None and not custom_text:
            raise DecisionError("option_or_text_required")
        if option_index is not None and custom_text:
            raise DecisionError("option_and_text_exclusive")

        async with session_scope(self._sessionmaker) as session:
            conflict_repo = ConflictRepository(session)
            conflict = await conflict_repo.get(conflict_id)
            if conflict is None:
                raise DecisionError("conflict_not_found", status=404)
            if conflict.status in ("resolved", "dismissed"):
                raise DecisionError("already_resolved", status=409)
            if option_index is not None:
                opts = conflict.options or []
                if option_index < 0 or option_index >= len(opts):
                    raise DecisionError("option_out_of_range")

            apply_actions = self._plan_actions(
                rule=conflict.rule,
                targets=list(conflict.targets or []),
                assignee_user_id=assignee_user_id,
            )
            project_id = conflict.project_id
            # Title-equivalent for the membrane dup-check: prefer the
            # conflict's chosen-option text when option_index is set,
            # else use custom_text. Conflict resolutions otherwise have
            # no natural "title" since they're identified by conflict_id.
            chosen_option_text = ""
            if option_index is not None and conflict.options:
                opt = conflict.options[option_index]
                chosen_option_text = (
                    (opt.get("title") or opt.get("text") or "")
                    if isinstance(opt, dict)
                    else ""
                )
            review_title = chosen_option_text or (custom_text or "")[:200]

        # Membrane review (Stage A — advisory only). Always returns
        # auto_merge in v0; warnings carry the membrane's observations
        # (dup-decision, missing rationale, etc.) and are surfaced in
        # the response payload so the FE can render them. The review
        # call lives outside the session_scope so the membrane can open
        # its own session for the recent-decisions scan.
        warnings: tuple[str, ...] = ()
        if self._membrane_service is not None:
            from .membrane import MembraneCandidate

            review = await self._membrane_service.review(
                MembraneCandidate(
                    kind="decision_crystallize",
                    project_id=project_id,
                    proposer_user_id=actor_id,
                    title=review_title,
                    content="",
                    metadata={
                        "source": "conflict_resolution",
                        "conflict_id": conflict_id,
                        "rationale": rationale or "",
                    },
                )
            )
            warnings = review.warnings

        async with session_scope(self._sessionmaker) as session:
            decision = await DecisionRepository(session).create(
                conflict_id=conflict_id,
                project_id=project_id,
                resolver_id=actor_id,
                option_index=option_index,
                custom_text=custom_text,
                rationale=rationale or "",
                apply_actions=apply_actions,
                trace_id=trace_id,
            )
            decision_id = decision.id

        await self._event_bus.emit(
            "decision.submitted",
            {
                "decision_id": decision_id,
                "conflict_id": conflict_id,
                "project_id": project_id,
                "resolver": actor_id,
                "option_index": option_index,
                "has_custom_text": bool(custom_text),
                "trace_id": trace_id,
            },
        )

        # ---- apply -----------------------------------------------------
        outcome, detail = await self._apply(
            actions=apply_actions, actor_id=actor_id
        )

        async with session_scope(self._sessionmaker) as session:
            decision_repo = DecisionRepository(session)
            await decision_repo.mark_applied(
                decision_id, outcome=outcome, detail=detail
            )
            # Mark the conflict resolved even if apply was advisory — the
            # human's decision stands; the system just didn't mechanically
            # execute it.
            conflict_row = await ConflictRepository(session).resolve(
                conflict_id,
                user_id=actor_id,
                option_index=option_index,
            )
            conflict_payload = (
                self._conflicts._row_payload(conflict_row)
                if conflict_row is not None
                else None
            )
            decision_row = await decision_repo.get(decision_id)
            decision_payload = (
                self._decision_payload(decision_row)
                if decision_row is not None
                else None
            )

        # Tally must increment BEFORE emit: event_bus schedules
        # subscribers via asyncio.create_task, whose concurrent sessions
        # race the tally commit on aiosqlite and silently drop the write.
        if self._signal_tally is not None:
            await self._signal_tally.increment(actor_id, "decisions_resolved")
        await self._event_bus.emit(
            "decision.applied",
            {
                "decision_id": decision_id,
                "conflict_id": conflict_id,
                "project_id": project_id,
                "resolver": actor_id,
                "outcome": outcome,
                "detail": detail,
                "trace_id": trace_id,
            },
        )
        if conflict_payload is not None:
            await self._hub.publish(
                project_id, {"type": "conflict", "payload": conflict_payload}
            )
        if decision_payload is not None:
            await self._hub.publish(
                project_id, {"type": "decision", "payload": decision_payload}
            )

        # If we changed ownership, rerun detection so missing_owner goes
        # stale in the same pass — keep banner + list honest.
        if any(a.get("kind") == "assign_task" for a in apply_actions):
            self._conflicts.kick_recheck(project_id, trace_id=trace_id)

        return {
            "ok": True,
            "decision": decision_payload,
            "conflict": conflict_payload,
            "warnings": list(warnings),
        }

    async def list_for_project(
        self, project_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            rows = await DecisionRepository(session).list_for_project(
                project_id, limit=limit
            )
        return [self._decision_payload(r) for r in rows]

    async def list_for_conflict(
        self, conflict_id: str
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            rows = await DecisionRepository(session).list_for_conflict(
                conflict_id
            )
        return [self._decision_payload(r) for r in rows]

    # ---- internals -----------------------------------------------------

    def _plan_actions(
        self,
        *,
        rule: str,
        targets: list[str],
        assignee_user_id: str | None,
    ) -> list[dict[str, Any]]:
        """Translate a conflict + decision input into structured actions.

        Only `missing_owner` currently has a mechanical path: if the
        resolver provides `assignee_user_id`, we assign every task target
        to that user. Other rules record an advisory action so the UI
        can flag them as "decision logged — human follow-up required."
        """
        if rule == "missing_owner" and assignee_user_id:
            return [
                {"kind": "assign_task", "task_id": t, "user_id": assignee_user_id}
                for t in targets
            ]
        return [{"kind": "advisory", "rule": rule}]

    async def _apply(
        self,
        *,
        actions: list[dict[str, Any]],
        actor_id: str,
    ) -> tuple[str, dict[str, Any]]:
        """Execute the structured action list. Advisory-only → 'advisory'.

        Returns (outcome, detail). outcome ∈
        {ok, partial, failed, advisory}. detail carries per-action results
        for auditability.
        """
        if not actions or all(a.get("kind") == "advisory" for a in actions):
            return "advisory", {"reason": "no mechanical apply for this rule"}

        results: list[dict[str, Any]] = []
        succeeded = 0
        failed = 0
        for action in actions:
            kind = action.get("kind")
            if kind == "assign_task":
                task_id = action.get("task_id")
                user_id = action.get("user_id")
                try:
                    result = await self._assignments.set_assignment(
                        task_id=task_id, user_id=user_id, actor_id=actor_id
                    )
                except Exception as e:
                    _log.exception(
                        "decision assign_task raised",
                        extra={"task_id": task_id, "user_id": user_id},
                    )
                    results.append(
                        {"action": action, "ok": False, "error": str(e)}
                    )
                    failed += 1
                    continue
                if result.get("ok"):
                    succeeded += 1
                    results.append({"action": action, "ok": True})
                else:
                    failed += 1
                    results.append(
                        {
                            "action": action,
                            "ok": False,
                            "error": result.get("error", "assign_failed"),
                        }
                    )
            else:
                # Unknown action → skip, record for audit.
                results.append({"action": action, "ok": False, "error": "unknown_kind"})
                failed += 1

        if failed == 0:
            outcome = "ok"
        elif succeeded == 0:
            outcome = "failed"
        else:
            outcome = "partial"
        return outcome, {"results": results, "succeeded": succeeded, "failed": failed}

    def _decision_payload(self, row: DecisionRow) -> dict[str, Any]:
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


__all__ = ["DecisionService", "DecisionError"]
