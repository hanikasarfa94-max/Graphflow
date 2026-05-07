"""Sort-and-limit step of the projection pipeline.

The order is the wire-visible order — clients trust it and the FE's
flow panels render packets sequentially without re-sorting. Keeping
the rule in one tiny module makes it easy to find and easy to test.
"""
from __future__ import annotations

from typing import Any


def sort_and_limit(
    packets: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Sort by recency (updated_at, falling back to created_at) and
    truncate to `limit`.

    `updated_at` is set on every packet by every projector (handoff
    sets it to finalized_at, decision crystallized sets it to
    applied_at, etc.) so it's always populated. The `or` fallback
    only protects against future bugs in projector code.
    """
    packets.sort(
        key=lambda p: p["updated_at"] or p["created_at"], reverse=True
    )
    return packets[:limit]
