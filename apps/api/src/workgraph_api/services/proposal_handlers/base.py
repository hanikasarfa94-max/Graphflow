"""Protocol shared by all candidate-kind handlers.

The membrane-review accept path queues a candidate (kb_item_group,
task_promote, manual_room, manual_skill_change, manual_invite,
kb_archive_request, …). Each candidate kind needs a distinct row
mutation when the owner clicks accept. This Protocol pins the call
shape so `IMService` can dispatch to a handler without knowing
which kind it is.

A handler does ONE thing: the cell-side mutation specific to its
candidate_kind. Things common to all kinds — loading the row,
validating the actor, persisting suggestion status, message/event
emission, audit logging — stay in `IMService`.

Handlers receive the SQLAlchemy session opened by `IMService.accept`
so the mutation joins the same transaction as the surrounding
status-flip / decision-crystallize work. They MUST NOT open their
own session.

Returns the same dict shape the legacy inline branches returned —
`{"ok": True, "graph_touched": True, "<kind>_id": ..., "action":
"approve_membrane_candidate"}` on success, `{"ok": False, "error":
"<code>"}` on failure. IMService normalizes nothing; the caller of
accept() reads the dict directly.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from workgraph_persistence import IMSuggestionRow


@runtime_checkable
class ProposalHandler(Protocol):
    """Per candidate_kind handler.

    Implementations declare the candidate_kind they own as a class
    attribute so the registry can index them without a separate
    factory call.
    """

    candidate_kind: str

    async def accept(
        self,
        *,
        session: Any,
        row: IMSuggestionRow,
        detail: dict[str, Any],
        actor_id: str | None,
        services: "HandlerServices",
    ) -> dict[str, Any]:
        """Apply the cell-side mutation for this candidate_kind.

        `services` carries the late-bound dependencies (stream,
        project, kb_item, membrane) so handlers don't reach into
        IMService internals. Some handlers ignore most of them.
        """
        ...


class HandlerServices:
    """Bundle of late-bound services handlers may need.

    `IMService` constructs a fresh instance per accept-call so a
    service that gets attached after construction is reflected. All
    fields are nullable — handlers MUST guard and return the same
    `{"ok": False, "error": "<service>_unavailable"}` shape the
    legacy code used.
    """

    __slots__ = (
        "kb_item_service",
        "stream_service",
        "project_service",
        "membrane_service",
    )

    def __init__(
        self,
        *,
        kb_item_service: Any | None = None,
        stream_service: Any | None = None,
        project_service: Any | None = None,
        membrane_service: Any | None = None,
    ) -> None:
        self.kb_item_service = kb_item_service
        self.stream_service = stream_service
        self.project_service = project_service
        self.membrane_service = membrane_service


__all__ = ["HandlerServices", "ProposalHandler"]
