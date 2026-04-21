"""Shared citation primitives — Phase 1.B (PLAN-v3).

Every user-visible claim from an edge-LLM agent carries structured
citations pointing at the graph / KB nodes that back it. This module
defines the wire format:

  Citation  — one reference, { node_id, kind }
  CitedClaim — { text, citations[] }; empty `citations` marks the claim
               as uncited (rendered visually weaker on the frontend,
               never hidden).

Valid `kind` values track the graph + KB taxonomy:
  decision | task | risk | deliverable | goal | milestone | commitment
  wiki_page | kb  (kb covers membrane-signal ingested KB items)

Tolerance: if the model returns plain `body: str` without structured
claims, callers should wrap the body with `wrap_uncited(body)` so
downstream renderers always see the same shape and the UI can mark
the turn `uncited: true`. This keeps existing stubs / legacy replies
working without a migration.
"""
from __future__ import annotations

from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

CitationKind = Literal[
    "decision",
    "task",
    "risk",
    "deliverable",
    "goal",
    "milestone",
    "commitment",
    "wiki_page",
    "kb",
]


class Citation(BaseModel):
    """One citation chip on a claim. `node_id` is the graph / KB id."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=200)
    kind: CitationKind


class CitedClaim(BaseModel):
    """One substantive claim + the citations that back it.

    An empty `citations` list marks the claim as uncited — the UI
    renders it in a muted color but still shows the text.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    citations: list[Citation] = Field(default_factory=list, max_length=12)


def wrap_uncited(body: str | None) -> list[CitedClaim]:
    """Wrap a plain string body into a single uncited claim.

    Returns `[]` when body is empty / None so the caller can treat
    "no claims" and "silence" identically downstream.
    """
    if not body:
        return []
    return [CitedClaim(text=body, citations=[])]


def claims_payload(claims: Iterable[CitedClaim]) -> list[dict]:
    """Serialize claims for persistence / WS payloads."""
    return [c.model_dump(mode="json") for c in claims]


def is_uncited(claims: Iterable[CitedClaim]) -> bool:
    """True iff every claim carries an empty `citations` list.

    Used by services to tag a reply `uncited: true` so the frontend
    can render the whole turn muted without walking the list again.
    """
    any_claim = False
    for c in claims:
        any_claim = True
        if c.citations:
            return False
    return any_claim  # empty iterable → False (nothing to call uncited)


__all__ = [
    "Citation",
    "CitationKind",
    "CitedClaim",
    "wrap_uncited",
    "claims_payload",
    "is_uncited",
]
