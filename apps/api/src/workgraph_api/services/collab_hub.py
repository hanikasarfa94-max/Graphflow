"""In-process + optional Redis pub/sub fanout for WebSocket broadcasts.

Phase 7'' scope: every state change (assignment / comment / message /
im_suggestion / notification / graph / plan) fan-outs to all connected
clients of the affected project. We keep a local asyncio broadcaster for
tests and single-node dev, and an optional Redis backend for multi-node
deploys.

The hub intentionally does not know about HTTP — callers pass raw payload
dicts; the WebSocket router is responsible for JSON encoding.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any, AsyncIterator

_log = logging.getLogger("workgraph.api.collab_hub")


class CollabHub:
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._redis = None  # lazily imported
        self._redis_pubsub_task: asyncio.Task | None = None
        # project_id -> set of asyncio.Queue[dict]
        self._local_queues: dict[str, set[asyncio.Queue]] = defaultdict(set)
        # (user_id, project_id) -> deque[float] of message timestamps for rate-limit
        self._msg_timestamps: dict[tuple[str, str], deque[float]] = defaultdict(
            lambda: deque(maxlen=32)
        )
        self._started = False

    @property
    def redis_enabled(self) -> bool:
        return self._redis_url is not None

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        if self._redis_url is None:
            return
        try:
            import redis.asyncio as aioredis  # type: ignore

            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            pubsub = self._redis.pubsub()
            await pubsub.psubscribe("wg:project:*")
            self._redis_pubsub_task = asyncio.create_task(
                self._consume_redis(pubsub), name="collab-redis-consumer"
            )
            _log.info("collab hub redis backend enabled")
        except Exception as exc:  # pragma: no cover — logged, not fatal
            _log.warning(
                "collab hub redis backend disabled", extra={"error": str(exc)}
            )
            self._redis = None

    async def stop(self) -> None:
        if self._redis_pubsub_task is not None:
            self._redis_pubsub_task.cancel()
            try:
                await self._redis_pubsub_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass

    async def _consume_redis(self, pubsub) -> None:
        try:
            async for message in pubsub.listen():
                if message is None or message.get("type") not in {"pmessage", "message"}:
                    continue
                channel = message.get("channel", "")
                data = message.get("data", "")
                try:
                    project_id = channel.split(":", 2)[2]
                except IndexError:
                    continue
                try:
                    payload = json.loads(data)
                except Exception:
                    continue
                self._fanout_local(project_id, payload)
        except asyncio.CancelledError:
            return

    def _fanout_local(self, project_id: str, payload: dict) -> None:
        queues = self._local_queues.get(project_id)
        if not queues:
            return
        for q in tuple(queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                _log.warning(
                    "collab hub local queue full — dropping", extra={"project_id": project_id}
                )

    async def publish(self, project_id: str, payload: dict[str, Any]) -> None:
        """Broadcast `payload` to every subscriber of `project_id`.

        When Redis is enabled the message also goes through pub/sub so other
        process replicas can fan out to their local subscribers.
        """
        self._fanout_local(project_id, payload)
        if self._redis is not None:
            try:
                await self._redis.publish(
                    f"wg:project:{project_id}", json.dumps(payload, default=str)
                )
            except Exception as exc:
                _log.warning(
                    "collab hub redis publish failed", extra={"error": str(exc)}
                )

    async def subscribe(
        self, project_id: str
    ) -> AsyncIterator[asyncio.Queue]:
        """Async context manager-style subscription: caller must `unsubscribe`."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._local_queues[project_id].add(queue)
        return queue  # type: ignore[return-value]

    def unsubscribe(self, project_id: str, queue: asyncio.Queue) -> None:
        self._local_queues[project_id].discard(queue)
        if not self._local_queues[project_id]:
            self._local_queues.pop(project_id, None)

    def rate_limit_ok(self, user_id: str, project_id: str, limit_per_sec: int = 10) -> bool:
        """Sliding-window rate check. Returns False when the user exceeded the limit."""
        now = time.monotonic()
        key = (user_id, project_id)
        bucket = self._msg_timestamps[key]
        while bucket and bucket[0] < now - 1.0:
            bucket.popleft()
        if len(bucket) >= limit_per_sec:
            return False
        bucket.append(now)
        return True

    def subscriber_count(self, project_id: str) -> int:
        return len(self._local_queues.get(project_id, ()))

    def project_ids_with_subscribers(self) -> list[str]:
        return [pid for pid, qs in self._local_queues.items() if qs]
