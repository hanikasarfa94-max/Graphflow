from __future__ import annotations

from uuid import uuid4


class DuplicateIntakeError(Exception):
    """Raised when (source, source_event_id) already exists."""

    def __init__(self, source: str, source_event_id: str, existing_project_id: str) -> None:
        super().__init__(
            f"intake already recorded: source={source} source_event_id={source_event_id}"
        )
        self.source = source
        self.source_event_id = source_event_id
        self.existing_project_id = existing_project_id


class InvalidProposalStateError(Exception):
    """GatedProposalRepository.resolve called on a non-pending row."""


def _new_id() -> str:
    return str(uuid4())


