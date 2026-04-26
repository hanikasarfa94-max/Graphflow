"""KbItemService — Phase V manual-write KB primitive (+ file upload).

Solves the QA finding "no way to write a doc, only paste URLs."
KbItemRow is a first-class user-authored note, distinct from the
membrane-ingested signals. The wiki UI will list both.

Scope contract:
  * personal — owner_user_id only. LLM never reads for other users.
  * group    — every project member can read; affects shared pretext.

Permission model (v0):
  * Create:    any project member; default scope=personal.
  * Read list: project members get personal-they-own + all-group.
  * Update:    owner of the item OR project owner (for group-scope
               cleanups). Personal stays editable by owner only.
  * Delete:    owner OR project owner.
  * Promote (personal → group): owner asks; project owner accepts.
    Bare owner-promotes-self is allowed in v0 — frontend can confirm
    "this will affect everyone's pretext" before the call. Phase V.2
    inserts the membrane review step.
  * Demote (group → personal): project owner only.

Phase B file upload:
  * Multipart upload → KbItemRow with source='upload'. Bytes saved to
    `<KB_UPLOADS_ROOT>/<item_id>/<filename>`. Text-ish files (≤32KB
    plain text) get inlined into content_md too so the LLM can read
    them directly; binary files leave content_md as a stub pointing
    to the download endpoint.
  * Cap at 5MB per upload (enforced server-side).
  * Download endpoint streams the file with the same scope/auth gate
    as item read.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    EDGE_AGENT_SYSTEM_USER_ID,
    IMSuggestionRepository,
    KbItemRepository,
    KbItemRow,
    MessageRepository,
    ProjectMemberRepository,
    StreamRepository,
    session_scope,
)


# Disk layout for attachments. Default lands inside the same /data
# volume the SQLite DB lives on, so the nightly backup script picks
# them up automatically. Override via env for non-Docker dev runs.
KB_UPLOADS_ROOT = Path(
    os.environ.get("WORKGRAPH_KB_UPLOADS_ROOT", "/data/kb-uploads")
)

# 5 MB hard cap on a single upload. Larger files should land in a
# real blob store (v3 — S3 / OSS) — this is a v1 sanity bound.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# Mime types we treat as "inline-able" — read into content_md so the
# LLM can use them directly. Anything else stays a binary attachment
# with a stub content_md.
_INLINE_MIME_PREFIXES = (
    "text/",
    "application/json",
    "application/yaml",
    "application/x-yaml",
)
_INLINE_MAX_BYTES = 32 * 1024  # don't inline beyond 32KB even if text

_log = logging.getLogger("workgraph.api.kb_items")

VALID_SCOPES = frozenset({"personal", "group"})
# Two status vocabularies share this column since the fold (migration
# 0022): user-authored items use draft/published/archived; ingested
# rows (source='ingest') use the membrane lifecycle. Both are valid;
# enforcement of "only legal transitions for this row's source" lives
# in the per-source service path, not here.
VALID_STATUSES = frozenset(
    {
        "draft",
        "published",
        "archived",
        "pending-review",
        "approved",
        "rejected",
        "routed",
    }
)
# 'ingest' (added 0022/F2): externally-pulled signals through the
# membrane pipeline. source_kind discriminates the sub-type
# (git-commit / rss / user-drop / webhook / etc.).
VALID_SOURCES = frozenset({"manual", "upload", "llm", "ingest"})

_MAX_CONTENT_BYTES = 64 * 1024  # 64KB; larger needs blob-store v2.


class KbItemError(Exception):
    """Service-layer error with machine-readable code + optional HTTP
    status hint. Router maps `code` → status via a small table; the
    optional `status_` arg lets callers override for callers that need
    a non-default mapping (e.g. forbidden vs not-found ambiguity)."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        status_: int | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.status = status_


class KbItemService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker
        # Optional — late-bound from main.py once MembraneService is
        # constructed (needs stream_service which is built later).
        # When set, group-scope writes pass through MembraneService.review()
        # before persisting. None falls through to direct write (legacy
        # path for tests + the period before late-binding completes).
        self._membrane_service = None

    def attach_membrane(self, membrane_service: Any) -> None:
        """Late-bind the MembraneService dependency.

        See docs/membrane-reorg.md stage 2: every group-scope KB write
        is a candidate trying to enter the cell. The membrane gets the
        last word before persistence. Personal-scope writes are forks
        and skip review entirely.
        """
        self._membrane_service = membrane_service

    async def create(
        self,
        *,
        project_id: str,
        owner_user_id: str,
        title: str,
        content_md: str = "",
        scope: str = "personal",
        folder_id: str | None = None,
        source: str = "manual",
        status: str = "published",
    ) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise KbItemError("invalid_title", "title required")
        if len(title) > 500:
            title = title[:500]
        content_md = content_md or ""
        if len(content_md.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise KbItemError("content_too_large", "content > 64KB")
        if scope not in VALID_SCOPES:
            raise KbItemError("invalid_scope")
        if status not in VALID_STATUSES:
            raise KbItemError("invalid_status")
        if source not in VALID_SOURCES:
            raise KbItemError("invalid_source")

        # Membrane review for group-scope writes (stage 2 — passthrough
        # for now, but the call site is in place for stage 3+ to add
        # conflict detection / review queueing without touching every
        # caller).
        review = None
        if scope == "group" and self._membrane_service is not None:
            from .membrane import MembraneCandidate

            review = await self._membrane_service.review(
                MembraneCandidate(
                    kind="kb_item_group",
                    project_id=project_id,
                    proposer_user_id=owner_user_id,
                    title=title,
                    content=content_md,
                    metadata={"source": source, "status": status},
                )
            )
            if review.action == "reject":
                raise KbItemError(
                    "membrane_rejected",
                    review.reason or "rejected by membrane",
                    status_=409,
                )
            if review.action in ("request_review", "request_clarification"):
                # Downgrade to draft. The full inbox enqueue happens
                # below after the row is persisted (we need its id).
                status = "draft"

        async with session_scope(self._sessionmaker) as session:
            if not await ProjectMemberRepository(session).is_member(
                project_id, owner_user_id
            ):
                raise KbItemError("not_a_member", status_=403)
            row = await KbItemRepository(session).create(
                project_id=project_id,
                owner_user_id=owner_user_id,
                title=title,
                content_md=content_md,
                scope=scope,
                folder_id=folder_id,
                source=source,
                status=status,
            )
            item_payload = _serialize(row)
            kb_item_id = row.id

            # Stage 4: when membrane staged this as a draft, also
            # create an IMSuggestion(kind='membrane_review') in the
            # team-room inbox so an owner can one-click approve. The
            # suggestion needs a message to anchor; post a system
            # message authored by the edge agent that names the
            # candidate + the reason for review.
            if (
                review is not None
                and review.action == "request_review"
                and scope == "group"
            ):
                team_stream = await StreamRepository(session).get_for_project(
                    project_id
                )
                if team_stream is not None:
                    body = (
                        f"📥 Membrane staged a group KB entry for review: "
                        f"'{title}'. Reason: {review.reason}."
                    )
                    if review.diff_summary:
                        body = f"{body}\n{review.diff_summary}"
                    msg = await MessageRepository(session).append(
                        project_id=project_id,
                        author_id=EDGE_AGENT_SYSTEM_USER_ID,
                        body=body,
                        stream_id=team_stream.id,
                        kind="membrane-review",
                        linked_id=kb_item_id,
                    )
                    await IMSuggestionRepository(session).append(
                        project_id=project_id,
                        message_id=msg.id,
                        kind="membrane_review",
                        confidence=1.0,
                        targets=list(review.conflict_with),
                        proposal={
                            "action": "approve_membrane_candidate",
                            "summary": (
                                review.diff_summary
                                or f"Approve '{title}' for the group wiki"
                            ),
                            "detail": {
                                "candidate_kind": "kb_item_group",
                                "kb_item_id": kb_item_id,
                                "diff_summary": review.diff_summary,
                                "conflict_with": list(review.conflict_with),
                            },
                        },
                        reasoning=review.reason or "membrane request_review",
                        prompt_version=None,
                        outcome="ok",
                        attempts=1,
                    )
            return item_payload

    async def list_visible(
        self, *, project_id: str, viewer_user_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            if not await ProjectMemberRepository(session).is_member(
                project_id, viewer_user_id
            ):
                raise KbItemError("not_a_member", status_=403)
            rows = await KbItemRepository(session).list_visible_for_user(
                project_id=project_id,
                viewer_user_id=viewer_user_id,
                limit=limit,
            )
            return [_serialize(r) for r in rows]

    async def get(
        self, *, item_id: str, viewer_user_id: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            await self._assert_can_read(session, row, viewer_user_id)
            return _serialize(row)

    async def update(
        self,
        *,
        item_id: str,
        actor_user_id: str,
        title: str | None = None,
        content_md: str | None = None,
        status: str | None = None,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        if status is not None and status not in VALID_STATUSES:
            raise KbItemError("invalid_status")
        if content_md is not None and len(content_md.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise KbItemError("content_too_large")
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            await self._assert_can_edit(session, row, actor_user_id)
            updated = await KbItemRepository(session).update(
                item_id=item_id,
                title=title,
                content_md=content_md,
                status=status,
                folder_id=folder_id,
            )
            return _serialize(updated)

    async def delete(
        self, *, item_id: str, actor_user_id: str
    ) -> dict[str, Any]:
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            await self._assert_can_edit(session, row, actor_user_id)
            had_attachment = bool(row.attachment_filename)
            await KbItemRepository(session).delete(item_id)
        # Clean up the attachment dir on disk after the row is gone.
        # Best-effort — if we crash here the orphaned file is harmless
        # (the FK cascade prevents the row from being recreated with
        # the same id), and a future cleanup sweep can reap it.
        if had_attachment:
            attachment_dir = KB_UPLOADS_ROOT / item_id
            if attachment_dir.exists():
                try:
                    shutil.rmtree(attachment_dir)
                except OSError:
                    _log.warning(
                        "kb delete: orphan attachment dir",
                        extra={"item_id": item_id},
                    )
        return {"ok": True, "deleted_id": item_id}

    async def promote_to_group(
        self, *, item_id: str, actor_user_id: str
    ) -> dict[str, Any]:
        """Personal → group. Owner-self-promote and project-owner
        promote both go through MembraneService.review() so a personal
        note moving into the cell gets the same duplicate-detection /
        request-review treatment as a direct group write.
        """
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            if row.scope == "group":
                return _serialize(row)
            is_owner_of_item = row.owner_user_id == actor_user_id
            is_project_owner = await _is_project_owner(
                session, row.project_id, actor_user_id
            )
            if not (is_owner_of_item or is_project_owner):
                raise KbItemError("forbidden", status_=403)
            project_id = row.project_id
            title = row.title
            content_md = row.content_md or ""

        # Membrane review — personal → group is a "join the cell"
        # gesture; same gate as direct group writes (stage 2/3 of
        # docs/membrane-reorg.md). Skip when no membrane attached
        # (legacy boot path / tests without late-binding).
        target_status = "published"
        if self._membrane_service is not None:
            from .membrane import MembraneCandidate

            review = await self._membrane_service.review(
                MembraneCandidate(
                    kind="kb_item_group",
                    project_id=project_id,
                    proposer_user_id=actor_user_id,
                    title=title,
                    content=content_md,
                    metadata={"source": "promote", "from_item_id": item_id},
                )
            )
            if review.action == "reject":
                raise KbItemError(
                    "membrane_rejected",
                    review.reason or "rejected by membrane",
                    status_=409,
                )
            if review.action in ("request_review", "request_clarification"):
                # Promote completes (scope flips) but lands as draft so
                # canonical group context isn't polluted until owner
                # approves the staged review. Symmetric with direct
                # group writes.
                target_status = "draft"

        async with session_scope(self._sessionmaker) as session:
            updated = await KbItemRepository(session).set_scope(
                item_id=item_id, scope="group"
            )
            if target_status == "draft":
                updated = await KbItemRepository(session).update(
                    item_id=item_id, status="draft"
                )
            return _serialize(updated)

    async def upload(
        self,
        *,
        project_id: str,
        owner_user_id: str,
        filename: str,
        data: bytes,
        title: str | None = None,
        scope: str = "personal",
        folder_id: str | None = None,
        client_mime: str | None = None,
    ) -> dict[str, Any]:
        """Multipart upload entry. Creates a KbItemRow with
        source='upload', persists bytes to disk, optionally inlines
        text content into content_md.

        Caller is responsible for already enforcing MAX_UPLOAD_BYTES
        on the multipart parser side; we double-check here anyway.

        `client_mime` is what the browser claimed in the multipart
        Content-Type header. We trust it if non-empty + non-default
        (the spec's `application/octet-stream` fallback) — it's better
        than `mimetypes.guess_type` for cases stdlib doesn't know
        (.md, .yaml, etc.).
        """
        if not filename:
            raise KbItemError("invalid_filename", "filename required")
        size = len(data)
        if size == 0:
            raise KbItemError("empty_file")
        if size > MAX_UPLOAD_BYTES:
            raise KbItemError("file_too_large")
        if scope not in VALID_SCOPES:
            raise KbItemError("invalid_scope")

        safe_name = _sanitize_filename(filename)
        # Prefer client-supplied MIME (browser usually has it right);
        # fall back to extension sniffing; final fallback to octet-stream.
        if client_mime and client_mime != "application/octet-stream":
            mime = client_mime
        else:
            mime, _ = mimetypes.guess_type(safe_name)
            mime = mime or "application/octet-stream"
        # Best-effort .md → text/markdown for the stdlib gap that bit
        # us in tests on certain Python builds.
        if mime == "application/octet-stream" and safe_name.lower().endswith(".md"):
            mime = "text/markdown"

        # Inline text-ish content into content_md so the LLM can read
        # it. Binary files get a stub pointing at the download endpoint.
        is_text = mime.startswith(_INLINE_MIME_PREFIXES)
        if is_text and size <= _INLINE_MAX_BYTES:
            try:
                inlined = data.decode("utf-8")
            except UnicodeDecodeError:
                # Mime claimed text but the bytes aren't UTF-8. Fall
                # back to attachment-only.
                inlined = None
        else:
            inlined = None

        if inlined is not None:
            content_md = inlined
        else:
            human_size = _format_bytes(size)
            content_md = (
                f"📎 **{safe_name}** ({human_size}, {mime})\n\n"
                f"_Binary attachment — fetch via the download link._"
            )

        display_title = (title or safe_name).strip()[:500] or safe_name

        async with session_scope(self._sessionmaker) as session:
            if not await ProjectMemberRepository(session).is_member(
                project_id, owner_user_id
            ):
                raise KbItemError("not_a_member", status_=403)
            row = await KbItemRepository(session).create(
                project_id=project_id,
                owner_user_id=owner_user_id,
                title=display_title,
                content_md=content_md,
                scope=scope,
                folder_id=folder_id,
                source="upload",
                status="published",
            )
            # Persist attachment metadata + bytes only after the row
            # exists, so a write failure leaves no orphan KbItemRow with
            # missing bytes.
            row.attachment_filename = safe_name
            row.attachment_mime = mime
            row.attachment_bytes = size
            await session.flush()
            item_id = row.id
            payload = _serialize(row)

        # Bytes-to-disk happens AFTER the DB commit so a transient FS
        # failure doesn't leave a dangling row claiming to have an
        # attachment. If the disk write fails post-commit we delete
        # the row so future reads don't 404 on the file.
        try:
            target = _attachment_path(item_id, safe_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError:
            _log.exception(
                "kb upload disk write failed; rolling back row",
                extra={"item_id": item_id, "filename": safe_name},
            )
            async with session_scope(self._sessionmaker) as session:
                await KbItemRepository(session).delete(item_id)
            raise KbItemError("storage_failed")

        return payload

    async def get_attachment(
        self, *, item_id: str, viewer_user_id: str
    ) -> tuple[Path, str, str, int]:
        """Returns (path-on-disk, filename, mime, bytes). Caller streams
        the file. Same scope/auth gate as item read."""
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            await self._assert_can_read(session, row, viewer_user_id)
            if not row.attachment_filename:
                raise KbItemError("no_attachment", status_=404)
            path = _attachment_path(row.id, row.attachment_filename)
        if not path.exists():
            # DB says yes, disk says no — return a clear error rather
            # than a generic 404 so we can spot and fix.
            raise KbItemError("attachment_missing", status_=410)
        return (
            path,
            row.attachment_filename,
            row.attachment_mime or "application/octet-stream",
            row.attachment_bytes or path.stat().st_size,
        )

    async def demote_to_personal(
        self, *, item_id: str, actor_user_id: str
    ) -> dict[str, Any]:
        """Group → personal. Project owner only — protects shared
        pretext from accidental loss when the original author leaves."""
        async with session_scope(self._sessionmaker) as session:
            row = await KbItemRepository(session).get(item_id)
            if row is None:
                raise KbItemError("not_found", status_=404)
            if row.scope == "personal":
                return _serialize(row)
            if not await _is_project_owner(
                session, row.project_id, actor_user_id
            ):
                raise KbItemError("forbidden", status_=403)
            updated = await KbItemRepository(session).set_scope(
                item_id=item_id, scope="personal"
            )
            return _serialize(updated)

    # ---- internals -----------------------------------------------------

    async def _assert_can_read(
        self, session, row: KbItemRow, viewer_user_id: str
    ) -> None:
        if not await ProjectMemberRepository(session).is_member(
            row.project_id, viewer_user_id
        ):
            raise KbItemError("not_a_member", status_=403)
        if row.scope == "personal" and row.owner_user_id != viewer_user_id:
            raise KbItemError("forbidden", status_=403)

    async def _assert_can_edit(
        self, session, row: KbItemRow, actor_user_id: str
    ) -> None:
        if row.owner_user_id == actor_user_id:
            return
        if await _is_project_owner(session, row.project_id, actor_user_id):
            return
        raise KbItemError("forbidden", status_=403)


async def _is_project_owner(session, project_id: str, user_id: str) -> bool:
    members = await ProjectMemberRepository(session).list_for_project(
        project_id
    )
    return any(m.user_id == user_id and m.role == "owner" for m in members)


def _serialize(row: KbItemRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "folder_id": row.folder_id,
        "owner_user_id": row.owner_user_id,
        "scope": row.scope,
        "title": row.title,
        "content_md": row.content_md,
        "status": row.status,
        "source": row.source,
        "attachment": (
            {
                "filename": row.attachment_filename,
                "mime": row.attachment_mime,
                "bytes": row.attachment_bytes,
                "download_url": f"/api/kb-items/{row.id}/attachment",
            }
            if row.attachment_filename
            else None
        ),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _attachment_path(item_id: str, filename: str) -> Path:
    """Resolved path on the volume. Filename is already sanitized at
    upload time; we re-sanitize here as belt-and-braces against a
    poisoned DB row."""
    return KB_UPLOADS_ROOT / item_id / _sanitize_filename(filename)


def _sanitize_filename(name: str) -> str:
    """Strip path separators + null bytes; collapse double-dot to
    single. Keeps unicode, dashes, dots, underscores. Caps at 200
    chars (DB column is 500 but the file system has a per-component
    limit much lower on some setups)."""
    name = name.replace("\x00", "").strip()
    # Drop directory prefixes — only the last component is the filename.
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    # Collapse `..` so an attacker can't escape the item-id dir.
    while ".." in name:
        name = name.replace("..", ".")
    if len(name) > 200:
        # Preserve the suffix so MIME stays sniffable.
        stem, dot, ext = name.rpartition(".")
        if dot and len(ext) <= 16:
            name = stem[: 200 - len(ext) - 1] + "." + ext
        else:
            name = name[:200]
    return name or "attachment"


def _format_bytes(n: int) -> str:
    """Tiny human-readable formatter used in the inline-stub copy."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


__all__ = [
    "KbItemService",
    "KbItemError",
    "VALID_SCOPES",
    "VALID_STATUSES",
    "VALID_SOURCES",
]
