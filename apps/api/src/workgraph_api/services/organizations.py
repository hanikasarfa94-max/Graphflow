"""Organization (Workspace) service — Studio / Enterprise tier above project.

This is the minimum-viable surface for the tier the user flagged as
missing: a container above ProjectRow so authority distribution and
"viewer vs new-employee" permissioning have a home to live in.

Scope (v1):
  * Create / list / detail / invite / remove / update role.
  * Attach an existing project to a workspace.

Deliberately out of scope (spelled out in callers' docstrings and the
deliverable report):
  * Authority delegation FROM the workspace TO members (scoped views).
    v1 stores the `viewer` role but enforcement is v2.
  * Cross-org project moves (once attached, detaching / reassigning
    needs a careful UX — deferred).
  * Workspace-scoped routing / KB / SSO / billing.
  * Workspace delete.

Role taxonomy:
  * owner  — create + everything. At least one must always remain.
  * admin  — invite + attach projects. Cannot alter ownership.
  * member — read + belong.
  * viewer — read-only (v2 will actually enforce).
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from workgraph_persistence import (
    OrganizationMemberRepository,
    OrganizationRepository,
    ProjectRow,
    UserRepository,
    session_scope,
)

VALID_ROLES = {"owner", "admin", "member", "viewer"}
MANAGEMENT_ROLES = {"owner", "admin"}


class OrganizationError(Exception):
    """Base for service-layer errors. Carries a machine-readable `code`
    so the router can translate to HTTP status + i18n string without
    stringly-typed branching."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


def _validate_slug(slug: str) -> None:
    """URL-safe lowercase slugs only. 3–64 chars, letters/digits/dashes,
    must start + end alphanumeric. We enforce here rather than in the
    repo so repo-layer callers (e.g. tests seeding fixtures) can skip
    validation if they need to — the router always calls the service."""
    if not isinstance(slug, str) or not _SLUG_RE.match(slug):
        raise OrganizationError(
            "invalid_slug",
            "slug must be 3–64 chars, lowercase letters/digits/dashes only",
        )


class OrganizationService:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sessionmaker = sessionmaker

    # ---- create / read --------------------------------------------------

    async def create_organization(
        self,
        *,
        name: str,
        slug: str,
        owner_user_id: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a workspace. Creator auto-joins as owner.

        Raises:
            OrganizationError('duplicate_slug') — slug is taken.
            OrganizationError('invalid_slug')    — slug fails shape check.
            OrganizationError('invalid_name')    — blank / too long.
        """
        name = (name or "").strip()
        if not name or len(name) > 120:
            raise OrganizationError("invalid_name", "name must be 1–120 chars")
        _validate_slug(slug)
        if description is not None and len(description) > 4000:
            raise OrganizationError(
                "invalid_description", "description must be ≤4000 chars"
            )

        async with session_scope(self._sessionmaker) as session:
            repo = OrganizationRepository(session)
            existing = await repo.get_by_slug(slug)
            if existing is not None:
                raise OrganizationError(
                    "duplicate_slug", f"workspace slug '{slug}' is taken"
                )
            org = await repo.create(
                name=name,
                slug=slug,
                owner_user_id=owner_user_id,
                description=description,
            )
            await OrganizationMemberRepository(session).add(
                organization_id=org.id,
                user_id=owner_user_id,
                role="owner",
                invited_by_user_id=None,
            )
            return _serialize_org(org)

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            memberships = await OrganizationMemberRepository(
                session
            ).list_for_user(user_id)
            if not memberships:
                return []
            org_ids = [m.organization_id for m in memberships]
            orgs = await OrganizationRepository(session).list_by_ids(org_ids)
            by_id = {o.id: o for o in orgs}
            out: list[dict[str, Any]] = []
            for m in memberships:
                org = by_id.get(m.organization_id)
                if org is None:
                    continue
                payload = _serialize_org(org)
                payload["role"] = m.role
                out.append(payload)
            return out

    async def get_by_slug(
        self, slug: str, *, viewer_user_id: str
    ) -> dict[str, Any]:
        """Detail view. Viewer must be a member."""
        async with session_scope(self._sessionmaker) as session:
            org = await OrganizationRepository(session).get_by_slug(slug)
            if org is None:
                raise OrganizationError(
                    "organization_not_found", f"workspace '{slug}' not found"
                )
            viewer_membership = await OrganizationMemberRepository(
                session
            ).get_member(org.id, viewer_user_id)
            if viewer_membership is None:
                raise OrganizationError(
                    "forbidden", "you are not a member of this workspace"
                )
            payload = _serialize_org(org)
            payload["role"] = viewer_membership.role
            # Attached projects — lightweight summary so the detail page
            # can render the "Projects in this workspace" list without a
            # second round-trip. No filtering yet (v1 is owner/admin +
            # member; they all see the same list). v2 applies
            # workspace-role-scoped visibility.
            from sqlalchemy import select as _select

            project_rows = list(
                (
                    await session.execute(
                        _select(ProjectRow)
                        .where(ProjectRow.organization_id == org.id)
                        .order_by(ProjectRow.updated_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            payload["projects"] = [
                {
                    "id": p.id,
                    "title": p.title,
                    "updated_at": (
                        p.updated_at.isoformat() if p.updated_at else None
                    ),
                }
                for p in project_rows
            ]
            return payload

    # ---- membership -----------------------------------------------------

    async def list_members(
        self, *, slug: str, viewer_user_id: str
    ) -> list[dict[str, Any]]:
        async with session_scope(self._sessionmaker) as session:
            org = await OrganizationRepository(session).get_by_slug(slug)
            if org is None:
                raise OrganizationError("organization_not_found")
            member_repo = OrganizationMemberRepository(session)
            if not await member_repo.is_member(org.id, viewer_user_id):
                raise OrganizationError("forbidden")
            memberships = await member_repo.list_for_organization(org.id)
            if not memberships:
                return []
            user_repo = UserRepository(session)
            out: list[dict[str, Any]] = []
            for m in memberships:
                user_row = await user_repo.get(m.user_id)
                if user_row is None:
                    continue
                out.append(
                    {
                        "user_id": user_row.id,
                        "username": user_row.username,
                        "display_name": user_row.display_name,
                        "role": m.role,
                        "invited_by_user_id": m.invited_by_user_id,
                        "created_at": (
                            m.created_at.isoformat() if m.created_at else None
                        ),
                    }
                )
            return out

    async def invite_member(
        self,
        *,
        slug: str,
        inviter_user_id: str,
        target_username: str,
        role: str = "member",
    ) -> dict[str, Any]:
        """Invite an existing user by username.

        Only owner/admin can invite. Target must already have a WorkGraph
        account — we surface `user_not_found` so the frontend can
        display "ask them to register first" rather than silently
        creating a ghost invite. Role must be in VALID_ROLES.
        """
        if role not in VALID_ROLES:
            raise OrganizationError("invalid_role", f"role must be one of {sorted(VALID_ROLES)}")

        async with session_scope(self._sessionmaker) as session:
            org = await OrganizationRepository(session).get_by_slug(slug)
            if org is None:
                raise OrganizationError("organization_not_found")
            member_repo = OrganizationMemberRepository(session)
            inviter = await member_repo.get_member(org.id, inviter_user_id)
            if inviter is None or inviter.role not in MANAGEMENT_ROLES:
                raise OrganizationError(
                    "forbidden",
                    "only workspace owners/admins can invite",
                )
            target = await UserRepository(session).get_by_username(target_username)
            if target is None:
                raise OrganizationError(
                    "user_not_found",
                    f"no account with username '{target_username}'",
                )
            row = await member_repo.add(
                organization_id=org.id,
                user_id=target.id,
                role=role,
                invited_by_user_id=inviter_user_id,
            )
            return {
                "ok": True,
                "user_id": target.id,
                "username": target.username,
                "display_name": target.display_name,
                "role": row.role,
            }

    async def update_member_role(
        self,
        *,
        slug: str,
        actor_user_id: str,
        target_user_id: str,
        new_role: str,
    ) -> dict[str, Any]:
        """Owner-only in v1. Admins cannot alter roles.

        Refuses to demote the last owner — the workspace always needs
        at least one. (Promotions to owner are fine; demotion of a
        non-last owner is fine.)
        """
        if new_role not in VALID_ROLES:
            raise OrganizationError("invalid_role")

        async with session_scope(self._sessionmaker) as session:
            org = await OrganizationRepository(session).get_by_slug(slug)
            if org is None:
                raise OrganizationError("organization_not_found")
            member_repo = OrganizationMemberRepository(session)
            actor = await member_repo.get_member(org.id, actor_user_id)
            if actor is None or actor.role != "owner":
                raise OrganizationError(
                    "forbidden", "only owners can change roles"
                )
            target = await member_repo.get_member(org.id, target_user_id)
            if target is None:
                raise OrganizationError("member_not_found")
            # Last-owner guard: demoting the last owner is the only
            # permanent-lockout path, so we block it even if the actor
            # is demoting themselves.
            if target.role == "owner" and new_role != "owner":
                owner_count = await member_repo.count_by_role(org.id, "owner")
                if owner_count <= 1:
                    raise OrganizationError(
                        "last_owner",
                        "cannot remove the last owner from a workspace",
                    )
            await member_repo.set_role(
                organization_id=org.id,
                user_id=target_user_id,
                new_role=new_role,
            )
            return {
                "ok": True,
                "user_id": target_user_id,
                "role": new_role,
            }

    async def remove_member(
        self,
        *,
        slug: str,
        actor_user_id: str,
        target_user_id: str,
    ) -> dict[str, Any]:
        """Owner-only. Cannot remove the last owner."""
        async with session_scope(self._sessionmaker) as session:
            org = await OrganizationRepository(session).get_by_slug(slug)
            if org is None:
                raise OrganizationError("organization_not_found")
            member_repo = OrganizationMemberRepository(session)
            actor = await member_repo.get_member(org.id, actor_user_id)
            if actor is None or actor.role != "owner":
                raise OrganizationError(
                    "forbidden", "only owners can remove members"
                )
            target = await member_repo.get_member(org.id, target_user_id)
            if target is None:
                raise OrganizationError("member_not_found")
            if target.role == "owner":
                owner_count = await member_repo.count_by_role(org.id, "owner")
                if owner_count <= 1:
                    raise OrganizationError(
                        "last_owner",
                        "cannot remove the last owner from a workspace",
                    )
            await member_repo.remove(
                organization_id=org.id, user_id=target_user_id
            )
            return {"ok": True, "user_id": target_user_id}

    # ---- project attachment --------------------------------------------

    async def attach_project(
        self,
        *,
        slug: str,
        project_id: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        """Nest an existing project under this workspace.

        Guards:
          * Actor must be workspace owner or admin.
          * Actor must be project owner (role == 'owner' in
            ProjectMemberRow) — the person attaching needs authority over
            the project they're moving in, not just the workspace.

        v1 limitation: once attached, we don't expose detach / move.
        Undo is a manual DB write for now.
        """
        from workgraph_persistence import ProjectMemberRepository
        from sqlalchemy import select as _select

        async with session_scope(self._sessionmaker) as session:
            org = await OrganizationRepository(session).get_by_slug(slug)
            if org is None:
                raise OrganizationError("organization_not_found")
            member_repo = OrganizationMemberRepository(session)
            actor_org = await member_repo.get_member(org.id, actor_user_id)
            if actor_org is None or actor_org.role not in MANAGEMENT_ROLES:
                raise OrganizationError(
                    "forbidden",
                    "only workspace owners/admins can attach projects",
                )
            # Actor must be project-owner on the target project.
            proj_member = await ProjectMemberRepository(session).list_for_project(
                project_id
            )
            actor_is_project_owner = any(
                m.user_id == actor_user_id and m.role == "owner"
                for m in proj_member
            )
            if not actor_is_project_owner:
                raise OrganizationError(
                    "forbidden",
                    "only the project owner can attach it to a workspace",
                )
            project_row = (
                await session.execute(
                    _select(ProjectRow).where(ProjectRow.id == project_id)
                )
            ).scalar_one_or_none()
            if project_row is None:
                raise OrganizationError("project_not_found")
            project_row.organization_id = org.id
            await session.flush()
            return {
                "ok": True,
                "project_id": project_id,
                "organization_id": org.id,
                "slug": org.slug,
            }


def _serialize_org(org) -> dict[str, Any]:
    return {
        "id": org.id,
        "name": org.name,
        "slug": org.slug,
        "owner_user_id": org.owner_user_id,
        "description": org.description,
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }
