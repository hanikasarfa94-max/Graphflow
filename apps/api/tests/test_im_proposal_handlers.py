"""Phase C — proposal_handlers registry contract.

Asserts:
  * Every candidate_kind the membrane today queues has a registered
    handler. Drift here = a candidate_kind was added without wiring an
    accept handler, which would leave that kind silently broken.
  * Unknown candidate_kind returns the same error shape the legacy
    inline dispatcher used: `{"ok": False,
    "error": "unknown_candidate_kind:<value>"}`. No new error type, no
    HTTP exception — the router maps !ok to 409 by reading the dict.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from workgraph_api.services.proposal_handlers import (
    HandlerServices,
    ProposalHandler,
    default_registry,
)


# Source of truth: the candidate_kinds the membrane stages today.
# Mirrors the inline dispatch that lived in `IMService._apply_proposal`
# pre Phase C. When MembraneService.review() learns a new CandidateKind,
# extend BOTH this list and `proposal_handlers.registry.default_registry`.
EXPECTED_CANDIDATE_KINDS = {
    "kb_item_group",
    "kb_archive_request",
    "task_promote",
    "manual_room",
    "manual_skill_change",
    "manual_invite",
}


def test_registry_covers_all_membrane_candidate_kinds() -> None:
    registry = default_registry()
    assert set(registry.keys()) == EXPECTED_CANDIDATE_KINDS


def test_registry_handlers_satisfy_protocol() -> None:
    registry = default_registry()
    for kind, handler in registry.items():
        assert isinstance(handler, ProposalHandler), (
            f"{kind} handler does not satisfy ProposalHandler"
        )
        # The runtime_checkable Protocol only checks attribute presence;
        # also pin candidate_kind matches the registry key so the index
        # can never disagree with the handler's self-declared kind.
        assert handler.candidate_kind == kind


def test_registry_keys_are_unique() -> None:
    # default_registry() builds the dict from a list of handlers; if two
    # handlers ever claim the same candidate_kind one would silently
    # overwrite the other. Detect by counting handlers vs dict size.
    registry = default_registry()
    # Re-build via the same code path the registry uses, but keep the
    # raw list around so we can compare lengths.
    from workgraph_api.services.proposal_handlers.kb import (
        KbArchiveRequestHandler,
        KbItemGroupHandler,
    )
    from workgraph_api.services.proposal_handlers.manual_invite import (
        ManualInviteHandler,
    )
    from workgraph_api.services.proposal_handlers.manual_room import (
        ManualRoomHandler,
    )
    from workgraph_api.services.proposal_handlers.manual_skill_change import (
        ManualSkillChangeHandler,
    )
    from workgraph_api.services.proposal_handlers.task import TaskPromoteHandler

    handlers = [
        KbItemGroupHandler(),
        KbArchiveRequestHandler(),
        TaskPromoteHandler(),
        ManualRoomHandler(),
        ManualSkillChangeHandler(),
        ManualInviteHandler(),
    ]
    assert len(handlers) == len(registry), (
        "Two handlers claim the same candidate_kind"
    )


@pytest.mark.asyncio
async def test_unknown_candidate_kind_returns_legacy_error_shape() -> None:
    """The dispatch in `IMService._apply_proposal` returns a dict (not
    raises) for unknown kinds. Match the EXACT error string the legacy
    inline code emitted: `unknown_candidate_kind:<value>`."""
    # Build a minimal IMService just enough to exercise _apply_proposal.
    # We bypass the constructor (lots of unrelated deps) and only set
    # the fields the membrane_review branch reads.
    from workgraph_api.services.im import IMService

    svc = IMService.__new__(IMService)
    svc._handler_registry = default_registry()
    svc._kb_item_service = None
    svc._stream_service = None
    svc._project_service = None
    svc._membrane_service = None

    fake_row = SimpleNamespace(
        kind="membrane_review",
        project_id="p1",
        message_id=None,
        reasoning="",
        proposal={
            "action": "approve_membrane_candidate",
            "detail": {"candidate_kind": "totally_made_up_kind"},
        },
    )
    result = await svc._apply_proposal(
        session=None, row=fake_row, actor_id="u1"
    )
    assert result == {
        "ok": False,
        "error": "unknown_candidate_kind:totally_made_up_kind",
    }


def test_handler_services_holds_late_bound_deps() -> None:
    # HandlerServices is __slots__-based; attempting to set an unknown
    # attribute raises AttributeError. This prevents drift where someone
    # wires a new dep into IMService without updating the bundle.
    services = HandlerServices(
        kb_item_service="kb",
        stream_service="stream",
        project_service="project",
        membrane_service="membrane",
    )
    assert services.kb_item_service == "kb"
    assert services.stream_service == "stream"
    assert services.project_service == "project"
    assert services.membrane_service == "membrane"

    with pytest.raises(AttributeError):
        services.bogus = "x"  # type: ignore[attr-defined]
