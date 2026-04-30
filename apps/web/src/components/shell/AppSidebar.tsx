"use client";

// AppSidebar — Phase Q global left rail navigation.
//
// Replaces the in-project top-tabs with a chat-tool-style sidebar
// (Lark / Slack / Linear rhythm). Sections, top to bottom:
//
//   * Brand / app name
//   * Home link (with routed-inbox badge)
//   * Expandable project list — each project expands into sub-items:
//       ☁ My thread     /projects/[id]
//       ♟ Team room     /projects/[id]/team
//       ▣ Status        /projects/[id]/status
//       ⌬ Org           /projects/[id]/org
//       ▥ KB            /projects/[id]/kb
//       ✣ Skills        /projects/[id]/skills
//       ▤ Docs          /projects/[id]/renders/postmortem|handoff
//       ⌕ Audit         /projects/[id]/detail/{graph,plan,…}
//   * Direct messages list
//   * Footer: Profile link, Language switcher, Sign out
//
// Glyphs come from the html2 sidebar-first prototype — a monochrome
// geometric set that renders identically across OSes (no platform-emoji
// drift) and reads as "instrument" rather than "social app."
//
// Active route is highlighted. The routed-inbox badge is clickable — it
// opens the drawer via the onOpenInbox callback owned by AppShellClient.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import {
  api,
  listProjectRooms,
  type ProjectState,
  type RoomSummary,
  type User,
} from "@/lib/api";
import {
  NewRoomModal,
  type ProjectMemberLite,
} from "@/components/rooms/NewRoomModal";

import { NewDMPicker } from "./NewDMPicker";
import { RoutedInboxBadge } from "./RoutedInboxBadge";
import type { ShellDM, ShellProject, ShellWorkspace } from "./AppShellClient";

const SIDEBAR_WIDTH = 256;

const linkBase: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "8px 12px",
  fontSize: 13,
  color: "var(--wg-ink)",
  textDecoration: "none",
  borderRadius: 10,
  lineHeight: 1.3,
  transition:
    "background 140ms ease-out, color 140ms ease-out",
};

// Active-state pill — gradient blue tint, brand-coloured text. Used by
// every nav row (top-level + project sub-items) so the highlight has a
// consistent silhouette across the rail.
const linkActive: CSSProperties = {
  background: "linear-gradient(135deg, #eaf2ff, #dbeafe)",
  color: "var(--wg-accent)",
  fontWeight: 700,
};

const sectionLabel: CSSProperties = {
  fontSize: 10,
  fontFamily: "var(--wg-font-mono)",
  color: "var(--wg-ink-soft)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  padding: "4px 12px",
  marginTop: 12,
  marginBottom: 4,
};

function isActive(pathname: string | null, href: string, exact = false): boolean {
  if (!pathname) return false;
  if (exact) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

function UnreadDot({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span
      aria-label={`${count} unread`}
      style={{
        marginLeft: "auto",
        background: "var(--wg-accent)",
        color: "#fff",
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
        fontWeight: 600,
        padding: "1px 6px",
        borderRadius: 10,
        minWidth: 18,
        textAlign: "center",
        lineHeight: 1.4,
      }}
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}

function ProjectNode({
  project,
  pathname,
  t,
  currentUserId,
}: {
  project: ShellProject;
  pathname: string | null;
  t: ReturnType<typeof useTranslations>;
  currentUserId: string;
}) {
  // Default-expand every project so the Team room + KB + Status are
  // visible without requiring an extra click. Small teams typically have
  // 1–3 projects; always-expanded reads better than hidden chat rooms.
  const [open, setOpen] = useState(true);

  // Batch E.4 IA simplification — one entry per per-project surface.
  // The redesign collapses Composition → Org (same authority lens),
  // drops Meetings from the sidebar (it lives inside Team room
  // workflow), and unwinds the Renders accordion into a single Docs
  // entry that lands on the postmortem default. Pages still exist at
  // their old URLs — only the sidebar surface shrinks.
  const myThread = `/projects/${project.id}`;
  const teamRoom = `/projects/${project.id}/team`;
  const status = `/projects/${project.id}/status`;
  const org = `/projects/${project.id}/org`;
  const kb = `/projects/${project.id}/kb`;
  const skills = `/projects/${project.id}/skills`;
  const docs = `/projects/${project.id}/renders`;
  // Audit View — Batch B IA reshape. The 5 audit subpages
  // (graph/plan/tasks/risks/decisions) collapse into one sidebar
  // entry; the user lands on the graph tab by default and switches
  // among the audit views via the in-page AuditTabBar.
  const auditDefault = `/projects/${project.id}/detail/graph`;
  const auditActive = pathname?.startsWith(`/projects/${project.id}/detail/`)
    && (pathname.includes("/detail/graph")
      || pathname.includes("/detail/plan")
      || pathname.includes("/detail/tasks")
      || pathname.includes("/detail/risks")
      || pathname.includes("/detail/decisions"));
  const docsActive = pathname?.startsWith(`/projects/${project.id}/renders/`);

  const subItem: CSSProperties = {
    ...linkBase,
    padding: "6px 12px 6px 28px",
    fontSize: 12,
    color: "var(--wg-ink-soft)",
    borderRadius: 9,
  };
  const subItemActive: CSSProperties = {
    ...linkActive,
    fontWeight: 700,
  };

  return (
    <li style={{ marginBottom: 2 }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          ...linkBase,
          width: "100%",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          textAlign: "left",
          justifyContent: "flex-start",
          fontWeight: pathname?.startsWith(`/projects/${project.id}`) ? 600 : 400,
        }}
      >
        <span style={{ width: 14, textAlign: "center", fontSize: 10 }} aria-hidden>
          {open ? "▾" : "▸"}
        </span>
        <span
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            flex: 1,
          }}
          title={project.title}
        >
          {project.title}
        </span>
        <UnreadDot count={project.unread_count} />
      </button>
      {open && (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          <li>
            <Link
              href={myThread}
              style={{
                ...subItem,
                ...(isActive(pathname, myThread, true) ? subItemActive : null),
              }}
            >
              <span aria-hidden>☁</span> {t("shell.project.myThread")}
            </Link>
          </li>
          <li>
            <Link
              href={teamRoom}
              style={{
                ...subItem,
                ...(isActive(pathname, teamRoom) ? subItemActive : null),
              }}
            >
              <span aria-hidden>♟</span> {t("shell.project.teamRoom")}
            </Link>
          </li>
          <li>
            <Link
              href={status}
              style={{
                ...subItem,
                ...(isActive(pathname, status) ? subItemActive : null),
              }}
            >
              <span aria-hidden>▣</span> {t("shell.project.status")}
            </Link>
          </li>
          <li>
            <Link
              href={org}
              style={{
                ...subItem,
                ...(isActive(pathname, org) ? subItemActive : null),
              }}
            >
              <span aria-hidden>⌬</span> {t("shell.project.organization")}
            </Link>
          </li>
          <li>
            <Link
              href={kb}
              style={{
                ...subItem,
                ...(isActive(pathname, kb) ? subItemActive : null),
              }}
            >
              <span aria-hidden>▥</span> {t("shell.project.kb")}
            </Link>
          </li>
          <li>
            <Link
              href={skills}
              style={{
                ...subItem,
                ...(isActive(pathname, skills) ? subItemActive : null),
              }}
            >
              <span aria-hidden>✣</span> {t("shell.project.skills")}
            </Link>
          </li>
          <li>
            <Link
              href={docs}
              style={{
                ...subItem,
                ...(docsActive ? subItemActive : null),
              }}
            >
              <span aria-hidden>▤</span> {t("shell.project.docs")}
            </Link>
          </li>
          <li>
            <Link
              href={auditDefault}
              style={{
                ...subItem,
                ...(auditActive ? subItemActive : null),
              }}
            >
              <span aria-hidden>⌕</span> {t("shell.project.audit")}
            </Link>
          </li>
          <ProjectRoomsSection
            projectId={project.id}
            currentUserId={currentUserId}
            pathname={pathname}
            subItem={subItem}
            subItemActive={subItemActive}
          />
        </ul>
      )}
    </li>
  );
}

// ProjectRoomsSection — collapsible "Rooms" entry inside each project
// in the sidebar. Lazy-fetches the rooms list on first expand, lists
// each room as a sub-link, and offers a "+ New room" affordance that
// opens NewRoomModal with project members pre-loaded.
function ProjectRoomsSection({
  projectId,
  currentUserId,
  pathname,
  subItem,
  subItemActive,
}: {
  projectId: string;
  currentUserId: string;
  pathname: string | null;
  subItem: CSSProperties;
  subItemActive: CSSProperties;
}) {
  const t = useTranslations("shell.project");
  const tRooms = useTranslations("stream.rooms");
  // Auto-open this section when the URL is already at a room route so
  // the active room is visible without clicking.
  const isRoomActive = pathname?.startsWith(`/projects/${projectId}/rooms/`);
  const [open, setOpen] = useState<boolean>(Boolean(isRoomActive));
  const [rooms, setRooms] = useState<RoomSummary[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [members, setMembers] = useState<ProjectMemberLite[] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [membersLoading, setMembersLoading] = useState(false);

  const refreshRooms = useCallback(async () => {
    setLoading(true);
    try {
      const r = await listProjectRooms(projectId);
      setRooms(r.rooms);
    } catch {
      setRooms([]);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  // First open or active-room-on-mount → fetch.
  useEffect(() => {
    if (open && rooms === null && !loading) {
      void refreshRooms();
    }
  }, [open, rooms, loading, refreshRooms]);

  async function ensureMembersLoaded() {
    if (members !== null || membersLoading) return;
    setMembersLoading(true);
    try {
      const state = await api<ProjectState>(`/api/projects/${projectId}/state`);
      const lite: ProjectMemberLite[] = (state.members ?? []).map((m) => ({
        user_id: m.user_id,
        username: m.username,
        display_name: m.display_name,
      }));
      setMembers(lite);
    } catch {
      setMembers([]);
    } finally {
      setMembersLoading(false);
    }
  }

  async function openNewRoom() {
    await ensureMembersLoaded();
    setModalOpen(true);
  }

  return (
    <>
      <li>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          style={{
            ...subItem,
            background: "transparent",
            border: "none",
            cursor: "pointer",
            width: "100%",
            textAlign: "left",
            display: "flex",
            alignItems: "center",
            gap: 6,
            ...(isRoomActive ? subItemActive : null),
          }}
        >
          <span aria-hidden style={{ fontSize: 9, width: 10, opacity: 0.6 }}>
            {open ? "▾" : "▸"}
          </span>
          <span aria-hidden>♛</span>
          <span style={{ flex: 1 }}>{t("rooms")}</span>
          {rooms && rooms.length > 0 && (
            <span
              style={{
                fontSize: 10,
                color: "var(--wg-ink-soft)",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {rooms.length}
            </span>
          )}
        </button>
      </li>
      {open && (
        <>
          <li>
            <button
              type="button"
              onClick={() => void openNewRoom()}
              disabled={membersLoading}
              style={{
                ...subItem,
                paddingLeft: 44,
                background: "transparent",
                border: "none",
                cursor: membersLoading ? "wait" : "pointer",
                width: "100%",
                textAlign: "left",
                color: "var(--wg-accent)",
                fontWeight: 600,
              }}
            >
              ＋ {tRooms("newRoom.openButton")}
            </button>
          </li>
          {loading && rooms === null && (
            <li
              style={{
                ...subItem,
                paddingLeft: 44,
                fontSize: 11,
                color: "var(--wg-ink-soft)",
                cursor: "default",
              }}
            >
              {tRooms("loading")}
            </li>
          )}
          {rooms !== null && rooms.length === 0 && !loading && (
            <li
              style={{
                ...subItem,
                paddingLeft: 44,
                fontSize: 11,
                color: "var(--wg-ink-soft)",
                cursor: "default",
                fontStyle: "italic",
              }}
            >
              {tRooms("emptyList")}
            </li>
          )}
          {rooms?.map((r) => {
            const href = `/projects/${projectId}/rooms/${r.id}`;
            const active = pathname === href;
            return (
              <li key={r.id}>
                <Link
                  href={href}
                  style={{
                    ...subItem,
                    paddingLeft: 44,
                    ...(active ? subItemActive : null),
                  }}
                >
                  <span style={{ flex: 1 }}>
                    {r.name ?? r.id.slice(0, 8)}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      color: "var(--wg-ink-soft)",
                      fontFamily: "var(--wg-font-mono)",
                    }}
                  >
                    {r.members?.length ?? 0}p
                  </span>
                </Link>
              </li>
            );
          })}
        </>
      )}
      {members !== null && (
        <NewRoomModal
          projectId={projectId}
          members={members}
          currentUserId={currentUserId}
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          onCreated={() => {
            // Refresh the list so the new room appears immediately
            // (the user navigates into it via NewRoomModal's
            // router.push, but the sidebar still re-renders with
            // the fresh list).
            void refreshRooms();
          }}
        />
      )}
    </>
  );
}

export function AppSidebar({
  user,
  projects,
  dms,
  inboxCount,
  onOpenInbox,
  workspaces = [],
}: {
  user: User;
  projects: ShellProject[];
  dms: ShellDM[];
  inboxCount: number;
  onOpenInbox: () => void;
  workspaces?: ShellWorkspace[];
}) {
  const pathname = usePathname();
  const t = useTranslations();
  const homeActive = isActive(pathname, "/", true);
  // Match /projects exactly (the all-projects list page) but NOT
  // /projects/[id]/* — those highlight the per-project tree below.
  const projectsActive = isActive(pathname, "/projects", true);

  return (
    <aside
      aria-label={t("shell.sidebar")}
      data-testid="app-sidebar"
      style={{
        width: SIDEBAR_WIDTH,
        minWidth: SIDEBAR_WIDTH,
        borderRight: "1px solid var(--wg-line)",
        // Glass over the page-level gradient so the sidebar reads as a
        // surface, not a slab. Backdrop-filter degrades silently on
        // browsers that don't support it.
        background: "rgba(255,255,255,0.86)",
        backdropFilter: "blur(18px)",
        WebkitBackdropFilter: "blur(18px)",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        position: "sticky",
        top: 0,
      }}
    >
      {/* Brand — gradient W mark + name + tagline. The mark is the
          single most repeated visual; making it a small instrument
          (gradient + soft shadow) is cheap personality. */}
      <Link
        href="/"
        style={{
          padding: "16px 14px 14px",
          borderBottom: "1px solid var(--wg-line)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          textDecoration: "none",
          color: "var(--wg-ink)",
        }}
      >
        <span
          aria-hidden
          style={{
            width: 32,
            height: 32,
            borderRadius: 11,
            display: "grid",
            placeItems: "center",
            background:
              "linear-gradient(135deg, #38bdf8, var(--wg-accent))",
            color: "#fff",
            fontWeight: 800,
            fontSize: 15,
            letterSpacing: "-0.02em",
            boxShadow: "0 8px 18px rgba(37,99,235,0.22)",
          }}
        >
          W
        </span>
        <span style={{ display: "flex", flexDirection: "column", gap: 1 }}>
          <span
            style={{
              fontSize: 15,
              fontWeight: 700,
              letterSpacing: "-0.01em",
            }}
          >
            {t("brand.name")}
          </span>
          <span
            style={{
              fontSize: 10,
              color: "var(--wg-ink-soft)",
              letterSpacing: "0.04em",
            }}
          >
            {t("brand.shortTagline")}
          </span>
        </span>
      </Link>

      {/* Scrollable nav */}
      <nav
        aria-label={t("shell.nav")}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "8px 6px",
        }}
      >
        {/* Home + global nav */}
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          <li>
            <Link
              href="/"
              data-testid="sidebar-home-link"
              style={{
                ...linkBase,
                ...(homeActive ? linkActive : null),
              }}
            >
              <span aria-hidden>⌂</span>
              <span>{t("shell.home")}</span>
            </Link>
          </li>
          <li>
            {/*
              All-projects page entry. The Home view shows projects as
              one of its sections; this link gives a dedicated all-
              projects surface for users who want to see / create
              projects without the rest of the home noise — and is the
              answer to "I quit a project, where do I go to find
              another one."
            */}
            <Link
              href="/projects"
              data-testid="sidebar-projects-link"
              style={{
                ...linkBase,
                ...(projectsActive ? linkActive : null),
              }}
            >
              <span aria-hidden>▦</span>
              <span>{t("nav.projects")}</span>
            </Link>
          </li>
          <li>
            <RoutedInboxBadge
              count={inboxCount}
              onClick={onOpenInbox}
            />
          </li>
        </ul>

        {/* Workspaces — Phase T tier above Projects. Hidden when the
            user belongs to none, so registered users without a
            workspace see the existing layout unchanged. */}
        {workspaces.length > 0 ? (
          <>
            <div style={sectionLabel}>{t("workspace.sidebarSection")}</div>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {workspaces.map((w) => {
                const wsHref = `/workspaces/${w.slug}`;
                const wsActive = isActive(pathname, wsHref);
                return (
                  <li key={w.id} style={{ marginBottom: 2 }}>
                    <Link
                      href={wsHref}
                      data-testid="sidebar-workspace-link"
                      data-slug={w.slug}
                      style={{
                        ...linkBase,
                        ...(wsActive ? linkActive : null),
                      }}
                      title={w.name}
                    >
                      <span aria-hidden>⊞</span>
                      <span
                        style={{
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          flex: 1,
                        }}
                      >
                        {w.name}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </>
        ) : null}

        {/* Projects */}
        <div style={sectionLabel}>{t("shell.projects")}</div>
        {projects.length === 0 ? (
          <div
            style={{
              padding: "4px 12px",
              fontSize: 12,
              color: "var(--wg-ink-soft)",
            }}
          >
            {t("shell.noProjects")}
          </div>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {projects.map((p) => (
              <ProjectNode
                key={p.id}
                project={p}
                pathname={pathname}
                t={t}
                currentUserId={user.id}
              />
            ))}
          </ul>
        )}

        {/* Direct messages */}
        <div style={sectionLabel}>{t("shell.dms")}</div>
        <NewDMPicker projects={projects} currentUserId={user.id} />
        {dms.length === 0 ? (
          <div
            style={{
              padding: "4px 12px",
              fontSize: 12,
              color: "var(--wg-ink-soft)",
            }}
          >
            {t("shell.noDms")}
          </div>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {dms.map((dm) => {
              const href = `/streams/${dm.stream_id}`;
              const active = isActive(pathname, href, true);
              return (
                <li key={dm.stream_id} style={{ marginBottom: 2 }}>
                  <Link
                    href={href}
                    style={{
                      ...linkBase,
                      ...(active ? linkActive : null),
                    }}
                  >
                    <span aria-hidden>☁</span>
                    <span
                      style={{
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        flex: 1,
                      }}
                      title={dm.other_display_name}
                    >
                      {dm.other_display_name}
                    </span>
                    <UnreadDot count={dm.unread_count} />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </nav>

      {/* Footer */}
      <div
        style={{
          borderTop: "1px solid var(--wg-line)",
          padding: "10px 12px",
          display: "flex",
          flexDirection: "column",
          gap: 8,
          background: "var(--wg-surface-raised, #fafaf7)",
        }}
      >
        <Link
          href="/settings/profile"
          data-testid="sidebar-profile-link"
          style={{
            ...linkBase,
            padding: "6px 8px",
            ...(isActive(pathname, "/settings/profile") ? linkActive : null),
          }}
        >
          <span
            aria-hidden
            style={{
              width: 24,
              height: 24,
              borderRadius: "50%",
              display: "grid",
              placeItems: "center",
              background: "var(--wg-accent-soft)",
              color: "var(--wg-accent)",
              fontSize: 11,
              fontWeight: 700,
              fontFamily: "var(--wg-font-mono)",
              flexShrink: 0,
            }}
          >
            {(user.display_name || user.username || "?").slice(0, 1)}
          </span>
          <span
            style={{
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              flex: 1,
            }}
            title={user.display_name || user.username}
          >
            {user.display_name || user.username}
          </span>
        </Link>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
            paddingLeft: 4,
          }}
        >
          <LanguageSwitcher />
          <form
            action="/api/auth/logout?redirect=/"
            method="POST"
            style={{ display: "inline" }}
          >
            <button
              type="submit"
              data-testid="sidebar-signout"
              style={{
                background: "transparent",
                border: "none",
                color: "var(--wg-accent)",
                cursor: "pointer",
                fontSize: 12,
                fontFamily: "var(--wg-font-mono)",
                padding: 0,
              }}
            >
              {t("shell.signOut")}
            </button>
          </form>
        </div>
      </div>
    </aside>
  );
}
