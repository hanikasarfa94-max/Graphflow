"""Deterministic helpers shared across membrane policies.

Pure functions with no DB / network side effects. Anything that needs
a row-set passes it in. Two responsibilities:

  * Title normalization for duplicate detection.
  * Conservative numeric-claim conflict scan (the dogfood-driven crowd
    KB pollution guard described in `membrane.py` pre-refactor).
  * Topic-token bag construction for LLM-pretext rank, plus a small
    overlap test reused by KB / task / decision policies.

Kept purposefully small — adding a smarter scorer here costs every
policy on import. Slice M2+ may swap `_topic_tokens` for the
RetrievalService primitive once it's lifted out of `_retrieval_primitives`.
"""
from __future__ import annotations

import re
from typing import Any

from workgraph_persistence import KbItemRow


_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_ASCII_TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]{1,}")
_CJK_RUN_RE = re.compile(r"[一-鿿]{2,}")

_TOPIC_STOP_TOKENS = {
    "note",
    "notes",
    "summary",
    "draft",
    "plan",
    "record",
    "wiki",
    "目标",
    "记录",
    "总结",
    "草稿",
    "方案",
}


def _normalize_title(title: str | None) -> str:
    """Normalize a KB title for duplicate detection.

    Lowercase, strip punctuation, collapse whitespace, drop common
    leading-article words. Two titles that pass this filter to the
    same value are treated as duplicates by the membrane.
    """
    if not title:
        return ""
    s = title.strip().lower()
    # Drop punctuation; keep word chars + Unicode letters (so "API 设计" stays
    # comparable to "API设计"). \W matches non-word; combined with the unicode
    # flag this preserves CJK + accented chars.
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _numeric_claims(text: str) -> set[str]:
    out: set[str] = set()
    for raw in _NUMBER_RE.findall(text or ""):
        try:
            n = float(raw)
        except ValueError:
            continue
        out.add(str(int(n)) if n.is_integer() else str(n))
    return out


def _topic_tokens(text: str) -> set[str]:
    s = (text or "").lower()
    tokens = {t for t in _ASCII_TOKEN_RE.findall(s) if t not in _TOPIC_STOP_TOKENS}
    for run in _CJK_RUN_RE.findall(s):
        # CJK bigrams keep this dependency-free while still catching
        # "关卡目标" / "Boss关" style topic overlap.
        for i in range(0, max(0, len(run) - 1)):
            tok = run[i : i + 2]
            if tok not in _TOPIC_STOP_TOKENS:
                tokens.add(tok)
    return tokens


def _topic_overlap(a: set[str], b: set[str]) -> bool:
    if not a or not b:
        return False
    common = a & b
    if len(common) >= 2:
        return True
    # Short titles can have only one meaningful shared token ("boss",
    # "关卡"). Require that token to be relatively specific by appearing
    # as a non-stop token on both sides.
    return len(common) == 1 and len(next(iter(common))) >= 3


def _iso_or_none(value: Any) -> str | None:
    """Best-effort ISO serialize for the agent pretext. Datetimes
    serialize via .isoformat(); None/strings pass through; anything
    else falls back to str()."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _first_numeric_fact_conflict(
    *,
    title: str,
    content: str,
    existing: list[KbItemRow],
) -> tuple[KbItemRow, set[str], set[str]] | None:
    """Conservative semantic guard for crowd KB pollution.

    This is intentionally not a full contradiction engine. It catches
    the high-value class the product just exposed in dogfood: two KB
    entries are about the same topic, both assert concrete numbers, and
    the number sets differ. Example: "5 levels + 2 bosses" vs
    "8 levels + 3 bosses". That should never auto-publish into shared
    LLM pretext; it should become owner review.
    """
    new_text = f"{title}\n{content}"
    new_numbers = _numeric_claims(new_text)
    if not new_numbers:
        return None
    new_tokens = _topic_tokens(new_text)
    if not new_tokens:
        return None

    for row in existing:
        if row.status in ("archived", "rejected"):
            continue
        old_text = f"{row.title or ''}\n{row.content_md or ''}"
        old_numbers = _numeric_claims(old_text)
        if not old_numbers or old_numbers == new_numbers:
            continue
        old_tokens = _topic_tokens(old_text)
        if _topic_overlap(new_tokens, old_tokens):
            return row, new_numbers, old_numbers
    return None


__all__ = [
    "_first_numeric_fact_conflict",
    "_iso_or_none",
    "_normalize_title",
    "_numeric_claims",
    "_topic_overlap",
    "_topic_tokens",
]
