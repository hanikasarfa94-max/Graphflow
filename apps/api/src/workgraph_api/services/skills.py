"""SkillsService — Phase Q tool execution (read-only).

The EdgeAgent.respond() prompt can return `kind="tool_call"` with a
structured `{name, args}`. The PersonalStreamService dispatches that
call through SkillsService, which:

  * Validates the skill name against ALLOWED_SKILLS.
  * Scopes every query to the project_id that originated the turn —
    a skill invocation from Maya's stream in project P never reads
    outside P.
  * Runs the skill as a pure read on the graph / KB.
  * Returns a uniform `{"ok": True, "result": {...}}` or
    `{"ok": False, "error": "..."}` envelope the caller can persist as
    an `edge-tool-result` system message body.

Skills are strictly read-only. None of them mutate the graph. This is
the invariant that makes bounded agent-loops safe: the system can
execute a tool call without asking the user, because the worst case
is "I wasted a token budget," not "I silently changed state."

Skill catalog (kept in lockstep with the respond prompt and with
`workgraph_agents.edge.ALLOWED_SKILLS`):

  * kb_search(query: str, limit: int = 3)
      → list of {id, source_kind, summary, tags, created_at}

  * recent_decisions(limit: int = 5)
      → list of {id, rationale, custom_text, option_index,
                 source_suggestion_id, created_at}

  * risk_scan(severity_floor: "low"|"medium"|"high" = "medium")
      → list of {id, title, content, severity, status, created_at}

  * member_profile(user_id: str)
      → {user_id, username, display_name, role, declared_abilities,
         role_hints, signal_tally}
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import ALLOWED_SKILLS
from workgraph_persistence import (
    AssignmentRepository,
    ConflictRepository,
    DecisionRepository,
    MembraneSignalRepository,
    MessageRepository,
    PlanRepository,
    ProjectGraphRepository,
    ProjectMemberRepository,
    RequirementRepository,
    RiskRow,
    UserRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.skills")


# Severity ordering used by risk_scan. Higher index → higher severity.
_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}

# Cap responses so a runaway LLM loop can't accidentally pull megabytes.
_KB_SEARCH_MAX_LIMIT = 20
_RECENT_DECISIONS_MAX_LIMIT = 20
_WHY_CHAIN_SCAN_LIMIT = 100  # how many recent decisions to score against a query
_WHY_CHAIN_MAX_RESULTS = 5

# routing_suggest — how many recent rows to pull for the activity signal.
_ROUTING_RECENT_MESSAGE_SCAN = 300
_ROUTING_RECENT_DECISION_SCAN = 100
_ROUTING_ACTIVITY_WINDOW_DAYS = 7
_ROUTING_MAX_RESULTS = 5

# Scorer weights. Graph distance dominates (the whole point of a graph-
# native platform); activity and profile are tie-breakers. Changing these
# constants is the primary knob for v2 — embeddings shift graph-distance,
# but the wire format stays stable.
_ROUTING_W_GRAPH = 0.50
_ROUTING_W_ACTIVITY = 0.30
_ROUTING_W_PROFILE = 0.20


class SkillsService:
    """Dispatcher for read-only skills the EdgeAgent may invoke."""

    # Re-export so callers can introspect without importing from agents.
    allowed_skills = frozenset(ALLOWED_SKILLS)

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def execute(
        self, *, project_id: str, skill_name: str, args: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Dispatch by skill_name. Returns `{ok, result}` on success,
        `{ok: False, error}` on failure.

        The envelope shape stays uniform so the PersonalStreamService
        can persist the result as a JSON system-message body without
        branching per skill.
        """
        args = dict(args or {})
        if skill_name not in self.allowed_skills:
            return {"ok": False, "error": "unknown_skill"}

        try:
            if skill_name == "kb_search":
                result = await self._kb_search(project_id=project_id, **args)
            elif skill_name == "recent_decisions":
                result = await self._recent_decisions(
                    project_id=project_id, **args
                )
            elif skill_name == "risk_scan":
                result = await self._risk_scan(project_id=project_id, **args)
            elif skill_name == "member_profile":
                result = await self._member_profile(
                    project_id=project_id, **args
                )
            elif skill_name == "why_chain":
                result = await self._why_chain(project_id=project_id, **args)
            elif skill_name == "routing_suggest":
                result = await self._routing_suggest(
                    project_id=project_id, **args
                )
            else:  # defensive — already guarded above
                return {"ok": False, "error": "unknown_skill"}
        except TypeError as e:
            # Wrong arg shape from the LLM — surface as a clean error
            # rather than exploding the whole turn.
            _log.warning(
                "skills.execute invalid_args",
                extra={"skill": skill_name, "error": str(e)},
            )
            return {"ok": False, "error": "invalid_args", "detail": str(e)}
        except Exception:
            _log.exception(
                "skills.execute raised", extra={"skill": skill_name}
            )
            return {"ok": False, "error": "skill_failed"}

        return {"ok": True, "skill": skill_name, "result": result}

    # ------------------------------------------------------------------
    # Skill implementations.
    # ------------------------------------------------------------------

    async def _kb_search(
        self,
        *,
        project_id: str,
        query: str = "",
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Simple text-match over MembraneSignalRow content + classification.

        v1: case-insensitive substring match on raw_content, summary, and
        tags. Full-text / vector search is a v2 concern. Rejected rows
        never surface.
        """
        q = (query or "").strip().lower()
        try:
            limit_val = max(1, min(int(limit), _KB_SEARCH_MAX_LIMIT))
        except (TypeError, ValueError):
            limit_val = 3

        async with session_scope(self._sessionmaker) as session:
            repo = MembraneSignalRepository(session)
            # Pull more than `limit` so we can post-filter by substring
            # without losing recall; cap hard at 200 rows for the scan.
            rows = await repo.list_for_project(project_id, limit=200)
            # Exclude rejected — stale content the graph explicitly said
            # should never surface. Everything else is fair game.
            rows = [r for r in rows if r.status != "rejected"]

        matched: list[dict[str, Any]] = []
        for row in rows:
            classification = dict(row.classification_json or {})
            summary = (classification.get("summary") or "")
            tags = list(classification.get("tags") or [])
            haystack_parts = [
                (row.raw_content or "").lower(),
                summary.lower(),
                " ".join(str(t).lower() for t in tags),
            ]
            if q and not any(q in part for part in haystack_parts):
                continue
            matched.append(
                {
                    "id": row.id,
                    "source_kind": row.source_kind,
                    "source_identifier": row.source_identifier,
                    "summary": summary[:200] if summary else (row.raw_content or "")[:200],
                    "tags": tags,
                    "status": row.status,
                    "created_at": (
                        row.created_at.isoformat() if row.created_at else None
                    ),
                }
            )
            if len(matched) >= limit_val:
                break
        return matched

    async def _recent_decisions(
        self, *, project_id: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        """Return the N most recent DecisionRows for this project."""
        try:
            limit_val = max(1, min(int(limit), _RECENT_DECISIONS_MAX_LIMIT))
        except (TypeError, ValueError):
            limit_val = 5

        async with session_scope(self._sessionmaker) as session:
            repo = DecisionRepository(session)
            rows = await repo.list_for_project(project_id, limit=limit_val)

        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "id": r.id,
                    "rationale": r.rationale or "",
                    "custom_text": r.custom_text,
                    "option_index": r.option_index,
                    "source_suggestion_id": r.source_suggestion_id,
                    "conflict_id": r.conflict_id,
                    "apply_outcome": r.apply_outcome,
                    "resolver_id": r.resolver_id,
                    "created_at": (
                        r.created_at.isoformat() if r.created_at else None
                    ),
                }
            )
        return out

    async def _risk_scan(
        self,
        *,
        project_id: str,
        severity_floor: str = "medium",
    ) -> list[dict[str, Any]]:
        """Return open RiskRows at or above `severity_floor`.

        Anything the graph hasn't marked 'closed' / 'resolved' counts as
        open in v1 — the field is free-form. "status == open" is the
        canonical value per _GraphEntityBase default.
        """
        floor = (severity_floor or "medium").lower()
        floor_rank = _SEVERITY_ORDER.get(floor)
        if floor_rank is None:
            return []

        async with session_scope(self._sessionmaker) as session:
            stmt = (
                select(RiskRow)
                .where(RiskRow.project_id == project_id)
                .order_by(RiskRow.sort_order)
            )
            rows = list((await session.execute(stmt)).scalars().all())

        out: list[dict[str, Any]] = []
        for r in rows:
            if r.status in ("closed", "resolved", "dismissed"):
                continue
            sev = (r.severity or "medium").lower()
            sev_rank = _SEVERITY_ORDER.get(sev, 1)
            if sev_rank < floor_rank:
                continue
            out.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "content": r.content,
                    "severity": sev,
                    "status": r.status,
                    "created_at": (
                        r.created_at.isoformat() if r.created_at else None
                    ),
                }
            )
        return out

    async def _member_profile(
        self, *, project_id: str, user_id: str
    ) -> dict[str, Any]:
        """Return the member's profile ONLY if they belong to this project.

        Scoping by project membership is the authorization boundary: a
        skill call from project A cannot read profile fields of a user
        who only belongs to project B. Returns an `{error}`-shaped dict
        inside the result on miss, so the caller can surface "no such
        member" without raising.
        """
        async with session_scope(self._sessionmaker) as session:
            pm_repo = ProjectMemberRepository(session)
            if not await pm_repo.is_member(project_id, user_id):
                return {"error": "not_a_project_member"}
            user = await UserRepository(session).get(user_id)
            if user is None:
                return {"error": "user_not_found"}
            profile = dict(user.profile or {})

        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": (profile.get("role_hints") or [None])[0] or "member",
            "declared_abilities": list(
                profile.get("declared_abilities") or []
            ),
            "role_hints": list(profile.get("role_hints") or []),
            "signal_tally": dict(profile.get("signal_tally") or {}),
        }


    # ------------------------------------------------------------------
    # why_chain — walks decision lineage matching a natural-language query.
    #
    # The v2 bet: decisions are the atomic unit. When a user asks "why
    # are we shipping April 30?", the answer isn't a search result — it's
    # a traversal. For each candidate decision we attach:
    #   * its rationale + custom_text (the "what")
    #   * its originating conflict summary, if any (the "why was this
    #     a decision at all")
    #   * the entity titles its conflict.targets point at (the "who /
    #     what was affected")
    #   * the resolver's display_name + timestamp (the "when / who
    #     made the call")
    #
    # Scoring is intentionally crude — lowercase substring match across
    # rationale / custom_text / conflict_summary / resolved-target
    # titles, with a recency tiebreaker so old-but-matching decisions
    # lose to recent-and-matching. When v2 adds embeddings we swap the
    # scorer here without changing the wire format.
    # ------------------------------------------------------------------
    async def _why_chain(
        self,
        *,
        project_id: str,
        query: str = "",
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        try:
            limit_val = max(1, min(int(limit), _WHY_CHAIN_MAX_RESULTS))
        except (TypeError, ValueError):
            limit_val = 3

        async with session_scope(self._sessionmaker) as session:
            dec_repo = DecisionRepository(session)
            decisions = await dec_repo.list_for_project(
                project_id, limit=_WHY_CHAIN_SCAN_LIMIT
            )
            if not decisions:
                return []

            # Batch-fetch the set of referenced conflicts.
            conflict_repo = ConflictRepository(session)
            conflict_ids = {d.conflict_id for d in decisions if d.conflict_id}
            conflicts = {}
            for cid in conflict_ids:
                row = await conflict_repo.get(cid)
                if row is not None:
                    conflicts[cid] = row

            # Build a single target-id → (kind, title) lookup across
            # every rendered graph kind. Both ProjectGraphRepository and
            # PlanRepository key off requirement_id, so we go through
            # the latest requirement version for this project. One round
            # trip here is cheap relative to the LLM turn that triggered
            # the skill.
            title_by_id: dict[str, str] = {}
            kind_by_id: dict[str, str] = {}
            req_repo = RequirementRepository(session)
            latest_req = await req_repo.latest_for_project(project_id)
            if latest_req is not None:
                graph = await ProjectGraphRepository(session).list_all(
                    latest_req.id
                )
                for g in graph.get("goals", []):
                    title_by_id[g.id] = g.title or ""
                    kind_by_id[g.id] = "goal"
                for d in graph.get("deliverables", []):
                    title_by_id[d.id] = d.title or ""
                    kind_by_id[d.id] = "deliverable"
                for r in graph.get("risks", []):
                    title_by_id[r.id] = r.title or ""
                    kind_by_id[r.id] = "risk"
                plan = await PlanRepository(session).list_all(latest_req.id)
                for t in plan.get("tasks", []):
                    title_by_id[t.id] = t.title or ""
                    kind_by_id[t.id] = "task"
                for m in plan.get("milestones", []):
                    title_by_id[m.id] = m.title or ""
                    kind_by_id[m.id] = "milestone"

            # Resolve resolver display names from project members.
            pm_repo = ProjectMemberRepository(session)
            user_repo = UserRepository(session)
            members = await pm_repo.list_for_project(project_id)
            member_ids = {m.user_id for m in members}
            name_by_user_id: dict[str, str] = {}
            for uid in {d.resolver_id for d in decisions if d.resolver_id}:
                if uid not in member_ids:
                    continue
                u = await user_repo.get(uid)
                if u is not None:
                    name_by_user_id[uid] = u.display_name or u.username

        # Score + shape the results. Substring matches across text fields
        # get a point each; a zero-score decision still surfaces if the
        # query is empty (fallback: recent decisions lineage-walked).
        scored: list[tuple[int, Any]] = []
        for d in decisions:
            conf = conflicts.get(d.conflict_id) if d.conflict_id else None
            target_ids = list(conf.targets) if conf else []
            target_titles = [
                title_by_id.get(tid, "") for tid in target_ids
            ]
            haystacks = [
                (d.rationale or "").lower(),
                (d.custom_text or "").lower(),
                (conf.summary.lower() if conf and conf.summary else ""),
                " ".join(t.lower() for t in target_titles),
            ]
            score = 0 if not q else sum(1 for h in haystacks if q in h)
            if q and score == 0:
                continue
            scored.append((score, (d, conf, target_ids, target_titles)))

        # Sort by (score desc, created_at desc). With q empty every row
        # tied at score=0 so we fall through to pure recency.
        scored.sort(
            key=lambda pair: (
                pair[0],
                pair[1][0].created_at or 0,
            ),
            reverse=True,
        )

        out: list[dict[str, Any]] = []
        for _score, (d, conf, target_ids, target_titles) in scored[:limit_val]:
            # `headline` is what the stream card displays. Prefer the
            # resolver's explicit custom_text (short, human-authored)
            # over the LLM rationale (usually a full paragraph).
            headline_source = (d.custom_text or d.rationale or "").strip()
            headline = headline_source.split("\n", 1)[0].split(". ", 1)[0]
            if len(headline) > 120:
                headline = headline[:119] + "…"
            # Resolved-target summary: first 5, with kind tags.
            affected = [
                {
                    "id": tid,
                    "kind": kind_by_id.get(tid, "unknown"),
                    "title": title_by_id.get(tid, "") or tid[:8],
                }
                for tid in target_ids[:5]
            ]
            out.append(
                {
                    "id": d.id,
                    "headline": headline or "(unlabelled decision)",
                    "rationale": d.rationale or "",
                    "conflict_summary": (
                        conf.summary if conf and conf.summary else None
                    ),
                    "affected": affected,
                    "resolver_name": name_by_user_id.get(d.resolver_id or ""),
                    "created_at": (
                        d.created_at.isoformat() if d.created_at else None
                    ),
                }
            )
        return out


    # ------------------------------------------------------------------
    # routing_suggest — graph-distance-aware candidate scorer.
    #
    # The v2 bet, sharpened: routing by graph distance beats routing by
    # org chart or @mention. When the edge LLM is about to propose a
    # route_proposal, it can call this skill to get a ranked list of
    # candidate members with explicit scores. Three signals:
    #
    #   graph_score — fraction of query tokens that appear in the titles
    #     of this member's assigned tasks OR in the rationale of
    #     decisions they've resolved. "How close is their work to the
    #     thing being asked?"
    #   activity_score — rolling-7d count of their messages + decisions,
    #     normalized to [0,1]. "Are they around right now?"
    #   profile_score — fraction of query tokens matching their
    #     declared_abilities + role_hints. "Have they self-declared
    #     expertise in this?"
    #
    # Source user is excluded (no self-routing). Members with zero signal
    # across all three axes are dropped so the LLM doesn't pick a
    # stranger with no visible connection to the issue. Query is tokenized
    # with a minimal lowercase split-on-whitespace pass; stop words and
    # short tokens are filtered. Embeddings replace this in v2 without
    # changing the wire format.
    # ------------------------------------------------------------------
    async def _routing_suggest(
        self,
        *,
        project_id: str,
        query: str = "",
        source_user_id: str | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        try:
            limit_val = max(1, min(int(limit), _ROUTING_MAX_RESULTS))
        except (TypeError, ValueError):
            limit_val = 3

        tokens = _tokenize_query(query)
        if not tokens:
            # No signal to score against. Return an empty list rather
            # than guess — the LLM should fall back to prompt intuition.
            return []

        async with session_scope(self._sessionmaker) as session:
            members = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            if not members:
                return []

            # Pre-fetch shared data once.
            assignments = await AssignmentRepository(session).list_for_project(
                project_id
            )
            active_assignments = [a for a in assignments if a.active]

            req_repo = RequirementRepository(session)
            latest_req = await req_repo.latest_for_project(project_id)
            task_title_by_id: dict[str, str] = {}
            if latest_req is not None:
                plan = await PlanRepository(session).list_all(latest_req.id)
                for t in plan.get("tasks", []):
                    task_title_by_id[t.id] = (t.title or "").lower()

            # All recent messages + decisions scoped to this project.
            msg_repo = MessageRepository(session)
            recent_messages = await msg_repo.list_recent(
                project_id, limit=_ROUTING_RECENT_MESSAGE_SCAN
            )
            dec_repo = DecisionRepository(session)
            recent_decisions = await dec_repo.list_for_project(
                project_id, limit=_ROUTING_RECENT_DECISION_SCAN
            )

            # SQLite in tests strips tz info on round-trip, leaving
            # naive datetimes in created_at. Compare on naive UTC so
            # aware/naive mix doesn't raise. Production Postgres
            # preserves tz, but since both sides become naive UTC the
            # comparison still behaves identically.
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            window_start = now - timedelta(days=_ROUTING_ACTIVITY_WINDOW_DAYS)

            def _as_naive(dt: datetime | None) -> datetime | None:
                if dt is None:
                    return None
                return dt.replace(tzinfo=None) if dt.tzinfo else dt

            # Hydrate per-member rollups.
            user_repo = UserRepository(session)
            scored: list[dict[str, Any]] = []

            for m in members:
                if source_user_id and m.user_id == source_user_id:
                    continue
                # Graph-distance tokens: concat the text the user is
                # plausibly "close to" into one haystack.
                assigned_task_ids = [
                    a.task_id
                    for a in active_assignments
                    if a.user_id == m.user_id
                ]
                graph_haystack_parts: list[str] = []
                for tid in assigned_task_ids:
                    title = task_title_by_id.get(tid)
                    if title:
                        graph_haystack_parts.append(title)
                for d in recent_decisions:
                    if d.resolver_id == m.user_id:
                        graph_haystack_parts.append(
                            (d.rationale or "").lower()
                        )
                        if d.custom_text:
                            graph_haystack_parts.append(d.custom_text.lower())
                graph_haystack = " ".join(graph_haystack_parts)
                graph_hits = sum(1 for tok in tokens if tok in graph_haystack)
                graph_score = graph_hits / len(tokens)

                # Activity in the 7d window.
                msg_count = sum(
                    1
                    for msg in recent_messages
                    if msg.author_id == m.user_id
                    and _as_naive(msg.created_at) is not None
                    and _as_naive(msg.created_at) >= window_start
                )
                dec_count = sum(
                    1
                    for d in recent_decisions
                    if d.resolver_id == m.user_id
                    and _as_naive(d.created_at) is not None
                    and _as_naive(d.created_at) >= window_start
                )
                # Normalize: 10 actions/week saturates. Simple ceiling.
                activity_score = min(1.0, (msg_count + dec_count) / 10.0)

                # Profile match.
                user = await user_repo.get(m.user_id)
                profile_text_parts: list[str] = []
                display_name = m.user_id
                if user is not None:
                    display_name = user.display_name or user.username
                    profile = dict(user.profile or {})
                    profile_text_parts.extend(
                        str(a).lower()
                        for a in (profile.get("declared_abilities") or [])
                    )
                    profile_text_parts.extend(
                        str(h).lower()
                        for h in (profile.get("role_hints") or [])
                    )
                profile_text = " ".join(profile_text_parts)
                profile_hits = (
                    sum(1 for tok in tokens if tok in profile_text)
                    if profile_text
                    else 0
                )
                profile_score = profile_hits / len(tokens) if tokens else 0.0

                total = (
                    _ROUTING_W_GRAPH * graph_score
                    + _ROUTING_W_ACTIVITY * activity_score
                    + _ROUTING_W_PROFILE * profile_score
                )
                # Drop members with zero signal — prevents the LLM from
                # proposing a teammate whose visible work has nothing
                # to do with the query.
                if total <= 0.0:
                    continue

                # Profile auto-evolution feedback (closes competition §10
                # item 1). If the candidate has a persisted signal_tally
                # for the kind we're routing, bump their score so
                # repeated resolvers rise over time. Bounded at +50% so
                # the graph / activity / profile signals still dominate
                # and the wire format stays stable.
                tally_affinity = _tally_affinity(user, tokens)
                total *= 1.0 + tally_affinity

                # Reason string — what made them rank? Pick whichever
                # of the three signals contributed most, back it up with
                # concrete evidence from the haystack.
                contributions = {
                    "graph": _ROUTING_W_GRAPH * graph_score,
                    "activity": _ROUTING_W_ACTIVITY * activity_score,
                    "profile": _ROUTING_W_PROFILE * profile_score,
                }
                primary = max(contributions, key=lambda k: contributions[k])
                if primary == "graph" and graph_hits > 0:
                    reason = "recent graph-adjacent work"
                elif primary == "activity":
                    reason = (
                        f"active this week ({msg_count + dec_count} signals)"
                    )
                elif primary == "profile" and profile_hits > 0:
                    reason = "self-declared expertise"
                else:
                    reason = "baseline fit"

                scored.append(
                    {
                        "user_id": m.user_id,
                        "display_name": display_name,
                        "role": m.role,
                        "score": round(total, 3),
                        "graph_score": round(graph_score, 3),
                        "activity_score": round(activity_score, 3),
                        "profile_score": round(profile_score, 3),
                        "reason": reason,
                    }
                )

        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:limit_val]


__all__ = ["SkillsService"]


# ---------------------------------------------------------------------------
# Tokenization helpers (module-private, pure).
# ---------------------------------------------------------------------------

# Minimal stop-word list — EN + ZH common non-content words. Not exhaustive;
# the goal is to prevent "the", "and", "is", "了", "的" from dominating the
# token set, not to build a linguist-grade tokenizer. Anything not in this
# list but ≥3 characters makes the cut.
_STOP_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "that",
        "this",
        "about",
        "which",
        "what",
        "why",
        "who",
        "how",
        "when",
        "where",
        "should",
        "could",
        "would",
        "can",
        "will",
        "are",
        "was",
        "has",
        "have",
        "but",
        "not",
        "请",
        "是否",
        "为什么",
        "怎么",
        "什么",
        "这个",
        "那个",
    }
)

_MAX_QUERY_TOKENS = 10

# Affinity cap — persisted-tally bump saturates at +50% so a long-tenured
# resolver doesn't eclipse a fresh but graph-relevant candidate. Saturation
# hits at ≈20 accumulated resolutions across decisions + routings (the
# kinds most predictive of "this person handles asks like this").
_TALLY_AFFINITY_CAP = 0.5
_TALLY_SATURATION = 20.0


def _tally_affinity(user, _tokens: list[str]) -> float:
    """Bounded multiplier derived from persisted signal_tally.

    Combines decisions_resolved + routings_answered as a "resolver track
    record" — the two kinds directly predictive of how useful a route is.
    messages_posted and risks_owned are noisier proxies and stay out of
    the bump so chatty members don't float to the top.
    """
    if user is None:
        return 0.0
    tally = (user.profile or {}).get("signal_tally") or {}
    if not isinstance(tally, dict):
        return 0.0
    score = 0
    for kind in ("decisions_resolved", "routings_answered"):
        try:
            score += int(tally.get(kind, 0) or 0)
        except (TypeError, ValueError):
            continue
    if score <= 0:
        return 0.0
    return min(_TALLY_AFFINITY_CAP, score / _TALLY_SATURATION)


def _tokenize_query(query: str) -> list[str]:
    """Lowercase split-on-whitespace tokenizer with a small stop-word filter.

    v1 is deliberately naive — embeddings replace it in v2 without
    changing the wire format of routing_suggest. The invariant we
    preserve: tokens are lowercase, unique, and non-empty; the list is
    capped so a megabyte of text can't blow up the scorer.
    """
    if not query:
        return []
    # Fold CJK punctuation to whitespace so "合规审查?为什么" splits.
    cleaned = re.sub(r"[\s。、,,.!?()()【】「」\[\]<>&|\\/:;\"'`]+", " ", query)
    parts = [p.strip().lower() for p in cleaned.split()]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if len(p) < 3:
            # Keep CJK bigrams — a 2-char CJK token carries meaning
            # even though EN 2-letter tokens don't. Heuristic: if the
            # token has any CJK codepoint, accept ≥ 2 chars.
            if len(p) >= 2 and any(
                "\u4e00" <= ch <= "\u9fff" for ch in p
            ):
                pass
            else:
                continue
        if p in _STOP_WORDS:
            continue
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
        if len(out) >= _MAX_QUERY_TOKENS:
            break
    return out
