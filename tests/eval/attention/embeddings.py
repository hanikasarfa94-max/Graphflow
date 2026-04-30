"""SiliconFlow embeddings client for §7.2 vector retrieval (slice 2).

Uses Qwen/Qwen3-Embedding-8B via SiliconFlow's OpenAI-compatible API
(https://api.siliconflow.cn/v1). Multilingual model — handles the
zh+en bilingual corpus without a separate model per language.

Design:
  * Settings via pydantic-settings, mirrors the LLMSettings pattern in
    `workgraph_agents/llm.py`. Reads `.env` automatically.
  * Async batch client (uses the openai SDK against SiliconFlow's
    compatible endpoint — same shape as the DeepSeek wiring).
  * Disk-cached embeddings keyed by content hash. Re-runs over the
    same corpus skip the API call entirely; only new / changed items
    re-embed. Eval at 538 nodes is one-time work amortized across
    every subsequent slice (vector-only, vector+BM25, full hybrid).

The cache is a JSON map `{ content_hash: [float, ...] }`. JSON keeps
debuggability — production would graduate to a packed numpy array
plus an id index, but that optimization is for slice 5.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = logging.getLogger("workgraph.eval.embeddings")

# Conservative batch size — Qwen3-Embedding-8B accepts large batches,
# but smaller batches keep individual requests faster and tolerate the
# residential-network HTTP 408 issue noted in the project state. Tune
# upward if rate limits become the bottleneck instead of latency.
_BATCH_SIZE = 16
_MAX_RETRIES = 3
_TRANSIENT_ERRORS = (APIConnectionError, APITimeoutError, RateLimitError)


class EmbeddingsSettings(BaseSettings):
    """SiliconFlow / OpenAI-compatible embedding provider config.

    .env fields:
      SILICONFLOW_API_KEY=...
      SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
      SILICONFLOW_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
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


def load_embeddings_settings() -> EmbeddingsSettings:
    try:
        return EmbeddingsSettings()  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Embedding settings failed to load. Set SILICONFLOW_API_KEY in .env. "
            f"Underlying error: {exc}"
        ) from exc


def content_hash(text: str) -> str:
    """Stable cache key for a text string.

    SHA-1 is plenty for cache-key collision resistance; we're not
    hashing for security and the corpus is small.
    """
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


class EmbeddingsCache:
    """Disk-backed `{content_hash: vector}` cache.

    Loaded at construction, mutated in-memory by `set`, persisted by
    `save`. Caller decides when to save (typically once after embedding
    a batch) so we don't spam the filesystem.
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


class SiliconFlowEmbeddingClient:
    """Thin async wrapper over the SiliconFlow embeddings endpoint.

    Uses the openai SDK because the API is wire-compatible. Retries
    transient errors (connection / timeout / rate-limit) with the
    same simple backoff the agents-package LLMClient uses.
    """

    def __init__(self, settings: EmbeddingsSettings | None = None) -> None:
        self._settings = settings or load_embeddings_settings()
        self._client = AsyncOpenAI(
            api_key=self._settings.api_key,
            base_url=self._settings.base_url,
        )

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns vectors in input order.

        SiliconFlow accepts a list-of-strings and returns embeddings in
        order; the openai SDK exposes that as `response.data[i].embedding`.
        """
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
    client: SiliconFlowEmbeddingClient,
    *,
    batch_size: int = _BATCH_SIZE,
    save_every: int = 4,
) -> list[list[float]]:
    """Embed every text, hitting the cache first.

    Returns vectors in input order. Saves the cache periodically so a
    long-running embed (538 nodes ≈ 34 batches of 16) survives a
    crash mid-run.
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

    # All slots filled.
    return [v for v in out if v is not None]  # type: ignore[misc]


__all__ = [
    "EmbeddingsCache",
    "EmbeddingsSettings",
    "SiliconFlowEmbeddingClient",
    "content_hash",
    "embed_with_cache",
    "load_embeddings_settings",
]
