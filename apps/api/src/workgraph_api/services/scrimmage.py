"""ScrimmageService — Phase 2.B agent-vs-agent debate orchestrator.

North-star §"Decisions are the atomic unit" + vision §"collaboration SLA":
before we interrupt a human with a routed question, let the two sub-agents
(source's and target's) debate for 2–3 turns. If they converge, surface
the proposal for human approval — don't waste the target's attention. If
they diverge, surface BOTH final stances side-by-side so humans pick up
with concrete context, not a blank question.

Per-turn contract:
  * Each turn's prompt context comes from
    `LicenseContextService.build_slice(audience_user_id=None,
                                      viewer_user_id=<turn-speaker>)`.
    The agent sees ONLY its owner's license slice — never the full graph.
    This prevents debate-turn leakage: a task_scoped target's sub-agent
    can't learn about out-of-scope risks just because the source's
    sub-agent cited them.
  * Turn 1 reuses PreAnswerService.draft_pre_answer to mint the target's
    opening draft — identical machinery to the existing single-sided
    pre-answer surface. Turns 2+ call the PreAnswerAgent directly with a
    debate-flavored project_context that embeds the prior transcript.

Convergence detector:
  * Each turn returns a PreAnswerDraft. We parse a stance triple from the
    draft's rationale by looking for `STANCE:<value>` / `PROPOSAL:<text>`
    markers. This lets stubbed agents emit explicit convergence signals
    for deterministic testing without mutating the PreAnswerDraft schema
    (which is a stable surface per the Phase 1 constraints).
  * Absent explicit markers we fall back to a heuristic:
      - `recommend_route=True`               → hold_position
      - `recommend_route=False` + high conf  → agree_with_other
      - otherwise                            → propose_compromise
  * Convergence = both sides' `proposal_summary` match (normalized) OR
    both stances are `agree_with_other` in the same turn.

On convergence: write pending DecisionRow (resolver_id = source as
proposer placeholder, apply_outcome="pending_scrimmage", custom_text =
proposal) + emit `scrimmage.converged`. The leader sees the card and
clicks "Approve as decision" to run the normal decision-submit flow.

On non-convergence: outcome='unresolved_crux'. Frontend renders both
stances as a DebateSummaryCard — the original "Ask [target]" flow is
still available so humans pick up where agents left off.

Stance hint markers (case-insensitive):
    STANCE:agree_with_other
    STANCE:propose_compromise
    STANCE:hold_position
    PROPOSAL:<summary up to one line>
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import PreAnswerAgent
from workgraph_agents.citations import claims_payload, wrap_uncited
from workgraph_domain import EventBus
from workgraph_observability import get_trace_id
from workgraph_persistence import (
    DecisionRepository,
    ProjectMemberRepository,
    ScrimmageRepository,
    ScrimmageRow,
    session_scope,
)

from .license_context import LicenseContextService
from .pre_answer import PreAnswerService
from .skill_atlas import SkillAtlasService

_log = logging.getLogger("workgraph.api.scrimmage")

MAX_TURNS = 3
VALID_STANCES = ("agree_with_other", "propose_compromise", "hold_position")

_STANCE_RE = re.compile(r"STANCE:\s*([a-z_]+)", re.IGNORECASE)
_PROPOSAL_RE = re.compile(
    r"PROPOSAL:\s*(.+?)(?:\n|$)", re.IGNORECASE
)


class ScrimmageError(Exception):
    """Raised for validation failures — router maps to 4xx."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _parse_stance_from_rationale(
    rationale: str,
    *,
    fallback_recommend_route: bool,
    fallback_confidence: str,
) -> tuple[str, str | None]:
    """Return (stance, proposal_summary).

    Parses explicit STANCE:/PROPOSAL: markers from the agent's rationale
    first. Falls back to a heuristic derived from the draft's
    recommend_route + confidence fields when markers are absent.
    """
    stance: str | None = None
    proposal: str | None = None
    if rationale:
        m = _STANCE_RE.search(rationale)
        if m:
            candidate = m.group(1).strip().lower()
            if candidate in VALID_STANCES:
                stance = candidate
        m2 = _PROPOSAL_RE.search(rationale)
        if m2:
            proposal = m2.group(1).strip()
    if stance is None:
        if fallback_recommend_route:
            stance = "hold_position"
        elif fallback_confidence == "high":
            stance = "agree_with_other"
        else:
            stance = "propose_compromise"
    return stance, proposal


def _norm_proposal(text: str | None) -> str:
    if not text:
        return ""
    return " ".join(text.strip().lower().split())


def _is_converged(turns: list[dict[str, Any]]) -> bool:
    """Detect convergence across the transcript so far.

    Two paths:
      * both sides' most recent `proposal_summary` match (normalized)
      * both sides' most recent `stance` is `agree_with_other`
    Requires at least one turn from each side.
    """
    last_by_speaker: dict[str, dict[str, Any]] = {}
    for t in turns:
        last_by_speaker[t["speaker"]] = t
    if "source" not in last_by_speaker or "target" not in last_by_speaker:
        return False
    src = last_by_speaker["source"]
    tgt = last_by_speaker["target"]
    if (
        src.get("stance") == "agree_with_other"
        and tgt.get("stance") == "agree_with_other"
    ):
        return True
    src_p = _norm_proposal(src.get("proposal_summary"))
    tgt_p = _norm_proposal(tgt.get("proposal_summary"))
    if src_p and tgt_p and src_p == tgt_p:
        return True
    return False


def _final_proposal(turns: list[dict[str, Any]]) -> str | None:
    """Pick the converged proposal text.

    Prefer the latest non-empty proposal_summary across either side; if
    both are `agree_with_other` with no summary, fall back to the latest
    target turn's text (that's what the target's sub-agent endorsed).
    """
    for t in reversed(turns):
        if t.get("proposal_summary"):
            return t["proposal_summary"]
    for t in reversed(turns):
        if t.get("speaker") == "target":
            return t.get("text")
    return None


class ScrimmageService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        event_bus: EventBus,
        pre_answer_service: PreAnswerService,
        pre_answer_agent: PreAnswerAgent,
        license_context_service: LicenseContextService,
        skill_atlas_service: SkillAtlasService,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._event_bus = event_bus
        self._pre_answer_service = pre_answer_service
        self._agent = pre_answer_agent
        self._license_ctx = license_context_service
        self._atlas = skill_atlas_service

    # ---- public API -------------------------------------------------------

    async def run_scrimmage(
        self,
        *,
        project_id: str,
        source_user_id: str,
        target_user_id: str,
        question: str,
        routed_signal_id: str | None = None,
    ) -> dict[str, Any]:
        """Run the full 2–3 turn debate and persist the transcript.

        Returns the scrimmage row shape (serialized). Raises
        ScrimmageError for input validation / membership failures.
        """
        question = (question or "").strip()
        if not question:
            raise ScrimmageError("empty_question")
        if source_user_id == target_user_id:
            raise ScrimmageError("same_user")

        src_role = await self._member_role(
            project_id=project_id, user_id=source_user_id
        )
        tgt_role = await self._member_role(
            project_id=project_id, user_id=target_user_id
        )
        if src_role is None:
            raise ScrimmageError("source_not_member", status=403)
        if tgt_role is None:
            raise ScrimmageError("target_not_member")

        trace_id = get_trace_id()
        async with session_scope(self._sessionmaker) as session:
            row = await ScrimmageRepository(session).create(
                project_id=project_id,
                source_user_id=source_user_id,
                target_user_id=target_user_id,
                question_text=question,
                routed_signal_id=routed_signal_id,
                trace_id=trace_id,
            )
            scrimmage_id = row.id

        transcript: list[dict[str, Any]] = []
        converged = False

        # ---- turn 1: target's sub-agent drafts opening position ------
        turn1 = await self._run_turn(
            speaker="target",
            turn_idx=1,
            project_id=project_id,
            speaker_user_id=target_user_id,
            other_user_id=source_user_id,
            question=question,
            transcript_so_far=[],
        )
        transcript.append(turn1)

        # ---- turn 2: source's sub-agent reads + responds -------------
        turn2 = await self._run_turn(
            speaker="source",
            turn_idx=2,
            project_id=project_id,
            speaker_user_id=source_user_id,
            other_user_id=target_user_id,
            question=question,
            transcript_so_far=transcript,
        )
        transcript.append(turn2)

        if _is_converged(transcript):
            converged = True
        else:
            # ---- turn 3 (optional): target's rebuttal ----------------
            turn3 = await self._run_turn(
                speaker="target",
                turn_idx=3,
                project_id=project_id,
                speaker_user_id=target_user_id,
                other_user_id=source_user_id,
                question=question,
                transcript_so_far=transcript,
            )
            transcript.append(turn3)
            converged = _is_converged(transcript)

        outcome = "converged_proposal" if converged else "unresolved_crux"
        proposal_text = _final_proposal(transcript) if converged else None

        proposal_payload: dict[str, Any] | None = None
        decision_id: str | None = None
        if converged and proposal_text:
            closing_src = _last_by_speaker(transcript, "source")
            closing_tgt = _last_by_speaker(transcript, "target")
            proposal_payload = {
                "proposal_text": proposal_text,
                "source_stance": (closing_src or {}).get("stance"),
                "target_stance": (closing_tgt or {}).get("stance"),
                "source_closing": (closing_src or {}).get("text"),
                "target_closing": (closing_tgt or {}).get("text"),
            }
            decision_id = await self._create_pending_decision(
                project_id=project_id,
                source_user_id=source_user_id,
                proposal_text=proposal_text,
                scrimmage_id=scrimmage_id,
                trace_id=trace_id,
            )
            proposal_payload["decision_id"] = decision_id

        async with session_scope(self._sessionmaker) as session:
            final_row = await ScrimmageRepository(session).finalize(
                scrimmage_id,
                transcript=transcript,
                outcome=outcome,
                proposal=proposal_payload,
            )

        # Event: leader sees converged proposals in their pending list;
        # non-converged surfaces in the source user's stream via the
        # frontend (DebateSummaryCard). We emit both paths for audit.
        await self._event_bus.emit(
            "scrimmage.converged" if converged else "scrimmage.unresolved",
            {
                "project_id": project_id,
                "scrimmage_id": scrimmage_id,
                "source_user_id": source_user_id,
                "target_user_id": target_user_id,
                "outcome": outcome,
                "decision_id": decision_id,
            },
        )

        _log.info(
            "scrimmage.completed",
            extra={
                "project_id": project_id,
                "scrimmage_id": scrimmage_id,
                "outcome": outcome,
                "turns": len(transcript),
            },
        )

        return _shape(final_row) if final_row else _shape_fallback(
            scrimmage_id=scrimmage_id,
            project_id=project_id,
            source_user_id=source_user_id,
            target_user_id=target_user_id,
            question=question,
            transcript=transcript,
            outcome=outcome,
            proposal=proposal_payload,
        )

    async def get_scrimmage(
        self,
        *,
        scrimmage_id: str,
        viewer_user_id: str,
    ) -> dict[str, Any]:
        """Fetch transcript, enforcing source/target/owner visibility."""
        async with session_scope(self._sessionmaker) as session:
            row = await ScrimmageRepository(session).get(scrimmage_id)
            if row is None:
                raise ScrimmageError("not_found", status=404)
            members = await ProjectMemberRepository(
                session
            ).list_for_project(row.project_id)
            viewer_is_owner = any(
                m.user_id == viewer_user_id and m.role == "owner"
                for m in members
            )

        if (
            viewer_user_id != row.source_user_id
            and viewer_user_id != row.target_user_id
            and not viewer_is_owner
        ):
            raise ScrimmageError("forbidden", status=403)

        return _shape(row)

    # ---- internals -------------------------------------------------------

    async def _run_turn(
        self,
        *,
        speaker: str,
        turn_idx: int,
        project_id: str,
        speaker_user_id: str,
        other_user_id: str,
        question: str,
        transcript_so_far: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build license-scoped prompt context for `speaker_user_id` and
        invoke PreAnswerAgent. Parse stance markers from the draft.

        For turn 1 where speaker='target' and no prior transcript exists,
        this is semantically identical to a single-sided pre-answer — we
        reuse PreAnswerService.draft_pre_answer so the exact prompt
        + skill-atlas payload stays consistent with the standalone
        pre-answer surface.
        """
        if turn_idx == 1 and speaker == "target" and not transcript_so_far:
            result = await self._pre_answer_service.draft_pre_answer(
                project_id=project_id,
                sender_user_id=other_user_id,
                target_user_id=speaker_user_id,
                question=question,
            )
            if not result.get("ok"):
                # Degrade gracefully: pre-answer rate-limit or a missing
                # target card means we still record a hold_position turn
                # with the error summarized. Better than crashing the
                # whole scrimmage flow.
                return {
                    "turn": turn_idx,
                    "speaker": speaker,
                    "text": f"pre-answer unavailable: {result.get('error')}",
                    "stance": "hold_position",
                    "proposal_summary": None,
                    "citations": [],
                    "confidence": "low",
                    "recommend_route": True,
                }
            draft = result["draft"]
            stance, proposal = _parse_stance_from_rationale(
                draft.get("rationale") or "",
                fallback_recommend_route=bool(draft.get("recommend_route")),
                fallback_confidence=draft.get("confidence") or "low",
            )
            return {
                "turn": turn_idx,
                "speaker": speaker,
                "text": draft.get("body") or "",
                "stance": stance,
                "proposal_summary": proposal,
                "citations": draft.get("claims")
                or claims_payload(wrap_uncited(draft.get("body"))),
                "confidence": draft.get("confidence") or "low",
                "recommend_route": bool(draft.get("recommend_route")),
                "rationale": draft.get("rationale") or "",
            }

        # Turns 2+: build a license-scoped slice for the speaker and
        # call the agent directly with a debate-flavored context.
        slice_ = await self._license_ctx.build_slice(
            project_id=project_id,
            viewer_user_id=speaker_user_id,
            audience_user_id=None,
        )
        speaker_context = await self._skill_card(
            project_id=project_id, user_id=speaker_user_id
        )
        other_context = await self._skill_card(
            project_id=project_id, user_id=other_user_id
        )

        # Encode the debate transcript as part of the project_context
        # payload the agent already accepts — no prompt schema change.
        project_context = {
            "title": (slice_.get("project") or {}).get("title"),
            "recent_decisions": [
                {
                    "id": str(d.get("id")),
                    "summary": (
                        d.get("rationale") or d.get("custom_text") or ""
                    )[:200],
                }
                for d in (slice_.get("decisions") or [])[:6]
            ],
            "license_tier": slice_.get("license_tier") or "full",
            "debate_transcript": [
                {
                    "turn": t["turn"],
                    "speaker": t["speaker"],
                    "text": t["text"],
                    "stance": t.get("stance"),
                }
                for t in transcript_so_far
            ],
            "debate_instructions": (
                "You are debating with the other member's sub-agent. Based on "
                "the prior turns, either (a) propose a compromise both sides "
                "can accept, (b) agree with the other side if their position "
                "is sound, or (c) hold your position with a refined rebuttal. "
                "Include `STANCE:<agree_with_other|propose_compromise|"
                "hold_position>` and optionally `PROPOSAL:<one-line summary>` "
                "in your rationale so the orchestrator can detect "
                "convergence."
            ),
        }

        # PreAnswerAgent's `target_context` / `sender_context` map onto
        # our (speaker, other) framing: the agent is drafting AS the
        # speaker, so the speaker's skill card goes into target_context.
        outcome = await self._agent.draft(
            question=question,
            target_context=_context_shape(speaker_context),
            sender_context=_context_shape(other_context),
            project_context=project_context,
        )

        draft = outcome.draft
        stance, proposal = _parse_stance_from_rationale(
            draft.rationale or "",
            fallback_recommend_route=draft.recommend_route,
            fallback_confidence=draft.confidence,
        )
        return {
            "turn": turn_idx,
            "speaker": speaker,
            "text": draft.body,
            "stance": stance,
            "proposal_summary": proposal,
            "citations": claims_payload(draft.claims or wrap_uncited(draft.body)),
            "confidence": draft.confidence,
            "recommend_route": draft.recommend_route,
            "rationale": draft.rationale or "",
        }

    async def _member_role(
        self, *, project_id: str, user_id: str
    ) -> str | None:
        async with session_scope(self._sessionmaker) as session:
            rows = await ProjectMemberRepository(
                session
            ).list_for_project(project_id)
            for r in rows:
                if r.user_id == user_id:
                    return r.role
        return None

    async def _skill_card(
        self, *, project_id: str, user_id: str
    ) -> dict[str, Any] | None:
        role = await self._member_role(
            project_id=project_id, user_id=user_id
        )
        if role is None:
            return None
        async with session_scope(self._sessionmaker) as session:
            return await self._atlas._member_card(
                session=session, user_id=user_id, role=role
            )

    async def _create_pending_decision(
        self,
        *,
        project_id: str,
        source_user_id: str,
        proposal_text: str,
        scrimmage_id: str,
        trace_id: str | None,
    ) -> str:
        """Create the pending DecisionRow the leader approves.

        Schema note: DecisionRow.resolver_id is NOT NULL (FK to users),
        so we use `source_user_id` as the placeholder "proposer". The
        `apply_outcome="pending_scrimmage"` sentinel lets leader-
        facing queries distinguish scrimmage-spawned proposals from
        crystallized ones. The leader's approval flow re-resolves by
        submitting a fresh decision via the existing endpoint; this
        row acts as the surfacing handle + audit trail.
        """
        async with session_scope(self._sessionmaker) as session:
            row = await DecisionRepository(session).create(
                conflict_id=None,
                project_id=project_id,
                resolver_id=source_user_id,
                option_index=None,
                custom_text=proposal_text[:4000],
                rationale=(
                    f"Scrimmage-converged proposal (scrimmage_id="
                    f"{scrimmage_id}). Awaiting leader approval."
                ),
                apply_actions=[],
                trace_id=trace_id,
                source_suggestion_id=None,
                apply_outcome="pending_scrimmage",
                apply_detail={"scrimmage_id": scrimmage_id},
            )
            return row.id


def _context_shape(card: dict[str, Any] | None) -> dict[str, Any]:
    """Render a skill-atlas card in the shape PreAnswerAgent expects."""
    if card is None:
        return {
            "display_name": "",
            "project_role": "",
            "role_hints": [],
            "role_skills": [],
            "declared_abilities": [],
            "validated_skills": [],
        }
    return {
        "display_name": card.get("display_name") or "",
        "project_role": card.get("project_role") or "",
        "role_hints": card.get("role_hints") or [],
        "role_skills": card.get("role_skills") or [],
        "declared_abilities": card.get("profile_skills_declared") or [],
        "validated_skills": card.get("profile_skills_validated") or [],
    }


def _last_by_speaker(
    turns: list[dict[str, Any]], speaker: str
) -> dict[str, Any] | None:
    for t in reversed(turns):
        if t.get("speaker") == speaker:
            return t
    return None


def _shape(row: ScrimmageRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "routed_signal_id": row.routed_signal_id,
        "source_user_id": row.source_user_id,
        "target_user_id": row.target_user_id,
        "question_text": row.question_text,
        "transcript": list(row.transcript_json or []),
        "outcome": row.outcome,
        "proposal": row.proposal_json,
        "trace_id": row.trace_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": (
            row.completed_at.isoformat() if row.completed_at else None
        ),
    }


def _shape_fallback(
    *,
    scrimmage_id: str,
    project_id: str,
    source_user_id: str,
    target_user_id: str,
    question: str,
    transcript: list[dict[str, Any]],
    outcome: str,
    proposal: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "id": scrimmage_id,
        "project_id": project_id,
        "routed_signal_id": None,
        "source_user_id": source_user_id,
        "target_user_id": target_user_id,
        "question_text": question,
        "transcript": transcript,
        "outcome": outcome,
        "proposal": proposal,
        "trace_id": None,
        "created_at": None,
        "completed_at": None,
    }


__all__ = ["ScrimmageService", "ScrimmageError", "MAX_TURNS"]
