"""Shared author-hydration helper.

Five services (collab, room_timeline, personal, streams) each hand-rolled the
same per-author `UserRepository.get` loop to attach username/display_name to a
list of rows — a copy-pasted N+1. This batches it into one query.

See ARCHITECTURE-AUDIT-2026-05-30.md H5 / D2.
"""

from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession
from workgraph_persistence import UserRepository


async def hydrate_authors(
    session: AsyncSession,
    rows: Iterable[Any],
    *,
    id_attr: str = "author_id",
) -> tuple[dict[str, str], dict[str, str | None]]:
    """Fetch author username + display_name for `rows` in ONE query.

    Returns ``(usernames_by_id, display_names_by_id)`` — the same two dicts the
    call sites already key by author id, so downstream serialization is
    unchanged. Rows whose author no longer exists are simply absent from both
    dicts (callers use ``.get(...)``).
    """
    ids = [getattr(r, id_attr) for r in rows]
    by_id = {u.id: u for u in await UserRepository(session).get_many(ids)}
    return (
        {uid: u.username for uid, u in by_id.items()},
        {uid: u.display_name for uid, u in by_id.items()},
    )
