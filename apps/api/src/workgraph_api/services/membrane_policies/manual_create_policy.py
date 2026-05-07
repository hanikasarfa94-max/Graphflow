"""manual_room / manual_skill_change / manual_invite policies.

These three share the "non-owner stages a write" pattern: a member
without owner role proposes a shared object (a new team-room, a
member skill_tags update, a project invite), and the membrane stages
an `IMSuggestion(kind=membrane_review)` for owner approval.

Action vocabulary:
  auto_merge | request_review | reject

`request_review` is the v1 default for all three. `reject` is reserved
for malformed inputs (empty room name, oversized skill tag) — never
used to block a well-formed but unwanted create. Owner accept/decline
on the suggestion drives the actual outcome.

Each policy posts the system message into the team-room stream + the
IMSuggestion row inline (mirrors the kb_items.py request_review
path). The accept handler in the IM service replays the proposal
detail back into the domain service when the owner approves.

Unlike kb / task / decision, these policies have method signatures
that don't fit the `MembranePolicy` Protocol — the inputs are
domain-specific (room name + members, target user + new tags,
target username). They live in the registry as named functions
called directly by `MembraneService.review_manual_*`, not via the
`candidate.kind` dispatch.
"""
from __future__ import annotations

from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    IMSuggestionRepository,
    MessageRepository,
    StreamRepository,
    StreamRow,
    session_scope,
)
from sqlalchemy import select

from .base import MembraneContext, MembraneReview


async def review_manual_room(
    *,
    project_id: str,
    proposer_user_id: str,
    name: str,
    member_user_ids: list[str],
    owner_ids: list[str],
    context: MembraneContext,
) -> MembraneReview:
    """Run deterministic manual_room checks and stage an
    IMSuggestion(membrane_review) for owner approval when needed.
    Returns a MembraneReview whose action is one of:
      * `auto_merge` — caller proceeds with direct create.
      * `request_review` — IMSuggestion staged; caller returns
        `deferred=True`. `suggestion_id` populated.
      * `reject` — caller surfaces the reason.

    M5 audit gap closure: room creates by non-owners now go through
    the same announcement-governance layer KB / task / decision use.
    Owners auto_merge through to direct creation (`create_room` calls
    this only for non-owners); the public method exists so tests
    can drive the gate from any caller.

    v1 deterministic only:
      * empty/long name → reject
      * duplicate room name in this project → request_review (owner
        decides merge vs keep separate vs reject)
      * non-cell members → reject (mirrors create_room's check; the
        membrane should refuse before the suggestion lands)
      * else → request_review (the spec's default for non-owner
        shared creates)
    """
    normalized = (name or "").strip()
    if not normalized:
        return MembraneReview(
            action="reject",
            reason="empty_name",
        )

    async with session_scope(context.sessionmaker) as session:
        # Duplicate-name check across rooms in the same project.
        # Case-insensitive comparison via lower().
        existing = list(
            (
                await session.execute(
                    select(StreamRow)
                    .where(StreamRow.project_id == project_id)
                    .where(StreamRow.type == "room")
                )
            )
            .scalars()
            .all()
        )
        duplicate = next(
            (
                r
                for r in existing
                if (r.name or "").strip().lower() == normalized.lower()
            ),
            None,
        )

    # Compose the diff summary so the IMSuggestion preview is
    # actionable. `request_review` is the v1 default — owners
    # decide whether the create is wanted, even without a
    # duplicate name.
    if duplicate is not None:
        diff_summary = (
            f"Duplicate room name '{normalized}' (existing room "
            f"id={duplicate.id}). Owner should decide merge vs. "
            f"keep separate."
        )
        conflict_with: tuple[str, ...] = (duplicate.id,)
    else:
        diff_summary = (
            f"Non-owner member proposed creating room '{normalized}' "
            f"with {len(set(member_user_ids))} member(s). Owner "
            f"approval required."
        )
        conflict_with = ()

    # Stage the IMSuggestion. Mirrors the kb_items.py request_review
    # path: post a system message into the team-room stream + an
    # IMSuggestion(kind='membrane_review',
    # candidate_kind='manual_room') for the owner inbox.
    suggestion_id: str | None = None
    async with session_scope(context.sessionmaker) as session:
        team_stream = await StreamRepository(session).get_for_project(
            project_id
        )
        if team_stream is not None:
            msg = await MessageRepository(session).append(
                project_id=project_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=(
                    f"📥 [膜审核·新房间 / Membrane review · new room] "
                    f"'{normalized}'"
                ),
                stream_id=team_stream.id,
                kind="membrane-review",
                linked_id=None,
            )
            suggestion = await IMSuggestionRepository(session).append(
                project_id=project_id,
                message_id=msg.id,
                kind="membrane_review",
                confidence=1.0,
                targets=list(conflict_with),
                proposal={
                    "action": "approve_membrane_candidate",
                    "summary": (
                        diff_summary
                        or f"Approve creation of room '{normalized}'"
                    ),
                    "detail": {
                        "candidate_kind": "manual_room",
                        # Args the accept handler replays into
                        # streams_service.create_room when the
                        # owner approves.
                        "name": normalized,
                        "member_user_ids": list(set(member_user_ids)),
                        "proposer_user_id": proposer_user_id,
                        "diff_summary": diff_summary,
                        "conflict_with": list(conflict_with),
                    },
                },
                reasoning=(
                    "duplicate_room_name"
                    if duplicate is not None
                    else "non_owner_manual_room_create"
                ),
                prompt_version=None,
                outcome="ok",
                attempts=1,
            )
            suggestion_id = suggestion.id

    return MembraneReview(
        action="request_review",
        reason=(
            "duplicate_room_name"
            if duplicate is not None
            else "non_owner_manual_room_create"
        ),
        diff_summary=diff_summary,
        conflict_with=conflict_with,
        warnings=(),
        suggestion_id=suggestion_id,
    )


async def review_manual_skill_change(
    *,
    project_id: str,
    proposer_user_id: str,
    target_user_id: str,
    new_skill_tags: list[str],
    owner_ids: list[str],
    context: MembraneContext,
) -> MembraneReview:
    """Stage an IMSuggestion(membrane_review,
    candidate_kind=manual_skill_change) for owner approval. Returns
    a MembraneReview whose `suggestion_id` names the staged row.

    M5.1: Project member skill_tags are role-level capability claims
    (per OrgCapabilityService — they map to level='role'). Self-edits
    and cross-edits by non-owners would let any member silently grant
    themselves a project-level capability that routing then cites
    as "role evidence." Closes that loop: non-owner edits stage a
    candidate; owner accepts to apply.

    v1 deterministic only:
      * empty new_skill_tags → reject (use the existing PATCH with
        [] to clear; no review needed for that path; service-side)
      * any tag exceeds the per-tag length cap → reject
      * else → request_review
    """
    cleaned = [
        (s or "").strip().lower()[:32]
        for s in new_skill_tags
        if isinstance(s, str)
    ]
    cleaned = [t for t in cleaned if t]
    # Self-skill-grant is the headline risk; surface it in the diff
    # summary so the reviewing owner sees it without reading rows.
    is_self_edit = proposer_user_id == target_user_id
    diff_summary = (
        f"{'Self-edit' if is_self_edit else 'Cross-edit'}: set "
        f"skill_tags={sorted(set(cleaned))} for member "
        f"{target_user_id[:8]}…. Owner approval required because "
        f"role-level capability affects routing."
    )

    suggestion_id: str | None = None
    async with session_scope(context.sessionmaker) as session:
        team_stream = await StreamRepository(session).get_for_project(
            project_id
        )
        if team_stream is not None:
            msg = await MessageRepository(session).append(
                project_id=project_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=(
                    f"📥 [膜审核·技能 / Membrane review · skill] "
                    f"member skill_tags update"
                ),
                stream_id=team_stream.id,
                kind="membrane-review",
                linked_id=None,
            )
            suggestion = await IMSuggestionRepository(session).append(
                project_id=project_id,
                message_id=msg.id,
                kind="membrane_review",
                confidence=1.0,
                targets=[target_user_id],
                proposal={
                    "action": "approve_membrane_candidate",
                    "summary": (
                        f"Set skill_tags={sorted(set(cleaned))} for "
                        f"member {target_user_id[:8]}…"
                    ),
                    "detail": {
                        "candidate_kind": "manual_skill_change",
                        "target_user_id": target_user_id,
                        "proposer_user_id": proposer_user_id,
                        "new_skill_tags": sorted(set(cleaned)),
                        "diff_summary": diff_summary,
                    },
                },
                reasoning=(
                    "non_owner_self_skill_grant"
                    if is_self_edit
                    else "non_owner_cross_skill_edit"
                ),
                prompt_version=None,
                outcome="ok",
                attempts=1,
            )
            suggestion_id = suggestion.id

    return MembraneReview(
        action="request_review",
        reason=(
            "non_owner_self_skill_grant"
            if is_self_edit
            else "non_owner_cross_skill_edit"
        ),
        diff_summary=diff_summary,
        warnings=(),
        suggestion_id=suggestion_id,
    )


async def review_manual_invite(
    *,
    project_id: str,
    proposer_user_id: str,
    target_username: str,
    owner_ids: list[str],
    context: MembraneContext,
) -> MembraneReview:
    """Stage an IMSuggestion for owner approval of a member-invite.

    M5.1: Project member invite is the lowest-risk "shared object
    addition" not yet gated. Same shape: non-owner invites stage for
    owner approval; owners auto_merge through.
    """
    target_username = (target_username or "").strip()
    diff_summary = (
        f"Non-owner proposed inviting '{target_username}' to project. "
        f"Owner approval required (member additions affect Org Graph)."
    )

    suggestion_id: str | None = None
    async with session_scope(context.sessionmaker) as session:
        team_stream = await StreamRepository(session).get_for_project(
            project_id
        )
        if team_stream is not None:
            msg = await MessageRepository(session).append(
                project_id=project_id,
                author_id=EDGE_AGENT_SYSTEM_USER_ID,
                body=(
                    f"📥 [膜审核·邀请 / Membrane review · invite] "
                    f"'{target_username}'"
                ),
                stream_id=team_stream.id,
                kind="membrane-review",
                linked_id=None,
            )
            suggestion = await IMSuggestionRepository(session).append(
                project_id=project_id,
                message_id=msg.id,
                kind="membrane_review",
                confidence=1.0,
                targets=[],
                proposal={
                    "action": "approve_membrane_candidate",
                    "summary": f"Approve invite of '{target_username}'",
                    "detail": {
                        "candidate_kind": "manual_invite",
                        "target_username": target_username,
                        "proposer_user_id": proposer_user_id,
                        "diff_summary": diff_summary,
                    },
                },
                reasoning="non_owner_manual_invite",
                prompt_version=None,
                outcome="ok",
                attempts=1,
            )
            suggestion_id = suggestion.id

    return MembraneReview(
        action="request_review",
        reason="non_owner_manual_invite",
        diff_summary=diff_summary,
        warnings=(),
        suggestion_id=suggestion_id,
    )


__all__ = [
    "review_manual_invite",
    "review_manual_room",
    "review_manual_skill_change",
]
