"""Per-recipe projectors. The facade calls one `derive_*` per recipe.

Each module is self-contained: SQL fetch, row→packet map, recipe-
specific helpers. Adding a recipe is a one-file change here plus
one line in the facade's `list_for_project`.
"""
from __future__ import annotations

from .decision import derive_decision_packets
from .handoff import derive_handoff_packets
from .kb_review import derive_kb_review_packets
from .manual_invite import derive_manual_invite_packets
from .manual_room import derive_manual_room_packets
from .manual_skill_change import derive_manual_skill_change_packets
from .route import derive_route_packets
from .task_promote import derive_task_promote_packets

__all__ = [
    "derive_decision_packets",
    "derive_handoff_packets",
    "derive_kb_review_packets",
    "derive_manual_invite_packets",
    "derive_manual_room_packets",
    "derive_manual_skill_change_packets",
    "derive_route_packets",
    "derive_task_promote_packets",
]
