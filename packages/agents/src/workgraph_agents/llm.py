from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, Field, ValidationError
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
    cache_read_tokens: int = 0


def _extract_cache_hit(usage) -> int:
    """Provider-agnostic cache-hit extraction.

    DeepSeek surfaces `prompt_cache_hit_tokens`; OpenAI nests it as
    `prompt_tokens_details.cached_tokens`. Anthropic (via proxy) uses
    `cache_read_input_tokens`. Return whichever is present, else 0.
    """
    if usage is None:
        return 0
    for attr in ("prompt_cache_hit_tokens", "cache_read_input_tokens"):
        v = getattr(usage, attr, None)
        if isinstance(v, int):
            return v
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        v = getattr(details, "cached_tokens", None)
        if isinstance(v, int):
            return v
    return 0


class ParseFailure(Exception):
    """Raised when structured extraction fails after max_attempts.

    Callers (agents) translate this into a `manual_review` outcome per 2C4.
    """

    def __init__(self, errors: list[str], last_result: LLMResult | None) -> None:
        self.errors = errors
        self.last_result = last_result
        super().__init__(
            f"structured parse failed after {len(errors)} attempts: "
            f"{errors[-1] if errors else 'unknown'}"
        )


class LLMClient:
    """Thin async client. Returns the raw completion string + token accounting.

    Structured-output helpers (`complete_json`) try JSON parse once, and on
    failure issue one strict-retry. `complete_structured` adds Pydantic
    validation with error-feedback reprompting per decision 2C4.
    """

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self._settings = settings or load_llm_settings()
        self._client = AsyncOpenAI(
            api_key=self._settings.api_key,
            base_url=self._settings.base_url,
        )

    @property
    def settings(self) -> LLMSettings:
        return self._settings

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
            cache_read_tokens=_extract_cache_hit(usage),
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


    async def complete_structured(
        self,
        messages: list[dict[str, str]],
        *,
        pydantic_cls: type[BaseModel],
        model: str | None = None,
        temperature: float = 0.1,
        max_attempts: int = 3,
    ) -> tuple[BaseModel, LLMResult, int]:
        """Structured extraction with error-feedback reprompting.

        Attempt 1: JSON mode with user's original messages.
        Attempt 2+: include the prior (invalid) assistant response +
          the JSON-decode or Pydantic-validation error so the model can
          self-correct. Temperature drops to 0.0 on retries.

        Returns (parsed_instance, final_result, attempts_taken).
        Raises ParseFailure after `max_attempts` unsuccessful attempts.
        """
        current_msgs = list(messages)
        last_result: LLMResult | None = None
        errors: list[str] = []

        for attempt in range(1, max_attempts + 1):
            temp = temperature if attempt == 1 else 0.0
            result = await self.complete(
                current_msgs,
                model=model,
                temperature=temp,
                response_format={"type": "json_object"},
            )
            last_result = result

            try:
                data = json.loads(result.content)
            except json.JSONDecodeError as e:
                err = f"invalid JSON: {e}"
                errors.append(err)
                _log.warning(
                    "structured parse: json error",
                    extra={"attempt": attempt, "error": err},
                )
                current_msgs = [
                    *current_msgs,
                    {"role": "assistant", "content": result.content},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response was not valid JSON ({e}). "
                            "Respond again with ONLY a valid JSON object. "
                            "No markdown, no prose, no code fences."
                        ),
                    },
                ]
                continue

            try:
                parsed = pydantic_cls.model_validate(data)
                return parsed, result, attempt
            except ValidationError as e:
                err = f"schema error: {e}"
                errors.append(err)
                _log.warning(
                    "structured parse: schema error",
                    extra={"attempt": attempt, "errors": e.errors()},
                )
                current_msgs = [
                    *current_msgs,
                    {"role": "assistant", "content": result.content},
                    {
                        "role": "user",
                        "content": (
                            "Your previous response was valid JSON but "
                            f"violated the schema:\n{e}\n"
                            "Respond again with ONLY a valid JSON object "
                            "that matches the schema exactly."
                        ),
                    },
                ]
                continue

        raise ParseFailure(errors, last_result)


class SmokeResult(BaseModel):
    ok: bool
    message: str
    model: str
    latency_ms: int
