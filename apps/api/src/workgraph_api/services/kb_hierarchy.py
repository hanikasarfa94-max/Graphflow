"""KbHierarchyService — Phase 3.A hierarchical KB.

Flat KB → tree. Every project gets a root folder; members nest
folders under it and move items between them. Owners can clamp any
single item to a tighter license tier than the project default.

Design choices (see PLAN-v4.md §3.A):
  * The leaf IS still MembraneSignalRow — audit URLs
    (`/projects/[id]/kb/[itemId]`) must stay stable across the v3→v4
    cutover. We add `folder_id` to that table rather than splitting
    KB items into a new physical row.
  * Cycle detection lives here (walk ancestor chain of the candidate
    parent; reject if the moving folder appears). Not in the DB —
    SQLite can't express it and the service is the only writer.
  * Delete is non-recursive: 409 if the folder has any child folder
    OR any item. Keeps destructive actions explicit — users see what
    they'd lose.
  * Name uniqueness among siblings is enforced in `create_folder`
    only. Rename isn't exposed as a v4 endpoint yet; if it lands the
    service call has to re-check.
  * Listing returns a flat array of folders + items per render. The
    frontend nests in-memory. A materialized-path column would speed
    breadcrumbs at scale but is YAGNI for v1 — projects have tens of
    folders, not thousands.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    KbFolderRepository,
    KbItemLicenseRepository,
    KbItemRepository,
    ProjectMemberRepository,
    UserRepository,
    session_scope,
)

_log = logging.getLogger("workgraph.api.kb_hierarchy")


ALLOWED_TIERS = {"full", "task_scoped", "observer"}

# Reserved root name the migration-less auto-backfill uses. The UI
# renders this as "/"; the service never exposes the string literal
# as a folder name the user can clash with (create_folder skips
# creating a second root implicitly by always requiring a parent
# selection when the user picks "New folder" on a non-root selection,
# and reparent-to-null is owner-only).
ROOT_NAME = "/"


class KbHierarchyError(Exception):
    """Base for service-level errors surfaced as structured results."""


class KbHierarchyService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    # ---- membership / role helpers --------------------------------------

    async def _member(
        self, *, project_id: str, user_id: str
    ) -> Any | None:
        async with session_scope(self._sessionmaker) as session:
            for m in await ProjectMemberRepository(
                session
            ).list_for_project(project_id):
                if m.user_id == user_id:
                    return m
        return None

    async def _is_member(
        self, *, project_id: str, user_id: str
    ) -> bool:
        return await self._member(
            project_id=project_id, user_id=user_id
        ) is not None

    async def _is_owner(
        self, *, project_id: str, user_id: str
    ) -> bool:
        m = await self._member(project_id=project_id, user_id=user_id)
        return m is not None and m.role == "owner"

    async def _is_full_tier(
        self, *, project_id: str, user_id: str
    ) -> bool:
        m = await self._member(project_id=project_id, user_id=user_id)
        if m is None:
            return False
        return (m.license_tier or "full") == "full"

    # ---- backfill --------------------------------------------------------

    async def ensure_project_root(
        self, project_id: str
    ) -> str:
        """Return the id of the project's root folder, creating it if
        necessary and sweeping any folder-less items into it.

        Idempotent: called on first read of a project's KB tree, so
        pre-0013 rows get a folder without a separate backfill job.
        Safe to call repeatedly — the second call finds the root and
        short-circuits.
        """
        async with session_scope(self._sessionmaker) as session:
            folder_repo = KbFolderRepository(session)
            root = await folder_repo.find_root(project_id)
            if root is None:
                root = await folder_repo.create(
                    project_id=project_id,
                    name=ROOT_NAME,
                    parent_folder_id=None,
                    created_by_user_id=None,
                )
            # Sweep any orphan items into the root. F4: kb_items is the
            # single store; one query, both ingest + user-authored.
            kb_item_repo = KbItemRepository(session)
            orphans = [
                r
                for r in await kb_item_repo.list_visible_for_user(
                    project_id=project_id,
                    viewer_user_id="",
                    limit=10_000,
                )
                if r.folder_id is None and r.scope == "group"
            ]
            # We pass an empty viewer_user_id to avoid pulling personal
            # rows — orphan sweep is project-wide cleanup, scoped to the
            # group store so a user's personal draft never gets moved
            # without their consent.
            for r in orphans:
                r.folder_id = root.id
            if orphans:
                await session.flush()
            return root.id

    # ---- folder CRUD -----------------------------------------------------

    async def create_folder(
        self,
        *,
        project_id: str,
        user_id: str,
        name: str,
        parent_folder_id: str | None,
    ) -> dict[str, Any]:
        """Create a new folder under `parent_folder_id` (or at root if
        None). Full-tier member required per PLAN-v4.md §3.A.
        """
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "name_required"}
        if len(name) > 200:
            return {"ok": False, "error": "name_too_long"}
        if not await self._is_member(
            project_id=project_id, user_id=user_id
        ):
            return {"ok": False, "error": "not_a_member"}
        if not await self._is_full_tier(
            project_id=project_id, user_id=user_id
        ):
            return {"ok": False, "error": "forbidden"}

        # Ensure the project has a root before we try to place a child.
        # If parent is None and a root already exists, we refuse to
        # create a second root — root is a singleton per project so
        # the tree always has a well-defined anchor.
        await self.ensure_project_root(project_id)
        async with session_scope(self._sessionmaker) as session:
            folder_repo = KbFolderRepository(session)
            if parent_folder_id is None:
                # Redirect "no parent" creates to under the root — the
                # frontend always passes a parent, but the API stays
                # forgiving for scripted callers.
                root = await folder_repo.find_root(project_id)
                parent_folder_id = root.id if root is not None else None
            else:
                parent = await folder_repo.get(parent_folder_id)
                if parent is None or parent.project_id != project_id:
                    return {"ok": False, "error": "parent_not_found"}

            # Sibling-name uniqueness guard.
            clash = await folder_repo.find_by_name(
                project_id=project_id,
                parent_folder_id=parent_folder_id,
                name=name,
            )
            if clash is not None:
                return {"ok": False, "error": "name_conflict"}

            row = await folder_repo.create(
                project_id=project_id,
                name=name,
                parent_folder_id=parent_folder_id,
                created_by_user_id=user_id,
            )
            return {"ok": True, "folder": _folder_payload(row)}

    async def reparent_folder(
        self,
        *,
        project_id: str,
        user_id: str,
        folder_id: str,
        new_parent_id: str | None,
    ) -> dict[str, Any]:
        """Move `folder_id` under `new_parent_id`. Owner required.

        Returns `{ok:false, error:'cycle'}` if the proposed move would
        make `folder_id` an ancestor of itself. The frontend surfaces
        this as a toast.
        """
        if not await self._is_owner(
            project_id=project_id, user_id=user_id
        ):
            return {"ok": False, "error": "forbidden"}

        async with session_scope(self._sessionmaker) as session:
            folder_repo = KbFolderRepository(session)
            moving = await folder_repo.get(folder_id)
            if moving is None or moving.project_id != project_id:
                return {"ok": False, "error": "folder_not_found"}

            if new_parent_id is not None:
                new_parent = await folder_repo.get(new_parent_id)
                if (
                    new_parent is None
                    or new_parent.project_id != project_id
                ):
                    return {
                        "ok": False,
                        "error": "parent_not_found",
                    }
                # Cycle check: walk new_parent's ancestor chain — if
                # moving.id appears, we'd create a loop.
                ancestor_id: str | None = new_parent_id
                seen: set[str] = set()
                while ancestor_id is not None:
                    if ancestor_id == folder_id:
                        return {"ok": False, "error": "cycle"}
                    if ancestor_id in seen:
                        # Defensive: DB already has a cycle (shouldn't,
                        # but fail closed rather than infinite-loop).
                        return {"ok": False, "error": "cycle"}
                    seen.add(ancestor_id)
                    current = await folder_repo.get(ancestor_id)
                    if current is None:
                        break
                    ancestor_id = current.parent_folder_id

            all_folders = await folder_repo.list_for_project(project_id)
            siblings = [
                f
                for f in all_folders
                if f.parent_folder_id == new_parent_id
                and f.id != folder_id
            ]
            if any(s.name == moving.name for s in siblings):
                return {"ok": False, "error": "name_conflict"}

            updated = await folder_repo.set_parent(
                folder_id, parent_folder_id=new_parent_id
            )
            return {"ok": True, "folder": _folder_payload(updated)}

    async def delete_folder(
        self,
        *,
        project_id: str,
        user_id: str,
        folder_id: str,
    ) -> dict[str, Any]:
        """Delete an EMPTY folder. Owner required; 409 if non-empty."""
        if not await self._is_owner(
            project_id=project_id, user_id=user_id
        ):
            return {"ok": False, "error": "forbidden"}
        async with session_scope(self._sessionmaker) as session:
            folder_repo = KbFolderRepository(session)
            folder = await folder_repo.get(folder_id)
            if folder is None or folder.project_id != project_id:
                return {"ok": False, "error": "folder_not_found"}
            if folder.parent_folder_id is None:
                # Refuse to delete the root — every project must have
                # an anchor, and the backfill will just recreate it on
                # next read anyway. Easier to say no up front.
                return {"ok": False, "error": "cannot_delete_root"}
            children = await folder_repo.count_children(folder_id)
            items = await folder_repo.count_items(folder_id)
            if children or items:
                return {"ok": False, "error": "folder_not_empty"}
            await folder_repo.delete(folder_id)
            return {"ok": True, "deleted_id": folder_id}

    # ---- item move -------------------------------------------------------

    async def move_item(
        self,
        *,
        project_id: str,
        user_id: str,
        item_id: str,
        folder_id: str,
    ) -> dict[str, Any]:
        """Move a KB item to a new folder. Any project member may move
        items; this is collaborative curation, not governance.
        """
        if not await self._is_member(
            project_id=project_id, user_id=user_id
        ):
            return {"ok": False, "error": "not_a_member"}
        async with session_scope(self._sessionmaker) as session:
            folder_repo = KbFolderRepository(session)
            kb_item_repo = KbItemRepository(session)
            folder = await folder_repo.get(folder_id)
            if folder is None or folder.project_id != project_id:
                return {"ok": False, "error": "folder_not_found"}
            item = await kb_item_repo.get(item_id)
            if item is None or item.project_id != project_id:
                return {"ok": False, "error": "item_not_found"}
            updated = await folder_repo.set_item_folder(
                item_id, folder_id=folder_id
            )
            return {
                "ok": True,
                "item_id": updated.id,
                "folder_id": updated.folder_id,
            }

    # ---- per-item license override --------------------------------------

    async def set_item_license(
        self,
        *,
        project_id: str,
        user_id: str,
        item_id: str,
        license_tier: str | None,
    ) -> dict[str, Any]:
        """Clamp an item to a tighter tier, or clear the override by
        passing `license_tier=None`. Owner only.
        """
        if not await self._is_owner(
            project_id=project_id, user_id=user_id
        ):
            return {"ok": False, "error": "forbidden"}
        if license_tier is not None and license_tier not in ALLOWED_TIERS:
            return {"ok": False, "error": "invalid_tier"}
        async with session_scope(self._sessionmaker) as session:
            kb_item_repo = KbItemRepository(session)
            item = await kb_item_repo.get(item_id)
            if item is None or item.project_id != project_id:
                return {"ok": False, "error": "item_not_found"}
            license_repo = KbItemLicenseRepository(session)
            if license_tier is None:
                await license_repo.clear(item_id)
                return {
                    "ok": True,
                    "item_id": item_id,
                    "license_tier": None,
                }
            row = await license_repo.upsert(
                item_id=item_id,
                license_tier=license_tier,
                set_by_user_id=user_id,
            )
            return {
                "ok": True,
                "item_id": row.item_id,
                "license_tier": row.license_tier,
            }

    # ---- tree read -------------------------------------------------------

    async def get_tree(
        self,
        *,
        project_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Return a flat list of folders + items suitable for client-
        side tree assembly. Members only.

        Shape:
            {
              "folders": [
                {"id": str, "name": str, "parent_folder_id": str|null,
                 "created_at": iso, "updated_at": iso},
                ...
              ],
              "items": [
                {"id": str, "folder_id": str|null, "title": str,
                 "source_kind": str, "updated_at": iso|null,
                 "created_at": iso, "license_tier_override": str|null},
                ...
              ],
              "root_id": str|null,
            }

        We return a flat list with parent_id rather than a nested JSON
        tree because (a) rendering drag targets on the client needs a
        map keyed by id anyway, and (b) nested JSON makes incremental
        updates (move a folder via PATCH) messier to reconcile.
        """
        if not await self._is_member(
            project_id=project_id, user_id=user_id
        ):
            return {"ok": False, "error": "not_a_member"}
        await self.ensure_project_root(project_id)
        async with session_scope(self._sessionmaker) as session:
            folder_repo = KbFolderRepository(session)
            license_repo = KbItemLicenseRepository(session)
            user_repo = UserRepository(session)

            folders = await folder_repo.list_for_project(project_id)
            # F4: single-table read. All KB items (user-authored AND
            # ingested) live in kb_items now. Visibility:
            #   * scope='group'    — every project member
            #   * scope='personal' — owner_user_id only (filtered in repo)
            # Excludes 'rejected' (signals) and 'archived' (kb notes) so
            # the surface mirrors pre-fold behavior. Drafts surface so
            # the membrane-stage queue stays visible.
            kb_item_repo = KbItemRepository(session)
            items = [
                r
                for r in await kb_item_repo.list_visible_for_user(
                    project_id=project_id, viewer_user_id=user_id, limit=1000
                )
                if r.status not in ("rejected", "archived")
            ]
            license_map = await license_repo.get_map_for_items(
                [i.id for i in items]
            )
            username_cache: dict[str, str | None] = {}

            async def _username(uid: str | None) -> str | None:
                if uid is None:
                    return None
                if uid in username_cache:
                    return username_cache[uid]
                user = await user_repo.get(uid)
                username = user.username if user is not None else None
                username_cache[uid] = username
                return username

            folder_payloads = [_folder_payload(f) for f in folders]
            item_payloads = []
            for r in items:
                payload = _kb_item_payload(r)
                # license override applies to both ingest + user-authored
                # rows; the renderer left it absent so the caller fills it
                # uniformly here.
                payload["license_tier_override"] = license_map.get(r.id)
                # `ingested_by_user_id` is set on ingest rows; for user-
                # authored items we surface owner_user_id under the same
                # key so the FE doesn't need to switch on source.
                payload["ingested_by_username"] = await _username(
                    r.ingested_by_user_id or r.owner_user_id
                )
                item_payloads.append(payload)

            root = next(
                (f for f in folders if f.parent_folder_id is None), None
            )
            return {
                "ok": True,
                "folders": folder_payloads,
                "items": item_payloads,
                "root_id": root.id if root is not None else None,
            }


def _folder_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "parent_folder_id": row.parent_folder_id,
        "name": row.name,
        "created_by_user_id": row.created_by_user_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _kb_item_payload(row: Any) -> dict[str, Any]:
    """Render a KbItemRow into the kb tree shape, polymorphic on `source`.

    Three families share the same row shape post-fold (F4):
      * `source='ingest'`   — externally-ingested signal. `source_kind`
        carries the ingest sub-type (`user-drop` / `rss` / `webhook` /
        `git-commit` / etc.); summary + tags pulled from
        `classification_json`; raw text in `raw_content`.
      * `source='manual'|'upload'|'llm'`, `scope='group'`  — group KB note,
        rendered with `source_kind='kb-note'` so the FE treats it as
        a wiki entry.
      * `source='manual'|'upload'|'llm'`, `scope='personal'` — owner-only
        draft, rendered with `source_kind='kb-personal'` so the FE
        scopes visibility on the client side too.

    Frontend already polymorphs on `source_kind`, so adding the ingest
    variants here doesn't require any client change.
    """
    if row.source == "ingest":
        classification = dict(row.classification_json or {})
        summary = classification.get("summary") or (row.raw_content or "")
        title = (
            row.title
            or summary[:120]
            or row.source_identifier
            or row.id
        )
        return {
            "id": row.id,
            "folder_id": row.folder_id,
            "title": title,
            "summary": (summary or "")[:300],
            "source_kind": row.source_kind,
            "source_identifier": row.source_identifier,
            "status": row.status,
            "tags": list(classification.get("tags") or []),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            # license_tier_override is filled in by the caller via the
            # KbItemLicenseRepository.get_map_for_items bulk lookup —
            # same path that pre-fold MembraneSignalRow rows used.
        }
    src_kind = "kb-personal" if row.scope == "personal" else "kb-note"
    return {
        "id": row.id,
        "folder_id": row.folder_id,
        "title": row.title or "(untitled)",
        "summary": (row.content_md or "")[:300],
        "source_kind": src_kind,
        "source_identifier": None,
        "status": row.status,
        "tags": [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "license_tier_override": None,
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "ALLOWED_TIERS",
    "KbHierarchyError",
    "KbHierarchyService",
    "ROOT_NAME",
]
