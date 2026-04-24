"""TutorialSeedService — welcome-project onboarding (game-style).

On first registration, seed a personal "Welcome to graphflow" project so
the new user lands inside a live state instead of an empty console:

  * A project titled "Welcome to graphflow" (or the zh variant, driven
    by the user's `display_language`). Title carries a canonical marker
    so the frontend can recognise and highlight the tutorial card.
  * 2–3 synthetic teammate users — globally shared, NOT reseeded per
    registration. Personas: Sam Chen (owner peer), Aiko Tanaka (member),
    Diego Ramirez (member). Password hashes are un-loginable sentinels.
  * The new user joins as owner; Sam joins as owner (so the vote pool
    reaches 2); Aiko + Diego join as members.
  * `gate_keeper_map = {"scope_cut": sam.id}` so a scope-cut proposal
    routes to Sam.
  * A seeded in-vote gated proposal ("Trim the auth feature from v1 to
    ship on time") with voter_pool = [new_user, sam]. Created directly
    rather than through the full propose/open_to_vote round-trip —
    we want the landing state to be "cast your vote now," not "wait for
    a round-trip."
  * Two warm-up messages in the project's group stream from Sam + Aiko
    so the room doesn't feel sterile.

Idempotence: re-calling `seed_for_new_user(user_id=…)` for a user who
already has a tutorial project is a no-op. Synthetic teammates are
looked up by username before creating. Safe to call from the register
endpoint unconditionally.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    GatedProposalRepository,
    ProjectMemberRepository,
    ProjectRow,
    StreamMemberRepository,
    StreamRepository,
    UserRepository,
    session_scope,
)

from .streams import StreamService

_log = logging.getLogger("workgraph.api.tutorial_seed")


# Canonical markers used by the frontend to recognise the tutorial
# project. Title strings double as the user-visible heading. Kept here
# (not in DESIGN.md) because the backend is the source of truth for the
# marker check.
TUTORIAL_TITLE_EN = "Welcome to graphflow"
TUTORIAL_TITLE_ZH = "graphflow 新手村"
TUTORIAL_TITLES = frozenset({TUTORIAL_TITLE_EN, TUTORIAL_TITLE_ZH})


def _tutorial_title(display_language: str | None) -> str:
    """Pick the right welcome title for the user's chrome language."""
    if display_language and display_language.lower().startswith("zh"):
        return TUTORIAL_TITLE_ZH
    return TUTORIAL_TITLE_EN


# Synthetic-teammate canonical personas. Globally shared — one row per
# persona across all tutorial projects. Usernames are stable so
# idempotence works by `get_by_username` lookup.
@dataclass(frozen=True)
class _Persona:
    username: str
    display_name: str
    role: str  # role in the tutorial project


_PERSONAS: tuple[_Persona, ...] = (
    _Persona(username="sam_chen_demo", display_name="Sam Chen", role="owner"),
    _Persona(username="aiko_tanaka_demo", display_name="Aiko Tanaka", role="member"),
    _Persona(username="diego_ramirez_demo", display_name="Diego Ramirez", role="member"),
)

# Sentinel password hash / salt that cannot validate any real input —
# `_hash_password(anything, "zz")` will never produce "__un_loginable__"
# because the hash is hex and longer. Keeps these rows out of the auth
# surface even if someone tries their usernames.
_UN_LOGINABLE_HASH = "__tutorial_synthetic__un_loginable__"
_UN_LOGINABLE_SALT = "00"

_PROPOSAL_BODY_EN = "Trim the auth feature from v1 to ship on time"
_PROPOSAL_TEXT_EN = "let's cut auth — it's blocking the demo"
_PROPOSAL_BODY_ZH = "把 v1 的登录功能砍掉,先按时上线"
_PROPOSAL_TEXT_ZH = "砍掉登录吧 —— 它卡住整个 demo 的演示"


class TutorialSeedService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        stream_service: StreamService,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._streams = stream_service

    async def seed_for_new_user(
        self, *, user_id: str, display_language: str | None = None
    ) -> dict[str, Any]:
        """Idempotent seed. Returns a small summary dict for observability.

        Contract: callers should swallow any exception — a failed seed
        must never block registration. The service logs warnings
        internally; exceptions still propagate so callers can log them
        with their own trace context.
        """
        title = _tutorial_title(display_language)

        # Phase 1: ensure user row exists (register is the only caller,
        # but defensive lookup keeps the service self-contained).
        async with session_scope(self._sessionmaker) as session:
            user_repo = UserRepository(session)
            user_row = await user_repo.get(user_id)
            if user_row is None:
                _log.warning(
                    "tutorial_seed: user not found",
                    extra={"user_id": user_id},
                )
                return {"ok": False, "reason": "user_not_found"}

            # Idempotence check: does this user already own a tutorial
            # project? Match by (title ∈ TUTORIAL_TITLES) on their
            # memberships. Cheap at the scale of "one user's projects."
            member_repo = ProjectMemberRepository(session)
            existing_memberships = await member_repo.list_for_user(user_id)
            if existing_memberships:
                project_ids = [m.project_id for m in existing_memberships]
                existing_rows = (
                    await session.execute(
                        select(ProjectRow).where(ProjectRow.id.in_(project_ids))
                    )
                ).scalars().all()
                for p in existing_rows:
                    if p.title in TUTORIAL_TITLES:
                        return {
                            "ok": True,
                            "already_seeded": True,
                            "project_id": p.id,
                        }

            # Phase 2: get-or-create synthetic personas. Globally shared
            # across all tutorial projects.
            persona_ids: dict[str, str] = {}
            for persona in _PERSONAS:
                row = await user_repo.get_by_username(persona.username)
                if row is None:
                    row = await user_repo.create(
                        username=persona.username,
                        password_hash=_UN_LOGINABLE_HASH,
                        password_salt=_UN_LOGINABLE_SALT,
                        display_name=persona.display_name,
                    )
                persona_ids[persona.username] = row.id
            sam_id = persona_ids["sam_chen_demo"]
            aiko_id = persona_ids["aiko_tanaka_demo"]

            # Phase 3: create the tutorial project.
            from workgraph_persistence.repositories import _new_id

            project_id = _new_id()
            project = ProjectRow(
                id=project_id,
                title=title,
                gate_keeper_map={"scope_cut": sam_id},
            )
            session.add(project)
            await session.flush()

            # Phase 4: memberships. User + Sam as owners (so the
            # owner-pool vote-pool reaches 2); Aiko + Diego as members.
            await member_repo.add(
                project_id=project_id, user_id=user_id, role="owner"
            )
            for persona in _PERSONAS:
                pid = persona_ids[persona.username]
                await member_repo.add(
                    project_id=project_id, user_id=pid, role=persona.role
                )

            # Phase 5: project (group) stream — created here rather than
            # waiting for a backfill. Members are added below so Sam +
            # Aiko can post warm-up messages.
            stream_repo = StreamRepository(session)
            group_stream = await stream_repo.get_for_project(project_id)
            if group_stream is None:
                group_stream = await stream_repo.create(
                    type="project", project_id=project_id
                )
            stream_member_repo = StreamMemberRepository(session)
            await stream_member_repo.add(
                stream_id=group_stream.id,
                user_id=user_id,
                role_in_stream="admin",
            )
            for persona in _PERSONAS:
                pid = persona_ids[persona.username]
                await stream_member_repo.add(
                    stream_id=group_stream.id,
                    user_id=pid,
                    role_in_stream=(
                        "admin" if persona.role == "owner" else "member"
                    ),
                )
            group_stream_id = group_stream.id

            # Phase 6: seeded gated proposal, directly in 'in_vote'
            # state. Pool = new user + Sam (both owners). Threshold = 2
            # — means the user's single approve vote is the tipping
            # vote, which is exactly the "cast in 10 seconds" story.
            is_zh = title == TUTORIAL_TITLE_ZH
            proposal_body = _PROPOSAL_BODY_ZH if is_zh else _PROPOSAL_BODY_EN
            proposal_text = _PROPOSAL_TEXT_ZH if is_zh else _PROPOSAL_TEXT_EN
            gp_repo = GatedProposalRepository(session)
            proposal = await gp_repo.create(
                project_id=project_id,
                proposer_user_id=sam_id,
                gate_keeper_user_id=sam_id,
                decision_class="scope_cut",
                proposal_body=proposal_body,
                decision_text=proposal_text,
                apply_actions=[],
            )
            # Transition pending → in_vote in the same txn. voter_pool =
            # owners only (user + Sam).
            voter_pool = sorted({user_id, sam_id})
            proposal.status = "in_vote"
            proposal.voter_pool = voter_pool
            await session.flush()
            proposal_id = proposal.id

        # Phase 7: warm-up group-stream messages. Done outside the
        # initial session so stream_service's own session_scope can
        # commit independently — matches how gated_proposals posts its
        # pending cards.
        welcome_line = (
            "欢迎加入!来,我们对范围问题过一个票。"
            if is_zh
            else "Hey, welcome aboard! Let's get a quick read on scope."
        )
        warmup_line = (
            "我先占个位——如果要按时上线,我觉得登录得先放放。"
            if is_zh
            else "Throwing this out there — if we want to ship on time, auth might have to wait."
        )
        try:
            await self._streams.post_system_message(
                stream_id=group_stream_id,
                author_id=aiko_id,
                body=welcome_line,
                kind="text",
                linked_id=None,
            )
            await self._streams.post_system_message(
                stream_id=group_stream_id,
                author_id=sam_id,
                body=warmup_line,
                kind="text",
                linked_id=None,
            )
            # Canonical "vote-opened" log so the group stream matches
            # the shape real vote flows produce.
            await self._streams.post_system_message(
                stream_id=group_stream_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=(
                    f"🗳 {proposal_body} (threshold 2/{len(voter_pool)})"
                ),
                kind="vote-opened",
                linked_id=proposal_id,
            )
        except Exception:  # noqa: BLE001 — warm-up is decorative
            _log.warning(
                "tutorial_seed: warm-up messages failed; project is still usable",
                extra={"project_id": project_id},
                exc_info=True,
            )

        _log.info(
            "tutorial_seed: created",
            extra={
                "user_id": user_id,
                "project_id": project_id,
                "proposal_id": proposal_id,
                "title": title,
            },
        )

        return {
            "ok": True,
            "already_seeded": False,
            "project_id": project_id,
            "proposal_id": proposal_id,
            "voter_pool": voter_pool,
            "title": title,
        }


__all__ = [
    "TutorialSeedService",
    "TUTORIAL_TITLE_EN",
    "TUTORIAL_TITLE_ZH",
    "TUTORIAL_TITLES",
]
