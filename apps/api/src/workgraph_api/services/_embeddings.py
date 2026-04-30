"""SiliconFlow embeddings client + disk cache for §7.2 vector retrieval.

Production version of `tests/eval/attention/embeddings.py`. Same shape:
SiliconFlow OpenAI-compatible API + JSON content-hash cache. Differs
only in:

  * Lives under `apps/api/services/` so the API package can import
    cleanly.
  * Defaults the cache path to `data/embeddings/kb_items.json` (the
    other prod data directory).
  * Defines an `EmbeddingClient` Protocol so tests can pass a stub
    that returns deterministic vectors without hitting SiliconFlow.

The eval module duplicates this code (over a different cache path and
sized for slice-2 corpora). DRY violation acknowledged; refactor to a
shared package waits until slice 5c when there's a third consumer.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = logging.getLogger("workgraph.api.embeddings")

# Conservative batch size — Qwen3-Embedding-8B accepts large batches but
# smaller batches keep per-request latency bounded and tolerate the
# residential-network HTTP 408 issue documented in the project state.
_BATCH_SIZE = 16
_MAX_RETRIES = 3
_TRANSIENT_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError)


class EmbeddingsSettings(BaseSettings):
    """SiliconFlow / OpenAI-compatible embedding provider config.

    Reads SILICONFLOW_API_KEY / _BASE_URL / _EMBEDDING_MODEL from .env.
    Same env-prefix convention as the eval scaffold so a single .env
    serves both.
    """

    model_config = SettingsConfigDict(
        env_prefix="SILICONFLOW_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: str = Field(min_length=1)
    base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "Qwen/Qwen3-Embedding-8B"


def load_embeddings_settings() -> EmbeddingsSettings | None:
    """Load settings if SILICONFLOW_API_KEY is configured, else None.

    Returning None lets the caller decide whether to disable vector
    retrieval gracefully (no key configured = BM25-only, no error)
    rather than blowing up at startup.
    """
    try:
        return EmbeddingsSettings()  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001
        _log.info(
            "embedding settings unavailable (%s); vector retrieval disabled",
            exc,
        )
        return None


def content_hash(text: str) -> str:
    """Stable cache key for a text string. SHA-1 is plenty here."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class EmbeddingsCache:
    """Disk-backed `{content_hash: vector}` cache.

    Loaded at construction, mutated in-memory by `set`, persisted by
    `save`. Caller decides when to save so we don't hammer the
    filesystem on every embedding.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, list[float]] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(self._data, dict):
                    self._data = {}
            except (json.JSONDecodeError, OSError):
                _log.warning(
                    "embeddings cache at %s unreadable; starting fresh", path
                )
                self._data = {}

    def get(self, key: str) -> list[float] | None:
        return self._data.get(key)

    def set(self, key: str, vec: list[float]) -> None:
        self._data[key] = vec

    def has(self, key: str) -> bool:
        return key in self._data

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Two-phase write so a crash mid-save can't truncate the cache.
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(self._path)

    @property
    def size(self) -> int:
        return len(self._data)


@runtime_checkable
class EmbeddingClient(Protocol):
    """Minimal embedding-provider shape.

    Production wires SiliconFlowEmbeddingClient; tests pass a stub
    that returns deterministic vectors (e.g. hash of content) so no
    network calls happen.
    """

    async def embed_batch(
        self, texts: Sequence[str]
    ) -> list[list[float]]: ...


class SiliconFlowEmbeddingClient:
    """Async wrapper over the SiliconFlow embeddings endpoint.

    Uses the openai SDK because the API is wire-compatible. Retries
    transient errors with the same simple backoff the agents-package
    LLMClient uses.
    """

    def __init__(self, settings: EmbeddingsSettings | None = None) -> None:
        self._settings = settings or load_embeddings_settings()
        if self._settings is None:
            raise RuntimeError(
                "SiliconFlowEmbeddingClient requires SILICONFLOW_API_KEY in .env"
            )
        self._client = AsyncOpenAI(
            api_key=self._settings.api_key,
            base_url=self._settings.base_url,
        )

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await self._client.embeddings.create(
                    model=self._settings.embedding_model,
                    input=list(texts),
                )
                return [list(d.embedding) for d in resp.data]
            except _TRANSIENT_ERRORS as exc:
                last_exc = exc
                wait = 2 ** attempt
                _log.warning(
                    "embed_batch transient error (attempt %d/%d): %s — sleeping %ds",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
        raise RuntimeError(
            f"embed_batch failed after {_MAX_RETRIES} attempts: {last_exc}"
        )


async def embed_with_cache(
    texts: Iterable[str],
    cache: EmbeddingsCache,
    client: EmbeddingClient,
    *,
    batch_size: int = _BATCH_SIZE,
    save_every: int = 4,
) -> list[list[float]]:
    """Embed every text, hitting the cache first.

    Returns vectors in input order. Saves the cache periodically so a
    crash mid-run preserves partial progress.
    """
    text_list = list(texts)
    out: list[list[float] | None] = [None] * len(text_list)
    misses: list[tuple[int, str, str]] = []  # (out_idx, key, text)

    for i, text in enumerate(text_list):
        key = content_hash(text)
        cached = cache.get(key)
        if cached is not None:
            out[i] = cached
        else:
            misses.append((i, key, text))

    if not misses:
        return out  # type: ignore[return-value]

    _log.info(
        "embed_with_cache: %d/%d hit cache, embedding %d new",
        len(text_list) - len(misses),
        len(text_list),
        len(misses),
    )
    batches_done = 0
    for batch_start in range(0, len(misses), batch_size):
        batch = misses[batch_start : batch_start + batch_size]
        vectors = await client.embed_batch([t for _i, _k, t in batch])
        for (out_idx, key, _text), vec in zip(batch, vectors):
            cache.set(key, vec)
            out[out_idx] = vec
        batches_done += 1
        if batches_done % save_every == 0:
            cache.save()
    cache.save()

    return [v for v in out if v is not None]  # type: ignore[misc]


__all__ = [
    "EmbeddingClient",
    "EmbeddingsCache",
    "EmbeddingsSettings",
    "SiliconFlowEmbeddingClient",
    "content_hash",
    "embed_with_cache",
    "load_embeddings_settings",
]
