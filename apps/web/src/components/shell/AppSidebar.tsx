"use client";

// AppSidebar — Phase Q global left rail navigation.
//
// Replaces the in-project top-tabs with a chat-tool-style sidebar
// (Lark / Slack / Linear rhythm). Sections, top to bottom:
//
//   * Brand / app name
//   * Home link (with routed-inbox badge)
//   * Expandable project list — each project expands into sub-items:
//       🧠 My thread     /projects/[id]
//       👥 Team room     /projects/[id]/team
//       📊 Status        /projects/[id]/status
//       📚 KB            /projects/[id]/kb (page may 404 — ok, Phase Q-A)
//       📝 Renders       /projects/[id]/renders/postmortem|handoff
//       🔎 Detail        /projects/[id]/detail/{graph,plan,…}
//   * Direct messages list
//   * Footer: Profile link, Language switcher, Sign out
//
// Active route is highlighted. The routed-inbox badge is clickable — it
// opens the drawer via the onOpenInbox callback owned by AppShellClient.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type CSSProperties } from "react";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import type { User } from "@/lib/api";

import { NewDMPicker } from "./NewDMPicker";
import { RoutedInboxBadge } from "./RoutedInboxBadge";
import type { ShellDM, ShellProject } from "./AppShellClient";

const SIDEBAR_WIDTH = 256;

const linkBase: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "7px 12px",
  fontSize: 13,
  color: "var(--wg-ink)",
  textDecoration: "none",
  borderRadius: "var(--wg-radius-sm, 4px)",
  lineHeight: 1.3,
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
}: {
  project: ShellProject;
  pathname: string | null;
  t: ReturnType<typeof useTranslations>;
}) {
  // Default-expand every project so the Team room + KB + Status are
  // visible without requiring an extra click. Small teams typically have
  // 1–3 projects; always-expanded reads better than hidden chat rooms.
  const [open, setOpen] = useState(true);
  const [rendersOpen, setRendersOpen] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);

  const myThread = `/projects/${project.id}`;
  const teamRoom = `/projects/${project.id}/team`;
  const status = `/projects/${project.id}/status`;
  const kb = `/projects/${project.id}/kb`;

  const subItem: CSSProperties = {
    ...linkBase,
    padding: "5px 12px 5px 28px",
    fontSize: 12,
    color: "var(--wg-ink-soft)",
  };
  const subItemActive: CSSProperties = {
    background: "var(--wg-accent-soft, #fdf4ec)",
    color: "var(--wg-accent)",
    fontWeight: 600,
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
              <span aria-hidden>🧠</span> {t("shell.project.myThread")}
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
              <span aria-hidden>👥</span> {t("shell.project.teamRoom")}
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
              <span aria-hidden>📊</span> {t("shell.project.status")}
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
              <span aria-hidden>📚</span> {t("shell.project.kb")}
            </Link>
          </li>
          <li>
            <button
              type="button"
              onClick={() => setRendersOpen((v) => !v)}
              aria-expanded={rendersOpen}
              style={{
                ...subItem,
                background: "transparent",
                border: "none",
                cursor: "pointer",
                textAlign: "left",
                width: "100%",
              }}
            >
              <span aria-hidden>📝</span> {t("shell.project.renders")}
              <span
                style={{ marginLeft: "auto", fontSize: 10 }}
                aria-hidden
              >
                {rendersOpen ? "▾" : "▸"}
              </span>
            </button>
            {rendersOpen && (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                <li>
                  <Link
                    href={`/projects/${project.id}/renders/postmortem`}
                    style={{
                      ...subItem,
                      paddingLeft: 44,
                      ...(isActive(
                        pathname,
                        `/projects/${project.id}/renders/postmortem`,
                      )
                        ? subItemActive
                        : null),
                    }}
                  >
                    · {t("shell.project.renders_postmortem")}
                  </Link>
                </li>
                <li>
                  <Link
                    href={`/projects/${project.id}/renders/handoff`}
                    style={{
                      ...subItem,
                      paddingLeft: 44,
                      ...(isActive(
                        pathname,
                        `/projects/${project.id}/renders/handoff`,
                      )
                        ? subItemActive
                        : null),
                    }}
                  >
                    · {t("shell.project.renders_handoff")}
                  </Link>
                </li>
              </ul>
            )}
          </li>
          <li>
            <button
              type="button"
              onClick={() => setDetailOpen((v) => !v)}
              aria-expanded={detailOpen}
              style={{
                ...subItem,
                background: "transparent",
                border: "none",
                cursor: "pointer",
                textAlign: "left",
                width: "100%",
              }}
            >
              <span aria-hidden>🔎</span> {t("shell.project.detail")}
              <span style={{ marginLeft: "auto", fontSize: 10 }} aria-hidden>
                {detailOpen ? "▾" : "▸"}
              </span>
            </button>
            {detailOpen && (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {(
                  [
                    ["graph", "shell.project.detail_graph"],
                    ["plan", "shell.project.detail_plan"],
                    ["tasks", "shell.project.detail_tasks"],
                    ["risks", "shell.project.detail_risks"],
                    ["decisions", "shell.project.detail_decisions"],
                  ] as const
                ).map(([slug, key]) => {
                  const href = `/projects/${project.id}/detail/${slug}`;
                  return (
                    <li key={slug}>
                      <Link
                        href={href}
                        style={{
                          ...subItem,
                          paddingLeft: 44,
                          ...(isActive(pathname, href, true)
                            ? subItemActive
                            : null),
                        }}
                      >
                        · {t(key)}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </li>
        </ul>
      )}
    </li>
  );
}

export function AppSidebar({
  user,
  projects,
  dms,
  inboxCount,
  onOpenInbox,
}: {
  user: User;
  projects: ShellProject[];
  dms: ShellDM[];
  inboxCount: number;
  onOpenInbox: () => void;
}) {
  const pathname = usePathname();
  const t = useTranslations();
  const homeActive = isActive(pathname, "/", true);

  return (
    <aside
      aria-label={t("shell.sidebar")}
      data-testid="app-sidebar"
      style={{
        width: SIDEBAR_WIDTH,
        minWidth: SIDEBAR_WIDTH,
        borderRight: "1px solid var(--wg-line)",
        background: "#fff",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        position: "sticky",
        top: 0,
      }}
    >
      {/* Brand */}
      <div
        style={{
          padding: "16px 14px 10px",
          borderBottom: "1px solid var(--wg-line)",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span className="wg-dot" />
        <Link
          href="/"
          style={{
            fontSize: 14,
            fontWeight: 600,
            color: "var(--wg-ink)",
            textDecoration: "none",
            letterSpacing: "-0.01em",
          }}
        >
          {t("brand.name")}
        </Link>
      </div>

      {/* Scrollable nav */}
      <nav
        aria-label={t("shell.nav")}
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "8px 6px",
        }}
      >
        {/* Home */}
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          <li>
            <Link
              href="/"
              data-testid="sidebar-home-link"
              style={{
                ...linkBase,
                background: homeActive
                  ? "var(--wg-accent-soft, #fdf4ec)"
                  : "transparent",
                color: homeActive ? "var(--wg-accent)" : "var(--wg-ink)",
                fontWeight: homeActive ? 600 : 400,
              }}
            >
              <span aria-hidden>🏠</span>
              <span>{t("shell.home")}</span>
            </Link>
          </li>
          <li>
            <RoutedInboxBadge
              count={inboxCount}
              onClick={onOpenInbox}
            />
          </li>
        </ul>

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
                      background: active
                        ? "var(--wg-accent-soft, #fdf4ec)"
                        : "transparent",
                      color: active ? "var(--wg-accent)" : "var(--wg-ink)",
                      fontWeight: active ? 600 : 400,
                    }}
                  >
                    <span aria-hidden>💬</span>
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
            background: isActive(pathname, "/settings/profile")
              ? "var(--wg-accent-soft, #fdf4ec)"
              : "transparent",
            color: isActive(pathname, "/settings/profile")
              ? "var(--wg-accent)"
              : "var(--wg-ink)",
          }}
        >
          <span aria-hidden>👤</span>
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
            action="/api/auth/logout"
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
