"""DissentService — Phase 2.A dissent + judgment accuracy.

A dissent is a member's recorded disagreement with a crystallized
DecisionRow. The value lives in two downstream flows:

  1. Lineage context — readers of the decision see who pushed back
     and why. Preserves the signal that the choice wasn't unanimous.
  2. Judgment accuracy — when outcomes later vindicate or refute the
     dissent, we flip `validated_by_outcome`. Rolled up per member on
     the perf panel so "whose dissents turned out right over time"
     becomes a promotion-relevant number.

Validation heuristic (chosen because the ORM doesn't carry explicit
decision→downstream-entity edges beyond the conflict.targets list):

  * SUPPORTED (a.k.a. `decision_reversed` / `decision_superseded`):
    when a NEW DecisionRow is applied against the SAME conflict_id as
    a prior decision, the prior decision is treated as superseded.
    All dissents on the prior decision flip `supported`, with the new
    decision's id appended to `outcome_evidence_ids`.

  * REFUTED (a.k.a. `milestone_hit` / `risk_materialized` supporting
    the decision): when the decision's own `apply_actions` have
    `apply_outcome == 'ok'`, the decision's direction bore concrete
    fruit — dissents against it flip `refuted`, with the decision's
    id appended as self-evidence (the apply_outcome flip IS the
    supporting event). This conservatively counts successful graph
    mutations ("closed the risk we said to close", "dropped the
    deliverable we said to drop") as "the decision worked". It does
    NOT try to chase task/milestone status transitions further
    downstream — that requires a decision↔task linkage the v1 ORM
    does not provide.

The subscriber hooks `decision.applied` (the existing canonical
event). On that single event we can check both conditions: did this
decision supersede a prior one? and did this decision's own apply
succeed? Both handlers are idempotent — re-running them against the
same event is a no-op when the dissents are already validated.

When tests or sibling services need to drive validation directly,
they call `validate_on_decision_applied` with the payload shape
emitted by DecisionService.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    DecisionRepository,
    DissentRepository,
    ProjectMemberRepository,
    UserRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.dissent")

# Cap on stance length. Mirrors the ORM column bound. Enforced server-
# side on create — 500 chars matches the PLAN spec and fits comfortably
# in a composer. Empty stance is invalid (a dissent needs a reason).
MAX_STANCE_CHARS = 500


class DissentError(Exception):
    """Base class for service-level dissent errors."""


@dataclass
class _SerializedDissent:
    id: str
    decision_id: str
    dissenter_user_id: str
    dissenter_display_name: str
    stance_text: str
    created_at: str
    validated_by_outcome: str | None
    outcome_evidence_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "decision_id": self.decision_id,
            "dissenter_user_id": self.dissenter_user_id,
            "dissenter_display_name": self.dissenter_display_name,
            "stance_text": self.stance_text,
            "created_at": self.created_at,
            "validated_by_outcome": self.validated_by_outcome,
            "outcome_evidence_ids": list(self.outcome_evidence_ids),
        }


class DissentService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus

    # ---- membership / lookup helpers ------------------------------------

    async def _is_member(
        self, *, project_id: str, user_id: str
    ) -> bool:
        async with session_scope(self._sessionmaker) as session:
            return await ProjectMemberRepository(session).is_member(
                project_id, user_id
            )

    async def _is_owner(
        self, *, project_id: str, user_id: str
    ) -> bool:
        async with session_scope(self._sessionmaker) as session:
            for m in await ProjectMemberRepository(
                session
            ).list_for_project(project_id):
                if m.user_id == user_id:
                    return m.role == "owner"
        return False

    async def _decision_belongs_to_project(
        self, *, project_id: str, decision_id: str
    ) -> bool:
        async with session_scope(self._sessionmaker) as session:
            row = await DecisionRepository(session).get(decision_id)
            return row is not None and row.project_id == project_id

    async def _user_display_name(self, user_id: str) -> str:
        async with session_scope(self._sessionmaker) as session:
            user = await UserRepository(session).get(user_id)
            if user is None:
                return ""
            return user.display_name or user.username

    # ---- public API -----------------------------------------------------

    async def record(
        self,
        *,
        project_id: str,
        decision_id: str,
        dissenter_user_id: str,
        stance_text: str,
    ) -> dict[str, Any]:
        """Upsert a dissent. Caller validates auth; this layer checks
        membership + decision-project match + stance bounds."""
        stance_text = (stance_text or "").strip()
        if not stance_text:
            return {"ok": False, "error": "stance_empty"}
        if len(stance_text) > MAX_STANCE_CHARS:
            return {"ok": False, "error": "stance_too_long"}
        if not await self._is_member(
            project_id=project_id, user_id=dissenter_user_id
        ):
            return {"ok": False, "error": "not_a_member"}
        if not await self._decision_belongs_to_project(
            project_id=project_id, decision_id=decision_id
        ):
            return {"ok": False, "error": "decision_not_in_project"}
        async with session_scope(self._sessionmaker) as session:
            row = await DissentRepository(session).upsert(
                decision_id=decision_id,
                dissenter_user_id=dissenter_user_id,
                stance_text=stance_text,
            )
            dissent_id = row.id
        await self._event_bus.emit(
            "dissent.recorded",
            {
                "dissent_id": dissent_id,
                "decision_id": decision_id,
                "project_id": project_id,
                "dissenter_user_id": dissenter_user_id,
            },
        )
        payload = await self._serialize_by_id(dissent_id)
        return {"ok": True, "dissent": payload}

    async def list_for_decision(
        self,
        *,
        project_id: str,
        decision_id: str,
    ) -> dict[str, Any]:
        if not await self._decision_belongs_to_project(
            project_id=project_id, decision_id=decision_id
        ):
            return {"ok": False, "error": "decision_not_in_project"}
        async with session_scope(self._sessionmaker) as session:
            rows = await DissentRepository(session).list_for_decision(
                decision_id
            )
        return {
            "ok": True,
            "dissents": [await self._serialize(r) for r in rows],
        }

    async def list_for_user_in_project(
        self,
        *,
        project_id: str,
        user_id: str,
        viewer_user_id: str,
    ) -> dict[str, Any]:
        """Surface one user's dissents across a project. Readable by
        the user themselves or a project owner; anyone else gets 403.
        """
        if not await self._is_member(
            project_id=project_id, user_id=viewer_user_id
        ):
            return {"ok": False, "error": "not_a_member"}
        if viewer_user_id != user_id:
            if not await self._is_owner(
                project_id=project_id, user_id=viewer_user_id
            ):
                return {"ok": False, "error": "forbidden"}
        async with session_scope(self._sessionmaker) as session:
            rows = await DissentRepository(
                session
            ).list_for_user_in_project(
                project_id=project_id, user_id=user_id
            )
        return {
            "ok": True,
            "dissents": [await self._serialize(r) for r in rows],
        }

    # ---- validation pipeline --------------------------------------------

    async def validate_on_decision_applied(
        self, payload: dict[str, Any]
    ) -> None:
        """Subscriber for the `decision.applied` event.

        Two passes:
          (1) Supersession pass — if this decision has a conflict_id
              and there is any PRIOR decision on the same conflict_id,
              flip every dissent on prior decisions to 'supported'
              with this decision's id as evidence.
          (2) Self-fruit pass — if THIS decision's apply_outcome is
              'ok' (real graph mutation), flip its own dissents to
              'refuted' with the decision's id as evidence. Advisory
              / failed / partial applies don't count — the decision
              didn't produce anything concrete, so the dissenter
              cannot yet be called wrong.
        """
        decision_id = payload.get("decision_id")
        conflict_id = payload.get("conflict_id")
        outcome = payload.get("outcome")
        if not isinstance(decision_id, str):
            return
        try:
            await self._validate_supersession(
                decision_id=decision_id,
                conflict_id=conflict_id if isinstance(conflict_id, str) else None,
            )
            if outcome == "ok":
                await self._validate_self_fruit(decision_id=decision_id)
        except Exception:  # pragma: no cover - subscriber safety net
            _log.exception("dissent validation failed", extra=payload)

    async def _validate_supersession(
        self,
        *,
        decision_id: str,
        conflict_id: str | None,
    ) -> None:
        if not conflict_id:
            return
        async with session_scope(self._sessionmaker) as session:
            prior = await DecisionRepository(session).list_for_conflict(
                conflict_id
            )
            flips: list[str] = []
            for prior_decision in prior:
                if prior_decision.id == decision_id:
                    continue
                dissents = await DissentRepository(
                    session
                ).list_for_decision(prior_decision.id)
                for d in dissents:
                    # Idempotent: if already supported (and this
                    # evidence id is recorded) skip the write.
                    if d.validated_by_outcome == "supported" and (
                        decision_id in (d.outcome_evidence_ids or [])
                    ):
                        continue
                    d.validated_by_outcome = "supported"
                    ev = list(d.outcome_evidence_ids or [])
                    if decision_id not in ev:
                        ev.append(decision_id)
                        d.outcome_evidence_ids = ev
                    flips.append(d.id)
            if flips:
                await session.flush()
        if flips:
            for fid in flips:
                await self._event_bus.emit(
                    "dissent.validated",
                    {
                        "dissent_id": fid,
                        "outcome": "supported",
                        "evidence_decision_id": decision_id,
                    },
                )

    async def _validate_self_fruit(
        self, *, decision_id: str
    ) -> None:
        async with session_scope(self._sessionmaker) as session:
            decision = await DecisionRepository(session).get(decision_id)
            if decision is None:
                return
            if decision.apply_outcome != "ok":
                return
            dissents = await DissentRepository(session).list_for_decision(
                decision_id
            )
            flips: list[str] = []
            for d in dissents:
                if d.validated_by_outcome == "refuted" and (
                    decision_id in (d.outcome_evidence_ids or [])
                ):
                    continue
                d.validated_by_outcome = "refuted"
                ev = list(d.outcome_evidence_ids or [])
                if decision_id not in ev:
                    ev.append(decision_id)
                    d.outcome_evidence_ids = ev
                flips.append(d.id)
            if flips:
                await session.flush()
        for fid in flips:
            await self._event_bus.emit(
                "dissent.validated",
                {
                    "dissent_id": fid,
                    "outcome": "refuted",
                    "evidence_decision_id": decision_id,
                },
            )

    # ---- serialization --------------------------------------------------

    async def _serialize(self, row: Any) -> dict[str, Any]:
        display = await self._user_display_name(row.dissenter_user_id)
        serialized = _SerializedDissent(
            id=row.id,
            decision_id=row.decision_id,
            dissenter_user_id=row.dissenter_user_id,
            dissenter_display_name=display,
            stance_text=row.stance_text,
            created_at=row.created_at.isoformat(),
            validated_by_outcome=row.validated_by_outcome,
            outcome_evidence_ids=list(row.outcome_evidence_ids or []),
        )
        return serialized.to_dict()

    async def _serialize_by_id(self, dissent_id: str) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            row = await DissentRepository(session).get(dissent_id)
        assert row is not None, "dissent id missing after upsert"
        return await self._serialize(row)


__all__ = ["DissentService", "DissentError", "MAX_STANCE_CHARS"]
