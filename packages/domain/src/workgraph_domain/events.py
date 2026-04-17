from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_observability import get_trace_id
from workgraph_persistence import EventRepository, session_scope


class EventBus:
    """Write-through event bus backed by the `events` table.

    Phase 2: events land in the DB audit log; trace_id pulled from ContextVar.
    Phase 12 (1A): swap `emit` implementation to publish to Inngest.
    The emission shape (`name`, `trace_id`, `payload`) is stable across the swap.
    """

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    async def emit(self, name: str, payload: dict[str, Any]) -> None:
        trace_id = get_trace_id()
        async with session_scope(self._sessionmaker) as session:
            repo = EventRepository(session)
            await repo.append(name=name, trace_id=trace_id, payload=payload)
