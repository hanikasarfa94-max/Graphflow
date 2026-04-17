from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_log = logging.getLogger("workgraph.agents.llm")

_TRANSIENT = (APIConnectionError, APITimeoutError, RateLimitError)
_MAX_RETRIES = 3


class LLMSettings(BaseSettings):
    """Provider-agnostic LLM config.

    DeepSeek is the current dev/test provider (OpenAI-compatible). Swap
    base_url + model to point at OpenAI, Anthropic via proxy, etc.
    """

    model_config = SettingsConfigDict(
        env_prefix="DEEPSEEK_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    api_key: str = Field(min_length=1)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"


def load_llm_settings() -> LLMSettings:
    try:
        return LLMSettings()
    except Exception as exc:
        raise RuntimeError(
            "LLM settings failed to load. Set DEEPSEEK_API_KEY in .env. "
            f"Underlying error: {exc}"
        ) from exc


@dataclass(slots=True)
class LLMResult:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class LLMClient:
    """Thin async client. Returns the raw completion string + token accounting.

    Structured-output helpers (`complete_json`) try JSON parse once, and on
    failure issue one strict-retry. That's the Phase 2.5 recovery; Phase 3
    upgrades to Instructor+Pydantic per decision 2C4.
    """

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self._settings = settings or load_llm_settings()
        self._client = AsyncOpenAI(
            api_key=self._settings.api_key,
            base_url=self._settings.base_url,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.1,
        response_format: dict | None = None,
    ) -> LLMResult:
        model = model or self._settings.model
        t0 = time.perf_counter()
        resp = await self._call_with_retry(
            model=model,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )
        latency = int((time.perf_counter() - t0) * 1000)
        usage = resp.usage
        return LLMResult(
            content=resp.choices[0].message.content or "",
            model=model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            latency_ms=latency,
        )

    async def _call_with_retry(self, **kwargs):
        """Retry transient network/rate-limit errors with exponential backoff.

        DeepSeek over residential networks occasionally drops connections;
        without retry the eval harness ends up noisier than the agent.
        """
        last: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                return await self._client.chat.completions.create(**kwargs)
            except _TRANSIENT as e:
                last = e
                if attempt == _MAX_RETRIES - 1:
                    break
                wait = 0.5 * (2 ** attempt)
                _log.warning(
                    "llm transient error; retrying",
                    extra={
                        "attempt": attempt + 1,
                        "max": _MAX_RETRIES,
                        "wait_s": wait,
                        "error": type(e).__name__,
                    },
                )
                await asyncio.sleep(wait)
        assert last is not None
        raise last

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> tuple[dict, LLMResult]:
        """Returns (parsed_dict, raw_result). Retries once on parse failure."""
        # First attempt with JSON mode.
        result = await self.complete(
            messages,
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(result.content), result
        except json.JSONDecodeError:
            _log.warning(
                "llm returned non-json; retry with strict instruction",
                extra={"len": len(result.content)},
            )

        retry_messages = [
            *messages,
            {"role": "assistant", "content": result.content},
            {
                "role": "user",
                "content": (
                    "Your previous response was not valid JSON. "
                    "Respond again with ONLY valid JSON. No markdown, no prose."
                ),
            },
        ]
        retry_result = await self.complete(
            retry_messages,
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        # Let this raise if the second attempt is still not JSON — caller decides.
        return json.loads(retry_result.content), retry_result


class SmokeResult(BaseModel):
    ok: bool
    message: str
    model: str
    latency_ms: int
