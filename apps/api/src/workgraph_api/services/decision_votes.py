"""DecisionVoteService — N.4 smallest-relevant-vote tally on decisions.

Pickup #6 (commit 4eec0ef) wrote `DecisionRow.scope_stream_id` so a
decision crystallized in a room scopes its quorum to that room's
members. This service is the read+write layer that materializes the
tally.

Polymorphic over the existing `VoteRow` model — `subject_kind="decision"`
joins the existing `gated_proposal` use without a schema change.
The room-stream slice's WS event shape (RoomTimelineEvent) carries
the tally as part of the decision item, so vote casts surface in
both the inline DecisionCard and (eventually) any tally-projecting
workbench panel without bespoke wiring.

Quorum derivation:
  * scope_stream_id set + stream is a 'room' → quorum = room member
    count. Voter must be a stream member.
  * scope_stream_id set + stream is the project's team-room → quorum
    = team-room member count (== all project members today).
  * scope_stream_id null → project-wide vote; quorum = project member
    count.

`status` is computed not stored:
  * "passed"  — approve >= ceil(quorum / 2) AND approve > deny
  * "failed"  — deny    >= ceil(quorum / 2) AND deny    > approve
  * "tied"    — approve == deny AND outstanding == 0
  * "open"    — outstanding > 0 AND neither side has hit threshold
"""
from __future__ import annotations

import logging
import math
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    DecisionRepository,
    ProjectMemberRepository,
    StreamMemberRepository,
    StreamRepository,
    VoteRepository,
    VoteRow,
    session_scope,
)

_log = logging.getLogger("workgraph.api.decision_votes")

VALID_VERDICTS: frozenset[str] = frozenset({"approve", "deny", "abstain"})
SUBJECT_KIND = "decision"


class DecisionVoteError(Exception):
    """Service-level error envelope. Carries a status code so the
    router can map directly without a translation table per error."""

    def __init__(self, code: str, *, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class DecisionVoteService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        *,
        collab_hub: Any | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._hub = collab_hub

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def cast_vote(
        self,
        *,
        decision_id: str,
        voter_user_id: str,
        verdict: str,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        """Cast or change a voter's verdict on a decision.

        Returns the updated tally + the voter's vote so the FE can
        round-trip without a follow-up GET. Also publishes a
        RoomTimelineEvent.timeline.update on the room stream when the
        decision is room-scoped, so every projection (inline +
        workbench) reconciles via the canonical reducer.

        Errors:
          * 'decision_not_found' (404)
          * 'invalid_verdict'    (400)
          * 'not_in_voter_pool'  (403) — voter isn't a member of the
            scope (room or project)
        """
        if verdict not in VALID_VERDICTS:
            raise DecisionVoteError("invalid_verdict")

        async with session_scope(self._sessionmaker) as session:
            decision = await DecisionRepository(session).get(decision_id)
            if decision is None:
                raise DecisionVoteError("decision_not_found", status=404)

            scope_stream_id = decision.scope_stream_id
            project_id = decision.project_id

            # Quorum + voter-pool resolution.
            in_pool = await self._is_in_pool(
                session=session,
                project_id=project_id,
                scope_stream_id=scope_stream_id,
                user_id=voter_user_id,
            )
            if not in_pool:
                raise DecisionVoteError("not_in_voter_pool", status=403)

            await VoteRepository(session).upsert(
                subject_kind=SUBJECT_KIND,
                subject_id=decision_id,
                voter_user_id=voter_user_id,
                verdict=verdict,
                rationale=rationale,
            )

            # Re-tally inside the same session so the response reflects
            # the freshly-cast vote without a second round trip.
            tally = await self._compute_tally(
                session=session,
                decision_id=decision_id,
                project_id=project_id,
                scope_stream_id=scope_stream_id,
            )
            my_vote_row = await VoteRepository(session).get_for_voter(
                subject_kind=SUBJECT_KIND,
                subject_id=decision_id,
                voter_user_id=voter_user_id,
            )

        my_vote = _vote_payload(my_vote_row) if my_vote_row else None

        # Publish a RoomTimelineEvent.timeline.update on the room
        # stream so workbench/timeline projections of this decision
        # both reconcile via the existing reducer (no new event type).
        if scope_stream_id and self._hub is not None:
            try:
                await self._hub.publish_stream(
                    scope_stream_id,
                    {
                        "type": "timeline.update",
                        "kind": "decision",
                        "id": decision_id,
                        "patch": {"tally": tally},
                    },
                )
            except Exception:
                _log.exception(
                    "decision_vote: publish_stream failed",
                    extra={
                        "decision_id": decision_id,
                        "stream_id": scope_stream_id,
                    },
                )

        return {"tally": tally, "my_vote": my_vote}

    async def get_tally(
        self,
        *,
        decision_id: str,
        viewer_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Read-only tally + the viewer's own vote (if any).

        Used by the FE to seed the DecisionCard without waiting for a
        WS frame. Does NOT enforce membership — read access is
        governed by the surrounding context (project state / room
        timeline endpoint already gates access at the slice they
        deliver).
        """
        async with session_scope(self._sessionmaker) as session:
            decision = await DecisionRepository(session).get(decision_id)
            if decision is None:
                raise DecisionVoteError("decision_not_found", status=404)
            tally = await self._compute_tally(
                session=session,
                decision_id=decision_id,
                project_id=decision.project_id,
                scope_stream_id=decision.scope_stream_id,
            )
            my_vote: dict[str, Any] | None = None
            if viewer_user_id is not None:
                row = await VoteRepository(session).get_for_voter(
                    subject_kind=SUBJECT_KIND,
                    subject_id=decision_id,
                    voter_user_id=viewer_user_id,
                )
                my_vote = _vote_payload(row) if row else None
        return {"tally": tally, "my_vote": my_vote}

    async def tally_for_decision(
        self,
        *,
        decision_id: str,
    ) -> dict[str, Any]:
        """Convenience used by IMService._decision_payload to bake the
        tally into the decision payload everywhere it's serialized.

        Tolerant: returns an empty tally on lookup failure rather than
        raising, so the payload-builder path never explodes.
        """
        try:
            res = await self.get_tally(decision_id=decision_id)
            return res["tally"]
        except Exception:
            _log.exception(
                "decision_vote.tally_for_decision swallowed",
                extra={"decision_id": decision_id},
            )
            return _empty_tally()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _is_in_pool(
        self,
        *,
        session,
        project_id: str,
        scope_stream_id: str | None,
        user_id: str,
    ) -> bool:
        """Voter pool gate.

        Room-scoped decisions: voter must be a stream member.
        Project-scoped (no scope_stream_id): voter must be a project
        member. The two queries are intentionally distinct — we don't
        widen project membership to grant room votes.
        """
        if scope_stream_id is not None:
            return await StreamMemberRepository(session).is_member(
                stream_id=scope_stream_id, user_id=user_id
            )
        return await ProjectMemberRepository(session).is_member(
            project_id, user_id
        )

    async def _compute_tally(
        self,
        *,
        session,
        decision_id: str,
        project_id: str,
        scope_stream_id: str | None,
    ) -> dict[str, Any]:
        votes = await VoteRepository(session).list_for_subject(
            subject_kind=SUBJECT_KIND, subject_id=decision_id
        )
        approve = sum(1 for v in votes if v.verdict == "approve")
        deny = sum(1 for v in votes if v.verdict == "deny")
        abstain = sum(1 for v in votes if v.verdict == "abstain")
        cast = approve + deny + abstain

        # Quorum size — same query the membership gate uses.
        if scope_stream_id is not None:
            members = await StreamMemberRepository(session).list_for_stream(
                scope_stream_id
            )
            quorum = len(members)
            scope_kind = "room"
        else:
            members = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            quorum = len(members)
            scope_kind = "project"

        outstanding = max(0, quorum - cast)

        # Threshold: simple majority of the scope membership.
        majority = math.ceil(quorum / 2) if quorum > 0 else 0
        if approve >= majority and approve > deny:
            status = "passed"
        elif deny >= majority and deny > approve:
            status = "failed"
        elif outstanding == 0 and approve == deny:
            status = "tied"
        else:
            status = "open"

        return {
            "approve": approve,
            "deny": deny,
            "abstain": abstain,
            "cast": cast,
            "quorum": quorum,
            "outstanding": outstanding,
            "majority": majority,
            "status": status,
            "scope_kind": scope_kind,
            "scope_stream_id": scope_stream_id,
        }


async def enrich_decision_with_tally(
    payload: dict[str, Any],
    sessionmaker: async_sessionmaker,
) -> dict[str, Any]:
    """Mutate a decision-shaped payload to include a `tally` field.

    Used at the WS publish + room-timeline assembly sites so every
    decision serialization carries the current tally without forcing
    a follow-up GET. Best-effort: failure leaves the payload alone
    plus an empty-tally placeholder so downstream type checks don't
    trip on a missing field.
    """
    decision_id = payload.get("id")
    if not isinstance(decision_id, str) or not decision_id:
        payload["tally"] = _empty_tally()
        return payload
    try:
        service = DecisionVoteService(sessionmaker)
        tally = await service.tally_for_decision(decision_id=decision_id)
        payload["tally"] = tally
    except Exception:
        _log.exception(
            "enrich_decision_with_tally swallowed",
            extra={"decision_id": decision_id},
        )
        payload["tally"] = _empty_tally()
    return payload


def _empty_tally() -> dict[str, Any]:
    return {
        "approve": 0,
        "deny": 0,
        "abstain": 0,
        "cast": 0,
        "quorum": 0,
        "outstanding": 0,
        "majority": 0,
        "status": "open",
        "scope_kind": "project",
        "scope_stream_id": None,
    }


def _vote_payload(row: VoteRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "verdict": row.verdict,
        "rationale": row.rationale,
        "voter_user_id": row.voter_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


__all__ = [
    "DecisionVoteError",
    "DecisionVoteService",
    "SUBJECT_KIND",
    "VALID_VERDICTS",
    "enrich_decision_with_tally",
]
