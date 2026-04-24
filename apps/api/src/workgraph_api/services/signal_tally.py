"""SignalTallyService — persist observed-signal counts onto UserRow.profile.

Closes the response-profile auto-evolution loop (competition §10 item 1).
profile_tallies.py computes on read; this writes on emit so the persisted
counts can feed back into routing_suggest as an affinity bump without
requiring a second table scan on every rank call.

Design:
  * No new ORM columns. Everything lives inside the pre-existing
    UserRow.profile JSON dict under the `signal_tally` key.
  * Call sites stay one-line and swallow their own exceptions so a
    failed increment never breaks the primary flow (post / accept /
    reply). Persistence is best-effort; compute-on-read remains the
    safety net for tallies that may drift.
  * `signal_tally_updated_at` is bumped alongside every increment — the
    decay story (v3) will read this to age out stale counts; v2 just
    records the timestamp.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import UserRepository, session_scope

_log = logging.getLogger("workgraph.api.signal_tally")


# Signal kinds we currently persist. Kept minimal; mirrors the keys
# profile_tallies.py already computes on read so the two halves stay
# consistent in intent.
SIGNAL_KINDS: frozenset[str] = frozenset(
    {
        "messages_posted",
        "decisions_resolved",
        "routings_answered",
        "risks_owned",
        # Phase S — governance participation. Bumps on every cast_vote
        # regardless of verdict (approve / deny / abstain). Feeds
        # `voting_profile` in compute_profile → future authority
        # inference reads this as evidence of engaged voters.
        "votes_cast",
    }
)


class SignalTallyService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def increment(self, user_id: str, signal_kind: str) -> None:
        """Bump UserRow.profile['signal_tally'][signal_kind] by 1.

        Swallows every exception — call sites fire-and-forget from inside
        request handlers; a failed increment must not surface as a 500.
        """
        if not user_id or signal_kind not in SIGNAL_KINDS:
            return
        try:
            async with session_scope(self._sessionmaker) as session:
                repo = UserRepository(session)
                row = await repo.get(user_id)
                if row is None:
                    return
                profile = dict(row.profile or {})
                tally = dict(profile.get("signal_tally") or {})
                tally[signal_kind] = int(tally.get(signal_kind, 0)) + 1
                profile["signal_tally"] = tally
                profile["signal_tally_updated_at"] = datetime.now(
                    timezone.utc
                ).isoformat()
                row.profile = profile
                await session.flush()
        except Exception:
            _log.exception(
                "signal_tally.increment failed",
                extra={"user_id": user_id, "signal_kind": signal_kind},
            )


__all__ = ["SignalTallyService", "SIGNAL_KINDS"]
