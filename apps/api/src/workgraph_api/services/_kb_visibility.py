"""Slice M1.1 — canonical KB visibility whitelist.

Replaces the prior blacklist (`status not in ('archived', 'draft',
'rejected')`) which let `pending-review` rows leak into shared agent
pretext. That was the dogfood bug: a group-scope candidate the
Membrane had staged for owner review was nevertheless retrieval-
visible to every project agent.

Whitelist policy (single source of truth, applied at every point that
feeds shared memory into agent pretext or user search):

    source in {manual, upload, llm}  →  status must be 'published'
    source == 'ingest'               →  status in {approved, routed}
    anything else                    →  excluded (fail closed)

Always excluded by construction: 'pending-review', 'draft',
'rejected', 'archived'.

Why fail closed on unknown sources: a new source kind landing in the
schema (e.g. 'agent_synthesis') must be considered for shared-memory
inclusion as a deliberate decision, not picked up by accident through
a blacklist gap.
"""
from __future__ import annotations

from workgraph_persistence import KbItemRow

_USER_AUTHORED_SOURCES = frozenset({"manual", "upload", "llm"})
_USER_AUTHORED_OK_STATUSES = frozenset({"published"})
_INGEST_OK_STATUSES = frozenset({"approved", "routed"})


def is_canonical_kb_row(row: KbItemRow) -> bool:
    """Return True iff `row` is canonical shared memory and may be
    surfaced in retrieval / agent pretext / search results.

    Callers should NEVER short-circuit this check — every code path
    that reads `KbItemRow` for shared-context purposes goes through
    here so the whitelist is the single audit point.
    """
    source = row.source or "manual"
    status = row.status or ""
    if source == "ingest":
        return status in _INGEST_OK_STATUSES
    if source in _USER_AUTHORED_SOURCES:
        return status in _USER_AUTHORED_OK_STATUSES
    return False


__all__ = ["is_canonical_kb_row"]
