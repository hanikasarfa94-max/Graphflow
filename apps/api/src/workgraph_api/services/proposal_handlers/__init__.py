"""Per candidate_kind accept handlers for IMService.

Phase C of the GraphFlow Architecture Organization Pass: replaces the
giant `if/elif candidate_kind == ...` block in `IMService._apply_proposal`
with a registry of single-responsibility handlers.

Each handler does ONE thing: the cell-side mutation specific to its
candidate_kind. Common concerns (loading the row, validating the
actor, persisting suggestion status, message/event emission, audit
logging) stay in `IMService`.

The dispatcher entry point is `default_registry()` from `.registry`.
"""
from __future__ import annotations

from .base import HandlerServices, ProposalHandler
from .kb import KbArchiveRequestHandler, KbItemGroupHandler
from .manual_invite import ManualInviteHandler
from .manual_room import ManualRoomHandler
from .manual_skill_change import ManualSkillChangeHandler
from .registry import default_registry
from .task import TaskPromoteHandler

__all__ = [
    "HandlerServices",
    "KbArchiveRequestHandler",
    "KbItemGroupHandler",
    "ManualInviteHandler",
    "ManualRoomHandler",
    "ManualSkillChangeHandler",
    "ProposalHandler",
    "TaskPromoteHandler",
    "default_registry",
]
