from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_observability import get_trace_id
from workgraph_persistence import EventRepository, session_scope

_log = logging.getLogger("workgraph.domain.events")

Subscriber = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """Write-through event bus backed by the `events` table, with
    optional in-process subscribers fired after the DB write.

    Phase 2: events land in the DB audit log; trace_id pulled from ContextVar.
    Phase 12 (1A): swap `emit` implementation to publish to Inngest.
    The emission shape (`name`, `trace_id`, `payload`) is stable across the swap.

    Subscribers (added Sprint 1c for drift auto-trigger): registered
    in-process handlers are fired via `asyncio.create_task` AFTER the
    DB write succeeds. Handlers must be async and must not raise — any
    exception is logged and swallowed so one bad subscriber cannot block
    other writes. Handler scheduling is fire-and-forget; callers never
    wait on it. When we move to Inngest the subscribe API stays; the
    implementation just points at the Inngest client instead of in-
    process tasks.
    """

    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker
        self._subscribers: dict[str, list[Subscriber]] = {}
        # Track every outstanding subscriber task so callers (primarily
        # tests) can drain them deterministically. Prod treats subscriber
        # scheduling as fire-and-forget; tests need a barrier to keep
        # cross-request state from bleeding across the shared aiosqlite
        # StaticPool connection. The set survives across emits — it is
        # pruned by the done-callback attached at scheduling time.
        self._tasks: set[asyncio.Task] = set()

    def subscribe(self, event_name: str, handler: Subscriber) -> None:
        """Register an async handler for events matching `event_name`.

        Event names are hierarchical (e.g., "decision.applied"); handlers
        match exact names only in v1. Wildcard/prefix matching is a v2
        concern.
        """
        self._subscribers.setdefault(event_name, []).append(handler)

    async def emit(self, name: str, payload: dict[str, Any]) -> None:
        trace_id = get_trace_id()
        async with session_scope(self._sessionmaker) as session:
            repo = EventRepository(session)
            await repo.append(name=name, trace_id=trace_id, payload=payload)

        handlers = self._subscribers.get(name, ())
        for handler in handlers:
            # Fire-and-forget; wrap so a bad handler doesn't break others.
            task = asyncio.create_task(self._safe_invoke(handler, name, payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Await all outstanding subscriber tasks.

        Test-only barrier. Production callers never wait on subscribers —
        they're fire-and-forget by design. Tests call this in teardown
        (and optionally between related requests) so subscriber
        transactions release the shared aiosqlite StaticPool connection
        before the next request's session_scope tries to commit.
        """
        # Snapshot first: done-callbacks mutate `_tasks` while we await.
        pending = list(self._tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()

    @staticmethod
    async def _safe_invoke(
        handler: Subscriber, name: str, payload: dict[str, Any]
    ) -> None:
        try:
            await handler(payload)
        except Exception:
            _log.exception("event bus subscriber failed", extra={"event": name})
