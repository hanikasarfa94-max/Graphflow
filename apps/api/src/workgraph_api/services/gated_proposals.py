"""GatedProposalService — Scene 2 routing (migration 0014).

Background: Scene 2 of the routing-agent taxonomy — *"the user's
proposal requires a gate-keeper's sign-off"* (north-star §382, §219,
R19). Distinct from Scene 1 (graph-distance-driven expertise discovery)
and from LeaderEscalationService (license-view escalation, not
authority gating).

Flow:

    proposer types a decision-shape utterance
      → edge agent classifies it (decision_class in VALID_CLASSES)
      → edge agent checks project.gate_keeper_map for that class
      → if mapped AND proposer != gate_keeper, emit route_kind='gated'
      → on "send for sign-off", frontend POSTs to
        /api/projects/{id}/gated-proposals
      → GatedProposalService.propose creates GatedProposalRow (pending)
        + posts a 'gated-proposal-pending' message into the gate-keeper's
        personal stream with linked_id = proposal.id
      → gate-keeper approves or denies from their sidebar card
      → GatedProposalService.approve creates DecisionRow (lineage set) +
        marks proposal approved + posts 'gated-proposal-resolved' into
        the proposer's personal stream
      → GatedProposalService.deny marks proposal denied + posts
        'gated-proposal-resolved' (no DecisionRow created)

v0 scope (what we're NOT doing yet):

  * Mechanical action execution. `apply_actions` is persisted on the
    proposal and forwarded verbatim to DecisionRow on approve, with
    `apply_outcome='advisory'`. Wiring to DecisionService._apply is a
    follow-up — v0 decisions are audit-only. This matches how
    `silent_consensus.py` handles ratified decisions today.

  * DecisionRepository.create hardening (Option 2 in the v4 proposal).
    Nothing prevents another site from creating a DecisionRow with a
    gated class but no proposal lineage. That bypass-closing assertion
    is deliberately deferred — v0 relies on the edge agent being the
    sole source of gated-class decisions, which holds when edge is the
    only utterance classifier.

Safety invariants that ARE enforced:

  * state machine: pending → {approved, denied, withdrawn} (terminal).
    Enforced in GatedProposalRepository.resolve via
    InvalidProposalStateError.
  * permission: only the named gate_keeper can approve/deny;
    only the original proposer can withdraw.
  * self-sign-off: proposer != gate_keeper (checked at propose time).
  * unknown class: decision_class must be in VALID_CLASSES.
  * empty gate: if project.gate_keeper_map lacks the class, propose
    returns 'no_gate_keeper' — caller falls back to normal flow.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_domain import EventBus
from workgraph_persistence import (
    DecisionRepository,
    EDGE_AGENT_SYSTEM_USER_ID,
    GatedProposalRepository,
    GatedProposalRow,
    InvalidProposalStateError,
    ProjectMemberRepository,
    ProjectRow,
    session_scope,
)
from sqlalchemy import select

from .streams import StreamService

_log = logging.getLogger("workgraph.api.gated_proposals")


# Closed set for v0 — adding a new class requires an edge-agent prompt
# update (classifier) and a settings-UI entry. Free-form strings would
# let the LLM invent classes the gate-map can't satisfy.
VALID_DECISION_CLASSES: frozenset[str] = frozenset(
    {
        "budget",
        "legal",
        "hire",
        "scope_cut",
    }
)


# Human-readable labels for the settings UI + card headers. Kept in the
# backend so frontend + i18n strings stay centralized with the source of
# truth for the enum.
DECISION_CLASS_LABELS: dict[str, dict[str, str]] = {
    "budget": {"en": "Budget", "zh": "预算"},
    "legal": {"en": "Legal / IP", "zh": "法务 / IP"},
    "hire": {"en": "Hiring", "zh": "招聘"},
    "scope_cut": {"en": "Scope cut", "zh": "范围收缩"},
}


def get_gate_keeper(
    project_row: ProjectRow, decision_class: str
) -> str | None:
    """Lookup helper shared between the service and the edge-agent
    context builder. Returns user_id or None when the class is unmapped.
    """
    if decision_class not in VALID_DECISION_CLASSES:
        return None
    gate_map = project_row.gate_keeper_map or {}
    value = gate_map.get(decision_class)
    if isinstance(value, str) and value:
        return value
    return None


class GatedProposalError(Exception):
    """Raised for service-layer failures mapped to 4xx by the router."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class GatedProposalService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        stream_service: StreamService,
        event_bus: EventBus,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._streams = stream_service
        self._event_bus = event_bus

    # --------------------------------------------------------------- propose

    async def propose(
        self,
        *,
        project_id: str,
        proposer_user_id: str,
        decision_class: str,
        proposal_body: str,
        apply_actions: list[dict[str, Any]] | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        proposal_body = (proposal_body or "").strip()
        if not proposal_body:
            raise GatedProposalError("empty_proposal_body")
        if decision_class not in VALID_DECISION_CLASSES:
            raise GatedProposalError("invalid_decision_class")

        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project is None:
                raise GatedProposalError("project_not_found", status=404)

            pm_repo = ProjectMemberRepository(session)
            if not await pm_repo.is_member(project_id, proposer_user_id):
                raise GatedProposalError("proposer_not_member", status=403)

            gate_keeper_id = get_gate_keeper(project, decision_class)
            if gate_keeper_id is None:
                # Caller should fall back to the normal flow — no gate
                # applies for this class on this project.
                raise GatedProposalError("no_gate_keeper", status=409)
            if gate_keeper_id == proposer_user_id:
                # Proposer IS the gate-keeper. Skip the round-trip; the
                # caller should just crystallize directly. We still
                # surface this as an error so the edge agent knows to
                # re-route this turn as a plain decision-shape reply.
                raise GatedProposalError("proposer_is_gate_keeper", status=409)

            if not await pm_repo.is_member(project_id, gate_keeper_id):
                # Stale gate-map entry (gate-keeper was removed from
                # project but map wasn't cleaned up). Fail loud.
                raise GatedProposalError("gate_keeper_not_member", status=409)

            proposal = await GatedProposalRepository(session).create(
                project_id=project_id,
                proposer_user_id=proposer_user_id,
                gate_keeper_user_id=gate_keeper_id,
                decision_class=decision_class,
                proposal_body=proposal_body,
                apply_actions=list(apply_actions or []),
                trace_id=trace_id,
            )
            proposal_id = proposal.id

        # Post a pending card into the gate-keeper's personal stream so
        # it surfaces in their sidebar. The message kind is
        # 'gated-proposal-pending' with linked_id = proposal_id — the
        # frontend renders an approve/deny card from that pair.
        stream_info = await self._streams.ensure_personal_stream(
            user_id=gate_keeper_id, project_id=project_id
        )
        stream_id = stream_info.get("stream_id") if stream_info.get("ok") else None
        if stream_id is not None:
            await self._streams.post_system_message(
                stream_id=stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=proposal_body,
                kind="gated-proposal-pending",
                linked_id=proposal_id,
            )
        else:
            # Stream missing is not fatal — the proposal still exists;
            # gate-keeper can pick it up from the pending-list endpoint.
            _log.warning(
                "gated_proposal.propose: no personal stream for gate_keeper",
                extra={
                    "project_id": project_id,
                    "proposal_id": proposal_id,
                    "gate_keeper_id": gate_keeper_id,
                },
            )

        await self._event_bus.emit(
            "gated_proposal.proposed",
            {
                "proposal_id": proposal_id,
                "project_id": project_id,
                "decision_class": decision_class,
                "proposer": proposer_user_id,
                "gate_keeper": gate_keeper_id,
                "trace_id": trace_id,
            },
        )

        return {
            "ok": True,
            "proposal": self._payload(proposal),
        }

    # --------------------------------------------------------------- approve

    async def approve(
        self,
        *,
        proposal_id: str,
        acting_user_id: str,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """Gate-keeper approves. Creates DecisionRow + marks proposal
        approved atomically within a single session so a crash between
        the two leaves no orphan.
        """
        async with session_scope(self._sessionmaker) as session:
            repo = GatedProposalRepository(session)
            proposal = await repo.get(proposal_id)
            if proposal is None:
                raise GatedProposalError("proposal_not_found", status=404)
            self._assert_gate_keeper(proposal, acting_user_id)

            # Create the DecisionRow FIRST so if resolve() fails state-
            # machine-wise we haven't already minted a decision.
            decision = await DecisionRepository(session).create(
                conflict_id=None,
                project_id=proposal.project_id,
                resolver_id=acting_user_id,
                option_index=None,
                custom_text=proposal.proposal_body,
                rationale=rationale or "",
                apply_actions=list(proposal.apply_actions or []),
                trace_id=proposal.trace_id,
                source_suggestion_id=None,
                apply_outcome="advisory",
                apply_detail={"reason": "v0 gated proposal: advisory only"},
                decision_class=proposal.decision_class,
                gated_via_proposal_id=proposal.id,
            )
            decision_id = decision.id
            project_id = proposal.project_id
            proposer_id = proposal.proposer_user_id
            decision_class = proposal.decision_class

            try:
                await repo.resolve(
                    proposal_id, status="approved", resolution_note=rationale
                )
            except InvalidProposalStateError as exc:
                # Double-approve or approve-after-deny — reject the
                # second attempt but the DecisionRow we just created is
                # orphan. Roll the whole session back.
                raise GatedProposalError("already_resolved", status=409) from exc

            proposal_refreshed = await repo.get(proposal_id)
            payload = self._payload(proposal_refreshed) if proposal_refreshed else None

        await self._notify_proposer(
            project_id=project_id,
            proposer_id=proposer_id,
            proposal_id=proposal_id,
            decision_class=decision_class,
            status="approved",
            rationale=rationale,
        )

        await self._event_bus.emit(
            "gated_proposal.approved",
            {
                "proposal_id": proposal_id,
                "project_id": project_id,
                "decision_id": decision_id,
                "decision_class": decision_class,
                "gate_keeper": acting_user_id,
                "proposer": proposer_id,
            },
        )

        return {
            "ok": True,
            "proposal": payload,
            "decision_id": decision_id,
        }

    # --------------------------------------------------------------- deny

    async def deny(
        self,
        *,
        proposal_id: str,
        acting_user_id: str,
        resolution_note: str | None = None,
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            repo = GatedProposalRepository(session)
            proposal = await repo.get(proposal_id)
            if proposal is None:
                raise GatedProposalError("proposal_not_found", status=404)
            self._assert_gate_keeper(proposal, acting_user_id)

            try:
                await repo.resolve(
                    proposal_id,
                    status="denied",
                    resolution_note=resolution_note,
                )
            except InvalidProposalStateError as exc:
                raise GatedProposalError("already_resolved", status=409) from exc

            proposal_refreshed = await repo.get(proposal_id)
            payload = self._payload(proposal_refreshed) if proposal_refreshed else None
            project_id = proposal.project_id
            proposer_id = proposal.proposer_user_id
            decision_class = proposal.decision_class

        await self._notify_proposer(
            project_id=project_id,
            proposer_id=proposer_id,
            proposal_id=proposal_id,
            decision_class=decision_class,
            status="denied",
            rationale=resolution_note,
        )

        await self._event_bus.emit(
            "gated_proposal.denied",
            {
                "proposal_id": proposal_id,
                "project_id": project_id,
                "decision_class": decision_class,
                "gate_keeper": acting_user_id,
                "proposer": proposer_id,
            },
        )

        return {"ok": True, "proposal": payload}

    # --------------------------------------------------------------- withdraw

    async def withdraw(
        self, *, proposal_id: str, acting_user_id: str
    ) -> dict[str, Any]:
        """Proposer (only) can withdraw a still-pending proposal."""
        async with session_scope(self._sessionmaker) as session:
            repo = GatedProposalRepository(session)
            proposal = await repo.get(proposal_id)
            if proposal is None:
                raise GatedProposalError("proposal_not_found", status=404)
            if proposal.proposer_user_id != acting_user_id:
                raise GatedProposalError("not_proposer", status=403)

            try:
                await repo.resolve(
                    proposal_id,
                    status="withdrawn",
                    resolution_note=None,
                )
            except InvalidProposalStateError as exc:
                raise GatedProposalError("already_resolved", status=409) from exc

            proposal_refreshed = await repo.get(proposal_id)
            payload = self._payload(proposal_refreshed) if proposal_refreshed else None

        # Intentionally no cross-stream notification on withdraw — the
        # proposer is the one who made the call, and spamming the gate-
        # keeper with "never mind" cards clutters their sidebar.

        return {"ok": True, "proposal": payload}

    # --------------------------------------------------------------- listing

    async def list_pending_for_gate_keeper(
        self, *, user_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            rows = await GatedProposalRepository(
                session
            ).list_for_gate_keeper(user_id, status="pending", limit=limit)
        return [self._payload(r) for r in rows]

    async def list_for_project(
        self,
        *,
        project_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            rows = await GatedProposalRepository(session).list_for_project(
                project_id, status=status, limit=limit
            )
        return [self._payload(r) for r in rows]

    async def get(self, *, proposal_id: str) -> dict[str, Any] | None:
        async with session_scope(self._sessionmaker) as session:
            row = await GatedProposalRepository(session).get(proposal_id)
        return self._payload(row) if row is not None else None

    # --------------------------------------------------------------- internals

    def _assert_gate_keeper(
        self, proposal: GatedProposalRow, acting_user_id: str
    ) -> None:
        if proposal.gate_keeper_user_id != acting_user_id:
            raise GatedProposalError("not_gate_keeper", status=403)

    async def _notify_proposer(
        self,
        *,
        project_id: str,
        proposer_id: str,
        proposal_id: str,
        decision_class: str,
        status: str,
        rationale: str | None,
    ) -> None:
        """Post a resolved-card into the proposer's personal stream so
        the approve/deny outcome surfaces in their main chat.
        """
        stream_info = await self._streams.ensure_personal_stream(
            user_id=proposer_id, project_id=project_id
        )
        stream_id = stream_info.get("stream_id") if stream_info.get("ok") else None
        if stream_id is None:
            _log.warning(
                "gated_proposal notify: no personal stream for proposer",
                extra={
                    "project_id": project_id,
                    "proposal_id": proposal_id,
                    "proposer_id": proposer_id,
                },
            )
            return

        label = DECISION_CLASS_LABELS.get(decision_class, {}).get("en") or decision_class
        note = f" — {rationale}" if rationale else ""
        body = f"Your {label.lower()} proposal was {status}{note}."

        await self._streams.post_system_message(
            stream_id=stream_id,
            author_id=EDGE_AGENT_SYSTEM_USER_ID,
            body=body,
            kind="gated-proposal-resolved",
            linked_id=proposal_id,
        )

    def _payload(self, row: GatedProposalRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "proposer_user_id": row.proposer_user_id,
            "gate_keeper_user_id": row.gate_keeper_user_id,
            "decision_class": row.decision_class,
            "proposal_body": row.proposal_body,
            "apply_actions": list(row.apply_actions or []),
            "status": row.status,
            "resolution_note": row.resolution_note,
            "trace_id": row.trace_id,
            "created_at": (
                row.created_at.isoformat() if row.created_at else None
            ),
            "resolved_at": (
                row.resolved_at.isoformat() if row.resolved_at else None
            ),
        }


__all__ = [
    "GatedProposalService",
    "GatedProposalError",
    "VALID_DECISION_CLASSES",
    "DECISION_CLASS_LABELS",
    "get_gate_keeper",
]
