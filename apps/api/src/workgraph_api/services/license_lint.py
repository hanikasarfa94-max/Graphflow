"""License-lint — Phase 1.A outbound reply scanner.

Scans an outbound reply body for cited node ids and flags any that fall
outside the recipient's license view. The caller (RoutingService reply
path) decides whether to ship, edit, deny, or bump to manual.

Phase 1.B will ship structured citations alongside reply bodies; until
then we text-scan. Patterns recognized:
  * `D#<digits>`         — decision shortcut (seeded by dissent agent)
  * `T#<digits>`         — task shortcut
  * `R#<digits>`, `G#<digits>`, `M#<digits>` — risk / goal / milestone
  * raw UUID fragments   — hex-32 with dashes; the slice's visible-id
    set is the authoritative allowlist, so false positives from unrelated
    UUIDs don't force a lint-pause (they just aren't in the slice either,
    hence they aren't cited-project-ids in the first place).

When 1.B lands, the caller should pass structured citations; this module
still works as a fallback for any path that hasn't migrated.
"""
from __future__ import annotations

import re
from typing import Any

from .license_context import LicenseContextService

# Pre-compiled ID scanners. Keep patterns permissive enough to handle the
# seeded formats without trying to parse the full citation grammar Phase
# 1.B will ship. `shortcut` captures Xnnn-style refs, `uuid` captures the
# UUID hex+dash format used as primary keys across the ORM.
_SHORTCUT_RE = re.compile(r"\b([DTRGM])#(\d+)\b")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def extract_node_ids(
    reply_body: str,
    *,
    explicit_citations: list[str] | None = None,
) -> list[str]:
    """Return the flat list of node ids referenced by the reply.

    `explicit_citations` wins when provided — that's the Phase 1.B
    structured path. Otherwise the function text-scans for shortcut
    refs + UUIDs.
    """
    if explicit_citations:
        return [c for c in explicit_citations if c]
    if not reply_body:
        return []
    ids: list[str] = []
    for match in _SHORTCUT_RE.finditer(reply_body):
        # Normalize to the original surface form so audit row
        # entries are human-searchable ("D#42" stays as "D#42").
        ids.append(f"{match.group(1)}#{match.group(2)}")
    for match in _UUID_RE.finditer(reply_body):
        ids.append(match.group(0))
    return ids


async def lint_reply(
    *,
    license_context_service: LicenseContextService,
    project_id: str,
    source_user_id: str,
    recipient_user_id: str,
    reply_body: str,
    explicit_citations: list[str] | None = None,
) -> dict[str, Any]:
    """Scan `reply_body` for cited node ids and report which fall outside
    recipient's license view.

    Return shape:
      {
        "referenced": list[str],      # all cited ids
        "out_of_view": list[str],     # subset outside recipient's slice
        "effective_tier": str,        # tighter of (source, recipient)
        "clean": bool,                # out_of_view is empty
      }
    """
    referenced = extract_node_ids(reply_body, explicit_citations=explicit_citations)
    # Build the recipient's slice and pull the flat visible-id set.
    slice_ = await license_context_service.build_slice(
        project_id=project_id,
        viewer_user_id=source_user_id,
        audience_user_id=recipient_user_id,
    )
    visible_ids = license_context_service.collect_visible_node_ids(slice_)
    # For shortcut refs (`D#42`) we can't match against UUID primary
    # keys — keep them as-is; the caller can inspect
    # `referenced` to decide whether shortcuts need their own
    # resolution step. For v1 we treat any shortcut that isn't
    # explicitly in the visible set as out-of-view.
    out_of_view = [r for r in referenced if r not in visible_ids]
    return {
        "referenced": referenced,
        "out_of_view": out_of_view,
        "effective_tier": slice_.get("license_tier") or "full",
        "clean": len(out_of_view) == 0,
    }


__all__ = ["extract_node_ids", "lint_reply"]
