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
from typing import Any, TYPE_CHECKING

from sqlalchemy.ext.asyncio import async_sessionmaker

if TYPE_CHECKING:
    from .simulation import SimulationService

from workgraph_domain import EventBus
from workgraph_persistence import (
    AssignmentRepository,
    DecisionRepository,
    EDGE_AGENT_SYSTEM_USER_ID,
    GatedProposalRepository,
    GatedProposalRow,
    InvalidProposalStateError,
    ProjectMemberRepository,
    ProjectRow,
    StreamRepository,
    TaskRow,
    UserRow,
    VoteRepository,
    session_scope,
)
from sqlalchemy import select

from .signal_tally import SignalTallyService
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
        signal_tally: SignalTallyService | None = None,
        simulation_service: "SimulationService | None" = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._streams = stream_service
        self._event_bus = event_bus
        self._signal_tally = signal_tally
        # Optional — absence is fine; counterfactual endpoint will
        # return an empty payload with reason='simulation_unavailable'.
        self._simulation = simulation_service

    # --------------------------------------------------------------- propose

    async def propose(
        self,
        *,
        project_id: str,
        proposer_user_id: str,
        decision_class: str,
        proposal_body: str,
        apply_actions: list[dict[str, Any]] | None = None,
        decision_text: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        proposal_body = (proposal_body or "").strip()
        if not proposal_body:
            raise GatedProposalError("empty_proposal_body")
        if decision_class not in VALID_DECISION_CLASSES:
            raise GatedProposalError("invalid_decision_class")
        # decision_text is optional but if supplied must be non-empty
        # and bounded. Treat bare whitespace as "not supplied".
        if decision_text is not None:
            decision_text = decision_text.strip()
            if not decision_text:
                decision_text = None
            elif len(decision_text) > 4000:
                decision_text = decision_text[:4000]

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
                decision_text=decision_text,
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

    # ----------------------------------------------------- vote mode (Phase S)
    #
    # When a proposal's authority is held by ≥2 members (owners ∪
    # gate-keeper), any of the following actors can convert the
    # single-approver proposal into a vote-mode proposal by calling
    # `open_to_vote`:
    #   * the proposer (always — it's *their* proposal)
    #   * any project owner (leader-requested vote)
    #   * the named gate-keeper, if any
    #
    # After conversion, status transitions pending → in_vote. Voters
    # cast via `cast_vote`. Threshold = ceil(len(voter_pool) / 2).
    # Resolution happens automatically inside `cast_vote` when the
    # threshold is reached on approve, or when remaining voters can no
    # longer reach threshold (deny-lock). On resolve, the normal
    # approved/denied flow fires — DecisionRow minted on approve,
    # proposer notified, existing event hooks fire.
    #
    # VoteRow is the first-class record. One row per (proposal, voter);
    # voters can change their verdict until resolution (upsert-style).

    _VOTE_SUBJECT_KIND = "gated_proposal"
    _VOTE_VERDICTS: frozenset[str] = frozenset({"approve", "deny", "abstain"})

    async def open_to_vote(
        self,
        *,
        proposal_id: str,
        acting_user_id: str,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """Convert a pending single-approver proposal to vote mode.

        Permission: proposer, any project owner, or the named gate-keeper.
        Voter pool: project owners ∪ {gate_keeper} (dedup; proposer is
        included if they're an owner). A pool of <2 is rejected —
        single-approver is still the right flow there.
        """
        async with session_scope(self._sessionmaker) as session:
            repo = GatedProposalRepository(session)
            proposal = await repo.get(proposal_id)
            if proposal is None:
                raise GatedProposalError("proposal_not_found", status=404)
            if proposal.status != "pending":
                raise GatedProposalError("already_resolved", status=409)

            pm_repo = ProjectMemberRepository(session)
            members = await pm_repo.list_for_project(proposal.project_id)
            owner_ids = {m.user_id for m in members if m.role == "owner"}
            all_member_ids = {m.user_id for m in members}

            # Permission check.
            allowed = (
                acting_user_id == proposal.proposer_user_id
                or acting_user_id in owner_ids
                or acting_user_id == proposal.gate_keeper_user_id
            )
            if not allowed:
                raise GatedProposalError("not_authorized_to_open_vote", status=403)

            # Build voter pool.
            pool = set(owner_ids)
            if proposal.gate_keeper_user_id in all_member_ids:
                pool.add(proposal.gate_keeper_user_id)
            # Only members can vote (guards against gate_keeper who left).
            pool &= all_member_ids
            voter_pool = sorted(pool)
            if len(voter_pool) < 2:
                raise GatedProposalError("insufficient_voters", status=409)

            proposal.status = "in_vote"
            proposal.voter_pool = voter_pool

            proposal_refreshed = await repo.get(proposal_id)
            payload = self._payload(proposal_refreshed)
            project_id = proposal.project_id
            decision_class = proposal.decision_class

        # Group-stream runtime log: the team sees "Vote opened on X
        # (threshold 2/3)". Must land before emit() so subscriber races
        # don't drop it.
        class_label = DECISION_CLASS_LABELS.get(decision_class, {}).get(
            "en"
        ) or decision_class
        threshold = self._threshold(voter_pool)
        await self._log_to_group_stream(
            project_id=project_id,
            body=(
                f"🗳 Vote opened on {class_label.lower()}: "
                f"{payload['proposal_body']} "
                f"(threshold {threshold}/{len(voter_pool)})"
            ),
            kind="vote-opened",
            linked_id=proposal_id,
        )

        await self._event_bus.emit(
            "gated_proposal.vote_opened",
            {
                "proposal_id": proposal_id,
                "project_id": project_id,
                "decision_class": decision_class,
                "opener": acting_user_id,
                "voter_pool": voter_pool,
                "threshold": threshold,
            },
        )

        return {"ok": True, "proposal": payload, "threshold": threshold}

    async def cast_vote(
        self,
        *,
        proposal_id: str,
        voter_user_id: str,
        verdict: str,
        rationale: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Voter casts / updates their verdict on an in-vote proposal.

        Returns the refreshed proposal payload plus a `tally` snapshot
        (approve/deny/abstain counts, threshold, whether the proposal
        resolved as a side effect of this cast).

        Idempotent: re-casting the same verdict is a no-op on the
        tally; changing verdict UPDATEs the existing VoteRow.
        """
        if verdict not in self._VOTE_VERDICTS:
            raise GatedProposalError("invalid_verdict")

        # Hold everything in one session so tally + (optional) resolve
        # are atomic. Threshold resolution happens inline; DecisionRow
        # minting mirrors the single-approver approve path.
        resolved_as: str | None = None
        decision_id: str | None = None

        async with session_scope(self._sessionmaker) as session:
            repo = GatedProposalRepository(session)
            vote_repo = VoteRepository(session)

            proposal = await repo.get(proposal_id)
            if proposal is None:
                raise GatedProposalError("proposal_not_found", status=404)
            if proposal.status != "in_vote":
                raise GatedProposalError("not_in_vote", status=409)
            pool = list(proposal.voter_pool or [])
            if voter_user_id not in pool:
                raise GatedProposalError("not_in_voter_pool", status=403)

            await vote_repo.upsert(
                subject_kind=self._VOTE_SUBJECT_KIND,
                subject_id=proposal_id,
                voter_user_id=voter_user_id,
                verdict=verdict,
                rationale=rationale,
                trace_id=trace_id,
            )

            votes = await vote_repo.list_for_subject(
                subject_kind=self._VOTE_SUBJECT_KIND, subject_id=proposal_id
            )
            approve = sum(1 for v in votes if v.verdict == "approve")
            deny = sum(1 for v in votes if v.verdict == "deny")
            abstain = sum(1 for v in votes if v.verdict == "abstain")
            outstanding = len(pool) - len(votes)
            threshold = self._threshold(pool)

            # Resolution: approve threshold reached?
            if approve >= threshold:
                decision = await DecisionRepository(session).create(
                    conflict_id=None,
                    project_id=proposal.project_id,
                    resolver_id=voter_user_id,  # the tipping vote
                    option_index=None,
                    custom_text=proposal.proposal_body,
                    rationale=f"Approved by vote ({approve}/{len(pool)})",
                    apply_actions=list(proposal.apply_actions or []),
                    trace_id=proposal.trace_id,
                    source_suggestion_id=None,
                    apply_outcome="advisory",
                    apply_detail={
                        "reason": "v0 gated proposal resolved by vote",
                        "approve": approve,
                        "deny": deny,
                        "abstain": abstain,
                        "pool_size": len(pool),
                    },
                    decision_class=proposal.decision_class,
                    gated_via_proposal_id=proposal.id,
                )
                decision_id = decision.id
                try:
                    await repo.resolve(
                        proposal_id,
                        status="approved",
                        resolution_note=f"Vote: {approve}/{len(pool)} approved",
                    )
                    resolved_as = "approved"
                except InvalidProposalStateError:
                    # Race with another caller. Rollback.
                    raise GatedProposalError("already_resolved", status=409)

            # Resolution: deny-lock (remaining voters cannot reach threshold)?
            elif approve + outstanding < threshold:
                try:
                    await repo.resolve(
                        proposal_id,
                        status="denied",
                        resolution_note=f"Vote: {deny} denied, threshold unreachable",
                    )
                    resolved_as = "denied"
                except InvalidProposalStateError:
                    raise GatedProposalError("already_resolved", status=409)

            proposal_refreshed = await repo.get(proposal_id)
            payload = self._payload(proposal_refreshed)
            project_id = proposal.project_id
            proposer_id = proposal.proposer_user_id
            decision_class = proposal.decision_class

        tally = {
            "approve": approve,
            "deny": deny,
            "abstain": abstain,
            "outstanding": outstanding,
            "pool_size": len(pool),
            "threshold": threshold,
        }

        # Bump the voter's profile tally BEFORE any emit() — the
        # emit-then-write race (see commit d0bf1fe / decisions.py) would
        # otherwise silently drop this. votes_cast counts every
        # verdict (approve / deny / abstain) — governance participation,
        # not just decisiveness.
        if self._signal_tally is not None:
            await self._signal_tally.increment(voter_user_id, "votes_cast")

        # Side effects AFTER session closes: stream posts + events.
        if resolved_as is not None:
            # Loop-closure: proposer's personal stream gets the outcome
            # so the thread started in their stream naturally concludes
            # there (matches the 1-to-1 route-back-to-origin pattern).
            await self._notify_proposer(
                project_id=project_id,
                proposer_id=proposer_id,
                proposal_id=proposal_id,
                decision_class=decision_class,
                status=resolved_as,
                rationale=payload.get("resolution_note") if payload else None,
            )
            # Group-stream runtime log: vote is group-layer, so the
            # team room gets a canonical resolution entry alongside
            # decisions / drift / commitments.
            class_label = DECISION_CLASS_LABELS.get(decision_class, {}).get(
                "en"
            ) or decision_class
            verdict_icon = "✓" if resolved_as == "approved" else "✗"
            abstain_frag = (
                f", {tally['abstain']} abstain" if tally["abstain"] else ""
            )
            body = (
                f"{verdict_icon} Vote {resolved_as} — {class_label.lower()}: "
                f"{tally['approve']} approve, {tally['deny']} deny"
                f"{abstain_frag} of {tally['pool_size']}"
            )
            await self._log_to_group_stream(
                project_id=project_id,
                body=body,
                kind=f"vote-resolved-{resolved_as}",
                linked_id=proposal_id,
            )
            await self._event_bus.emit(
                f"gated_proposal.{resolved_as}",
                {
                    "proposal_id": proposal_id,
                    "project_id": project_id,
                    "decision_class": decision_class,
                    "proposer": proposer_id,
                    "via": "vote",
                    "tally": tally,
                    "decision_id": decision_id,
                },
            )
        else:
            await self._event_bus.emit(
                "gated_proposal.vote_cast",
                {
                    "proposal_id": proposal_id,
                    "project_id": project_id,
                    "decision_class": decision_class,
                    "voter": voter_user_id,
                    "verdict": verdict,
                    "tally": tally,
                },
            )

        return {
            "ok": True,
            "proposal": payload,
            "tally": tally,
            "resolved_as": resolved_as,
            "decision_id": decision_id,
        }

    async def tally(self, *, proposal_id: str) -> dict[str, Any]:
        """Read-only tally snapshot. Safe to call on any proposal;
        returns threshold=None and pool_size=0 for non-vote proposals.
        """
        async with session_scope(self._sessionmaker) as session:
            repo = GatedProposalRepository(session)
            proposal = await repo.get(proposal_id)
            if proposal is None:
                raise GatedProposalError("proposal_not_found", status=404)
            pool = list(proposal.voter_pool or [])
            votes = await VoteRepository(session).list_for_subject(
                subject_kind=self._VOTE_SUBJECT_KIND, subject_id=proposal_id
            )
        approve = sum(1 for v in votes if v.verdict == "approve")
        deny = sum(1 for v in votes if v.verdict == "deny")
        abstain = sum(1 for v in votes if v.verdict == "abstain")
        return {
            "approve": approve,
            "deny": deny,
            "abstain": abstain,
            "outstanding": len(pool) - len(votes),
            "pool_size": len(pool),
            "threshold": self._threshold(pool) if pool else None,
            "votes": [
                {
                    "voter_user_id": v.voter_user_id,
                    "verdict": v.verdict,
                    "rationale": v.rationale,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                    "updated_at": v.updated_at.isoformat() if v.updated_at else None,
                }
                for v in votes
            ],
        }

    @staticmethod
    def _threshold(pool: list[str]) -> int:
        """Strict-majority threshold: floor(n/2) + 1.

        Pool sizes map to: 2→2, 3→2, 4→3, 5→3, 6→4, 7→4. More than half
        must approve for the proposal to pass — a tied vote (e.g. pool=4,
        approve=2, deny=2) does NOT resolve on approve, which matches
        intuition: a tie is not a win.
        """
        if not pool:
            return 0
        return len(pool) // 2 + 1

    # -------------------------------------------------------- counterfactual

    async def counterfactual(self, *, proposal_id: str) -> dict[str, Any]:
        """Predict the graph-shape effects of approving this proposal.

        The marquee view on a vote-pending card: "if this passes, here's
        what changes." Read-only. No writes, no events.

        Shape:
          {
            empty: bool,
            reason: str | None,       # 'advisory_only' | 'no_actions'
                                      # | 'proposal_resolved' | None
            proposal_id: str,
            status: str,              # current proposal.status for context
            action_count: int,
            advisory_count: int,
            reassignments: [{task_id, task_title, from_user_id,
                             from_display_name, to_user_id,
                             to_display_name}],
            unblocks: [{id, title}],          # reserved — empty in v0
            blocks: [{id, title}],            # reserved — empty in v0
            milestone_slips: [{id, title, slip_days}],  # reserved — empty
            total_effects: int,
          }

        Adapter contract — apply_actions → effect categories:
          * {kind: 'assign_task', task_id, user_id} → reassignment entry
            (delta against the *current* active assignment, if any).
          * {kind: 'advisory', ...}                 → advisory_count++
          * any other kind                          → action_count++ only
                                                      (generic — no
                                                      structured preview
                                                      available yet)

        Note: the v1 simulation primitive (`drop_task`) is orthogonal to
        today's apply_actions (which are additive: assign_task /
        advisory). When a future apply_action kind ('drop_task',
        'delay_milestone') lands, plumb it through by calling
        self._simulation.simulate(...) here and folding the result into
        unblocks / blocks / milestone_slips.
        """
        async with session_scope(self._sessionmaker) as session:
            proposal = await GatedProposalRepository(session).get(proposal_id)
            if proposal is None:
                raise GatedProposalError("proposal_not_found", status=404)

            actions: list[dict[str, Any]] = list(proposal.apply_actions or [])
            status = proposal.status
            project_id = proposal.project_id

            # Short-circuit: no actions at all, or only advisory entries
            # → empty preview, but with a distinguishing reason so the
            # card can render "advisory decision; no graph mutations
            # predicted" gracefully.
            if not actions:
                return {
                    "empty": True,
                    "reason": "no_actions",
                    "proposal_id": proposal_id,
                    "status": status,
                    "action_count": 0,
                    "advisory_count": 0,
                    "reassignments": [],
                    "unblocks": [],
                    "blocks": [],
                    "milestone_slips": [],
                    "total_effects": 0,
                }

            advisory_count = sum(
                1 for a in actions if a.get("kind") == "advisory"
            )
            assign_actions = [
                a for a in actions if a.get("kind") == "assign_task"
            ]
            if not assign_actions and advisory_count == len(actions):
                # All advisory — honest "no mechanical effects" case.
                return {
                    "empty": True,
                    "reason": "advisory_only",
                    "proposal_id": proposal_id,
                    "status": status,
                    "action_count": len(actions),
                    "advisory_count": advisory_count,
                    "reassignments": [],
                    "unblocks": [],
                    "blocks": [],
                    "milestone_slips": [],
                    "total_effects": 0,
                }

            # Resolve task + user details for assign_task previews. Batch
            # the selects so we don't do 2N round-trips for N actions.
            task_ids = [
                a.get("task_id") for a in assign_actions if a.get("task_id")
            ]
            to_user_ids = [
                a.get("user_id") for a in assign_actions if a.get("user_id")
            ]

            task_by_id: dict[str, TaskRow] = {}
            if task_ids:
                rows = (
                    await session.execute(
                        select(TaskRow).where(TaskRow.id.in_(task_ids))
                    )
                ).scalars().all()
                task_by_id = {r.id: r for r in rows}

            # Current active assignment per task — used to render the
            # reassignment delta ("from" side).
            assign_repo = AssignmentRepository(session)
            current_owner: dict[str, str | None] = {}
            for tid in task_ids:
                active = await assign_repo.active_for_task(tid)
                current_owner[tid] = active.user_id if active else None

            # Resolve display names in one hop — union of "from" owners
            # and proposed "to" users.
            user_ids_needed: set[str] = {
                uid for uid in current_owner.values() if uid
            }
            user_ids_needed.update(uid for uid in to_user_ids if uid)
            user_by_id: dict[str, UserRow] = {}
            if user_ids_needed:
                rows = (
                    await session.execute(
                        select(UserRow).where(UserRow.id.in_(user_ids_needed))
                    )
                ).scalars().all()
                user_by_id = {r.id: r for r in rows}

        def _name(uid: str | None) -> str | None:
            if not uid:
                return None
            u = user_by_id.get(uid)
            if u is None:
                return None
            return u.display_name or u.username

        reassignments: list[dict[str, Any]] = []
        for action in assign_actions:
            tid = action.get("task_id") or ""
            to_uid = action.get("user_id") or ""
            task = task_by_id.get(tid)
            from_uid = current_owner.get(tid)
            # Skip no-op reassignments (already owned by target) — not
            # worth rendering as a "change."
            if from_uid == to_uid and from_uid:
                continue
            reassignments.append(
                {
                    "task_id": tid,
                    "task_title": (task.title if task else "") or "",
                    "from_user_id": from_uid,
                    "from_display_name": _name(from_uid),
                    "to_user_id": to_uid or None,
                    "to_display_name": _name(to_uid),
                }
            )

        total_effects = len(reassignments)
        empty = total_effects == 0 and advisory_count == len(actions)

        return {
            "empty": empty,
            "reason": "advisory_only" if empty else None,
            "proposal_id": proposal_id,
            "status": status,
            "action_count": len(actions),
            "advisory_count": advisory_count,
            "reassignments": reassignments,
            # Reserved categories — kept in the shape so the frontend
            # doesn't have to feature-flag their rendering. These light
            # up once apply_actions grow a drop_task / delay_milestone
            # kind.
            "unblocks": [],
            "blocks": [],
            "milestone_slips": [],
            "total_effects": total_effects,
            # project_id is useful context for any follow-up fetch (e.g.
            # the full-graph simulation overlay on hover).
            "project_id": project_id,
        }

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

    async def list_inbox_for_user(
        self, *, user_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Unified inbox feed for a user — a proposal appears here when:

        * status='pending' AND they are the named gate-keeper (single-
          approver: waiting on their sign-off). Item kind='gate-sign-off'.
        * status='in_vote' AND they are in voter_pool (waiting on their
          verdict OR they can still change it). Item kind='vote-pending';
          `my_vote` carries their current verdict if they've already cast.

        Ordered by `created_at DESC` across both kinds so the sidebar
        shows most-recent-first regardless of type.

        Note: this does NOT replace the per-voter fan-out pattern you
        see in RoutedSignalRow — pending gated proposals are derived
        from voter_pool membership on read, so there's no schema
        explosion as voter counts grow. One GatedProposalRow → one
        canonical source of truth across all its voters.
        """
        async with session_scope(self._sessionmaker) as session:
            repo = GatedProposalRepository(session)
            # Gate-sign-offs (single-approver): existing query already
            # filters by gate_keeper_user_id + status='pending'.
            sign_offs = await repo.list_for_gate_keeper(
                user_id, status="pending", limit=limit
            )
            # Vote-pending: no direct repo method today. Query inline —
            # scan in_vote proposals and filter by voter_pool membership
            # in Python. At current scale (≤100 concurrent votes per
            # project) this is fine; if we ever need an index, a
            # materialized `gated_proposal_voters` join table is the
            # next step (parked; not competition-blocking).
            from sqlalchemy import select as _select

            in_vote_rows = (
                await session.execute(
                    _select(GatedProposalRow).where(
                        GatedProposalRow.status == "in_vote"
                    )
                )
            ).scalars().all()
            in_vote_for_me = [
                r for r in in_vote_rows
                if r.voter_pool and user_id in r.voter_pool
            ]

            # Build my_vote lookup for in_vote proposals in one pass.
            proposal_ids = [r.id for r in in_vote_for_me]
            my_votes: dict[str, dict[str, Any]] = {}
            if proposal_ids:
                from workgraph_persistence import VoteRow as _VoteRow
                rows = (
                    await session.execute(
                        _select(_VoteRow).where(
                            _VoteRow.subject_kind == self._VOTE_SUBJECT_KIND,
                            _VoteRow.voter_user_id == user_id,
                            _VoteRow.subject_id.in_(proposal_ids),
                        )
                    )
                ).scalars().all()
                for v in rows:
                    my_votes[v.subject_id] = {
                        "verdict": v.verdict,
                        "rationale": v.rationale,
                        "updated_at": (
                            v.updated_at.isoformat() if v.updated_at else None
                        ),
                    }

        items: list[dict[str, Any]] = []
        for row in sign_offs:
            items.append(
                {
                    "kind": "gate-sign-off",
                    "created_at": (
                        row.created_at.isoformat() if row.created_at else None
                    ),
                    "proposal": self._payload(row),
                    "my_vote": None,
                }
            )
        for row in in_vote_for_me:
            items.append(
                {
                    "kind": "vote-pending",
                    "created_at": (
                        row.created_at.isoformat() if row.created_at else None
                    ),
                    "proposal": self._payload(row),
                    "my_vote": my_votes.get(row.id),
                }
            )
        # Most-recent first across both kinds.
        items.sort(key=lambda i: i["created_at"] or "", reverse=True)
        return items[:limit]

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

    async def _log_to_group_stream(
        self,
        *,
        project_id: str,
        body: str,
        kind: str,
        linked_id: str,
    ) -> None:
        """Post a runtime-log system message into the project's shared
        group stream. Vote activity is group-layer by definition —
        opening + resolving get a canonical audit entry in the team
        feed alongside decisions / drift / commitments.

        Silent no-op if the project stream doesn't exist (shouldn't
        happen after boot backfill, but the service treats its absence
        as non-fatal — the proposal row itself is the source of truth).
        """
        async with session_scope(self._sessionmaker) as session:
            stream_row = await StreamRepository(session).get_for_project(
                project_id
            )
            stream_id = stream_row.id if stream_row is not None else None
        if stream_id is None:
            _log.warning(
                "gated_proposal group-stream log: no project stream",
                extra={"project_id": project_id, "linked_id": linked_id},
            )
            return
        await self._streams.post_system_message(
            stream_id=stream_id,
            author_id=EDGE_AGENT_SYSTEM_USER_ID,
            body=body,
            kind=kind,
            linked_id=linked_id,
        )

    def _payload(self, row: GatedProposalRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "project_id": row.project_id,
            "proposer_user_id": row.proposer_user_id,
            "gate_keeper_user_id": row.gate_keeper_user_id,
            "decision_class": row.decision_class,
            "proposal_body": row.proposal_body,
            "decision_text": row.decision_text,
            "apply_actions": list(row.apply_actions or []),
            "status": row.status,
            "resolution_note": row.resolution_note,
            "voter_pool": list(row.voter_pool or []) if row.voter_pool else None,
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
    "VOTE_SUBJECT_KIND",
]

# Exported for downstream consumers (e.g. voting_profile in
# compute_profile, cast_vote skill in workgraph_agents).
VOTE_SUBJECT_KIND = GatedProposalService._VOTE_SUBJECT_KIND
