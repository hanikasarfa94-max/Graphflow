"""Per-packet visibility + bucket selection + owner resolution.

Side-effect surface: one DB read in `_project_owner_ids` for the owner
list. Everything else is pure-python over the projected packet dicts.

These helpers sit between projection and the user-facing list — they
must NEVER mutate packets, and the visibility filter must always run
before status / bucket / recipe filters or the bucket combination
becomes a side-channel for non-participants.
"""
from __future__ import annotations

from typing import Any

from workgraph_persistence import ProjectMemberRepository

from .contracts import Bucket


async def _project_owner_ids(session, project_id: str) -> list[str]:
    """Fetch project owner user_ids — once per `list_for_project` call.

    Used both for visibility filtering (owners can audit any packet)
    and for populating `authority_user_ids` on owner-gated recipes
    (KB review, handoff finalize). Returns [] when the project has no
    owner row, which prevents authority from leaking to all members
    on a misconfigured project.
    """
    members = await ProjectMemberRepository(session).list_for_project(project_id)
    return [m.user_id for m in members if m.role == "owner"]


def _visible_to(
    packet: dict[str, Any], viewer_user_id: str, owner_ids: list[str]
) -> bool:
    """Per-packet visibility filter.

    Project membership alone is NOT enough — that was Slice A's leak.
    Visibility rules per recipe:

    - ask_with_context: source / current target / participants /
      authority owners. Other members do not see Maya↔Raj routes.
    - promote_to_memory: drafter / current target (the owner pool) /
      authority owners. Casual members do not see drafts moving
      through Membrane review.
    - handoff: from_user / to_user (target_user_ids) / authority
      owners. Other members don't see the routine transfer until it
      finalizes.

    Owners always see — they need audit visibility per §10. The
    drafter / source always sees their own work.
    """
    if viewer_user_id in owner_ids:
        return True
    if packet.get("source_user_id") == viewer_user_id:
        return True
    if viewer_user_id in (packet.get("target_user_ids") or []):
        return True
    if viewer_user_id in (packet.get("current_target_user_ids") or []):
        return True
    if viewer_user_id in (packet.get("authority_user_ids") or []):
        return True
    # DC slice — completed decisions are project-public. The
    # `list_for_project` route already gates project membership before
    # calling the projection, so any viewer reaching this filter is a
    # member; surfacing crystallized decisions to all of them matches
    # how DecisionRow rows render elsewhere (graph view, postmortem).
    if (
        packet.get("recipe_id") == "crystallize_decision"
        and packet.get("status") == "completed"
    ):
        return True
    return False


def _matches_bucket(
    packet: dict[str, Any], viewer_user_id: str, bucket: Bucket
) -> bool:
    """Apply a bucket filter to a single packet from `viewer_user_id`'s
    perspective. The bucket model in §10 is:

      needs_me            — viewer is in current_target_user_ids
                            OR is the source on a packet awaiting their
                            accept (e.g. a returned reply).
      waiting_on_others   — viewer is the source and someone else is
                            holding the next action.
      awaiting_membrane   — packet is gated on a Membrane decision.
      recent              — completed within the last 14 days.

    Buckets are deliberately overlap-friendly: a packet that needs me
    can also be awaiting_membrane; the UI groups by primary bucket and
    can re-check the others as badges.
    """
    if bucket == "needs_me":
        if viewer_user_id in (packet.get("current_target_user_ids") or []):
            return True
        # Source-side "your reply is waiting" — when reply has landed
        # but source hasn't accepted yet. Slice C will model this with
        # a richer next_actions; for now route packets in 'completed'
        # status with no source-accept event count.
        return False
    if bucket == "waiting_on_others":
        if packet.get("source_user_id") != viewer_user_id:
            return False
        if packet.get("status") != "active":
            return False
        targets = packet.get("current_target_user_ids") or []
        return bool(targets) and viewer_user_id not in targets
    if bucket == "awaiting_membrane":
        candidate = packet.get("membrane_candidate")
        return candidate is not None and packet.get("status") == "active"
    if bucket == "recent":
        return packet.get("status") == "completed"
    return True
