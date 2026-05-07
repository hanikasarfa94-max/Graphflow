"""Tiny dict-backed registry for candidate_kind → handler.

The membrane-review accept path branches on `proposal.detail.candidate_kind`
(see `MembraneCandidate.kind`). Adding a new kind is now:
  1. Write a handler module that satisfies `ProposalHandler`.
  2. Add it to `default_registry()` here.

No changes to IMService, no changes to the router.
"""
from __future__ import annotations

from .base import ProposalHandler
from .kb import KbArchiveRequestHandler, KbItemGroupHandler
from .manual_invite import ManualInviteHandler
from .manual_room import ManualRoomHandler
from .manual_skill_change import ManualSkillChangeHandler
from .task import TaskPromoteHandler


def default_registry() -> dict[str, ProposalHandler]:
    """Build the canonical candidate_kind → handler map.

    Construct fresh handlers per call so callers can mutate / replace
    the map in tests without leaking state across runs. Handlers are
    stateless, so the cost is negligible.
    """
    handlers: list[ProposalHandler] = [
        KbItemGroupHandler(),
        KbArchiveRequestHandler(),
        TaskPromoteHandler(),
        ManualRoomHandler(),
        ManualSkillChangeHandler(),
        ManualInviteHandler(),
    ]
    return {h.candidate_kind: h for h in handlers}


__all__ = ["default_registry"]
