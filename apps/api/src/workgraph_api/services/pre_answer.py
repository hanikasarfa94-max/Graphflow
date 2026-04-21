"""PreAnswerService — Stage 2 pre-answer routing.

Composes SkillAtlasService (for the target's skill card) and
PreAnswerAgent (for the LLM draft). Returns a payload the sender's UI
renders as a "would you accept this as an answer?" card.

Visibility model:
  * both sender and target must be members of the project
  * the pre-answer is shown to the SENDER only — the target never sees
    it unless the sender proceeds with routing (in which case the draft
    may optionally be appended as a framing hint on the routed signal;
    that's the sender's choice, not automatic)

Rate-limit: 4 drafts / minute / (sender, project). The LLM is called
once per draft, so this is modest but prevents pathological loops.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_agents import PreAnswerAgent
from workgraph_agents.citations import claims_payload, is_uncited, wrap_uncited
from workgraph_persistence import (
    DecisionRepository,
    ProjectMemberRepository,
    ProjectRow,
    UserRepository,
    session_scope,
)

from .license_context import LicenseContextService
from .skill_atlas import SkillAtlasService

_log = logging.getLogger("workgraph.api.pre_answer")

_RATE_WINDOW_SEC = 60.0
_RATE_LIMIT = 4


class PreAnswerService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        skill_atlas_service: SkillAtlasService,
        pre_answer_agent: PreAnswerAgent,
        license_context_service: LicenseContextService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._atlas = skill_atlas_service
        self._agent = pre_answer_agent
        self._license_ctx = license_context_service
        self._rate: dict[tuple[str, str], list[float]] = {}

    def _check_rate(self, *, sender_id: str, project_id: str) -> bool:
        key = (sender_id, project_id)
        now = time.monotonic()
        window = self._rate.setdefault(key, [])
        self._rate[key] = [t for t in window if now - t < _RATE_WINDOW_SEC]
        if len(self._rate[key]) >= _RATE_LIMIT:
            return False
        self._rate[key].append(now)
        return True

    async def _load_member_card(
        self, *, project_id: str, user_id: str, role: str
    ) -> dict[str, Any] | None:
        async with session_scope(self._sessionmaker) as session:
            return await self._atlas._member_card(
                session=session, user_id=user_id, role=role
            )

    async def _load_project_context(
        self,
        project_id: str,
        *,
        sender_user_id: str | None = None,
        target_user_id: str | None = None,
    ) -> dict[str, Any]:
        # License-scoped context: if we have both sender+target we pass
        # the pair to the slice builder so the tighter tier wins.
        # Falls through to the unscoped read when the slice builder
        # isn't wired (legacy tests).
        if (
            self._license_ctx is not None
            and sender_user_id is not None
        ):
            slice_ = await self._license_ctx.build_slice(
                project_id=project_id,
                viewer_user_id=sender_user_id,
                audience_user_id=target_user_id,
            )
            project = slice_.get("project") or {}
            decisions = (slice_.get("decisions") or [])[:6]
            return {
                "title": project.get("title"),
                "recent_decisions": [
                    {
                        "id": str(d.get("id")),
                        "summary": (
                            d.get("rationale") or d.get("custom_text") or ""
                        )[:200],
                    }
                    for d in decisions
                ],
                "license_tier": slice_.get("license_tier") or "full",
            }
        async with session_scope(self._sessionmaker) as session:
            project = (
                await session.execute(
                    select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            decisions = await DecisionRepository(
                session
            ).list_for_project(project_id, limit=6)
        return {
            "title": (project.title if project else None),
            "recent_decisions": [
                {
                    "id": str(d.id),
                    "summary": (d.rationale or d.custom_text or "")[:200],
                }
                for d in decisions
            ],
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

    async def _user_display(self, user_id: str) -> tuple[str, str]:
        async with session_scope(self._sessionmaker) as session:
            user = await UserRepository(session).get(user_id)
            if user is None:
                return ("", "")
            return (user.username, user.display_name or user.username)

    async def draft_pre_answer(
        self,
        *,
        project_id: str,
        sender_user_id: str,
        target_user_id: str,
        question: str,
    ) -> dict[str, Any]:
        """Produce a pre-answer for the sender to review.

        Shape:
          { "ok": True, "draft": {...}, "target": {...} }  on success
          { "ok": False, "error": "...", ... }             on failure
        """
        question = (question or "").strip()
        if not question:
            return {"ok": False, "error": "empty_question"}
        if sender_user_id == target_user_id:
            return {"ok": False, "error": "same_user"}

        if not self._check_rate(
            sender_id=sender_user_id, project_id=project_id
        ):
            return {"ok": False, "error": "rate_limited"}

        sender_role = await self._member_role(
            project_id=project_id, user_id=sender_user_id
        )
        target_role = await self._member_role(
            project_id=project_id, user_id=target_user_id
        )
        if sender_role is None:
            return {"ok": False, "error": "sender_not_member"}
        if target_role is None:
            return {"ok": False, "error": "target_not_member"}

        target_card = await self._load_member_card(
            project_id=project_id,
            user_id=target_user_id,
            role=target_role,
        )
        if target_card is None:
            return {"ok": False, "error": "target_not_found"}

        sender_username, sender_display = await self._user_display(
            sender_user_id
        )
        project_ctx = await self._load_project_context(
            project_id,
            sender_user_id=sender_user_id,
            target_user_id=target_user_id,
        )

        target_context = {
            "display_name": target_card["display_name"],
            "project_role": target_card["project_role"],
            "role_hints": target_card["role_hints"],
            "role_skills": target_card["role_skills"],
            "declared_abilities": target_card["profile_skills_declared"],
            "validated_skills": target_card["profile_skills_validated"],
        }
        sender_context = {
            "display_name": sender_display,
            "username": sender_username,
            "project_role": sender_role,
        }

        outcome = await self._agent.draft(
            question=question,
            target_context=target_context,
            sender_context=sender_context,
            project_context=project_ctx,
        )

        _log.info(
            "pre_answer.served",
            extra={
                "project_id": project_id,
                "sender": sender_user_id,
                "target": target_user_id,
                "confidence": outcome.draft.confidence,
                "recommend_route": outcome.draft.recommend_route,
                "outcome": outcome.outcome,
            },
        )

        draft_claims = list(outcome.draft.claims) or wrap_uncited(
            outcome.draft.body
        )
        return {
            "ok": True,
            "draft": {
                "body": outcome.draft.body,
                "confidence": outcome.draft.confidence,
                "matched_skills": outcome.draft.matched_skills,
                "uncovered_topics": outcome.draft.uncovered_topics,
                "recommend_route": outcome.draft.recommend_route,
                "rationale": outcome.draft.rationale,
                "claims": claims_payload(draft_claims),
                "uncited": is_uncited(draft_claims),
            },
            "target": {
                "user_id": target_user_id,
                "display_name": target_card["display_name"],
                "project_role": target_card["project_role"],
                "role_skills": target_card["role_skills"],
                "declared_abilities": target_card["profile_skills_declared"],
                "validated_skills": target_card["profile_skills_validated"],
            },
            "meta": {
                "outcome": outcome.outcome,
                "attempts": outcome.attempts,
            },
        }


__all__ = ["PreAnswerService"]
