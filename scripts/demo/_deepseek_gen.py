"""DeepSeek-backed prose generator for demo seed scripts.

Read DEEPSEEK_API_KEY + DEEPSEEK_BASE_URL from .env, expose a tiny
`gen(system, user)` -> str helper. Caches per-prompt to a JSON sidecar
so re-running the seed-content generator never re-hits the API for
already-produced content.

Per `feedback_use_deepseek_for_mocks.md`: generate, but review the
output before writing it to a real seed script. This module is the
generator only — the seed scripts call gen() and the human picks/edits.

Usage:
    from _deepseek_gen import gen
    text = gen(
        system="You are a Chinese product-team chat seed generator.",
        user="Write a single Slack-style message from a QA lead...",
        max_tokens=120,
    )

Reads from project-root .env. Cache file at:
    scripts/demo/_deepseek_cache.json
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = Path(__file__).resolve().parent / "_deepseek_cache.json"


def _load_env() -> dict[str, str]:
    """Load .env at repo root. Trim CRLF. No external deps."""
    env: dict[str, str] = {}
    p = ROOT / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _key(system: str, user: str, model: str, temp: float) -> str:
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"\x00")
    h.update(f"{temp:.4f}".encode("utf-8"))
    h.update(b"\x00")
    h.update(system.encode("utf-8"))
    h.update(b"\x00")
    h.update(user.encode("utf-8"))
    return h.hexdigest()[:16]


def gen(
    system: str,
    user: str,
    *,
    model: str = "deepseek-chat",
    max_tokens: int = 200,
    temperature: float = 0.7,
    use_cache: bool = True,
) -> str:
    """Call DeepSeek chat completions, return the assistant text.

    Caches by (system, user, model, temperature). Re-running with the
    same inputs returns the cached output.
    """
    cache = _load_cache() if use_cache else {}
    ck = _key(system, user, model, temperature)
    if use_cache and ck in cache:
        return cache[ck]

    env = _load_env()
    api_key = env.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    base = (
        env.get("DEEPSEEK_BASE_URL")
        or os.environ.get("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com"
    )
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY missing in .env")

    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = Request(
        f"{base.rstrip('/')}/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            text = payload["choices"][0]["message"]["content"].strip()
            if use_cache:
                cache[ck] = text
                _save_cache(cache)
            return text
        except HTTPError as e:
            last_err = e
            err_body = e.read().decode("utf-8", errors="replace")[:400]
            sys.stderr.write(
                f"[deepseek] HTTP {e.code} attempt {attempt + 1}: {err_body}\n"
            )
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except URLError as e:
            last_err = e
            sys.stderr.write(f"[deepseek] URLError attempt {attempt + 1}: {e}\n")
            time.sleep(2 * (attempt + 1))
    assert last_err is not None
    raise last_err


if __name__ == "__main__":
    # Smoke test
    out = gen(
        system="You answer in one short Chinese sentence.",
        user="用一句话确认你已就绪。",
        max_tokens=40,
        use_cache=False,
    )
    print(out)
