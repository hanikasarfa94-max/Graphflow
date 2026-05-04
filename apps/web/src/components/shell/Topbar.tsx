"use client";

// Topbar — Batch E.5 global header.
//
// Sits above every page inside the AppShell main pane:
//   * brand dot + breadcrumb derived from the current path
//   * search pill (placeholder for the future Cmd-K palette — no
//     backend yet, but the affordance signals "we know you'll want
//     to jump-search soon")
//   * notification button — opens the routed-inbound drawer when
//     there's pending work, mutes when empty
//   * **切换项目** dropdown — port of prototype App.tsx::ProjectBar
//     dropdown. Lazy-fetches /api/projects on first open; jumps to
//     /projects/{id} on click. Current project highlighted.
//   * **+ 新建 ▾** dropdown — port of prototype App.tsx:73 newMenu.
//     Items: 新建项目 (functional → /projects), 新建 Agent / 新建频道
//     / 新建任务 (inert vocabulary chips matching the workbench +
//     composer plus-menu pattern). User-avatar / settings deliberately
//     left out — already in AppSidebar; one canonical place each.
//
// Pure client component. Reads pathname + the AppShell context for
// inbox count + open handler.

import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { fetchMyProjects, type ProjectSummary } from "@/lib/api";

import { useAppShell } from "./AppShellClient";

const SEGMENT_LABELS: Record<string, string> = {
  "": "home",
  projects: "projects",
  workspaces: "workspaces",
  settings: "settings",
  streams: "dm",
  inbox: "inbox",
  detail: "audit",
  graph: "graph",
  plan: "plan",
  tasks: "tasks",
  risks: "risks",
  decisions: "decisions",
  status: "status",
  org: "org",
  kb: "kb",
  skills: "skills",
  team: "team-room",
  renders: "docs",
  postmortem: "postmortem",
  handoff: "handoff",
  meetings: "meetings",
  composition: "composition",
  nodes: "node",
  conflicts: "conflicts",
  clarify: "clarify",
  delivery: "delivery",
  events: "events",
  im: "im",
};

function isOpaqueId(seg: string): boolean {
  // UUID-looking segments and stream/session IDs aren't human-readable
  // breadcrumb material — collapse them to "·" so the path stays
  // legible. Anything 16+ chars with at least one dash is a candidate.
  return seg.length >= 16 && /[a-f0-9-]{16,}/i.test(seg);
}

function buildCrumbs(
  pathname: string,
  projectTitleById: Map<string, string>,
): string {
  const parts = pathname.split("/").filter(Boolean);
  const segs = parts.map((s, i) => {
    if (isOpaqueId(s)) {
      // The segment right after `/projects/` is a project ID — try to
      // resolve it to a real title from the sidebar's project list so
      // the breadcrumb reads "GRAPHFLOW / PROJECTS / Welcome to graphflow"
      // instead of the orphan "·" placeholder.
      if (i > 0 && parts[i - 1] === "projects") {
        const title = projectTitleById.get(s);
        if (title) return title;
      }
      return "·";
    }
    return SEGMENT_LABELS[s] ?? s;
  });
  if (segs.length === 0) return "GRAPHFLOW / HOME";
  return ["GRAPHFLOW", ...segs.map((s) => s.toUpperCase())].join(" / ");
}

export function Topbar() {
  const t = useTranslations("topbar");
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const { inboxCount, openInbox, projects: shellProjects } = useAppShell();

  const projectTitleById = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of shellProjects) m.set(p.id, p.title);
    return m;
  }, [shellProjects]);

  const crumbs = buildCrumbs(pathname, projectTitleById);

  // Lazy-fetched project list for the switcher dropdown. Single
  // request shared across opens (cached on the component for the
  // life of the page).
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [projectMenuOpen, setProjectMenuOpen] = useState(false);
  const [newMenuOpen, setNewMenuOpen] = useState(false);
  const projectMenuRef = useRef<HTMLDivElement | null>(null);
  const newMenuRef = useRef<HTMLDivElement | null>(null);

  // Derive the current project id from the URL so the switcher can
  // mark it active. Pathname is `/projects/<id>/...` for any project
  // route; everything else returns null.
  const currentProjectId = useMemo(() => {
    const m = pathname.match(/^\/projects\/([^/]+)/);
    if (!m) return null;
    const seg = m[1];
    // Skip the index route (`/projects` with no id).
    return seg && !["new", "intake"].includes(seg) ? seg : null;
  }, [pathname]);

  const openProjectMenu = () => {
    setProjectMenuOpen((open) => {
      const next = !open;
      if (next && projects === null && !projectsLoading) {
        setProjectsLoading(true);
        fetchMyProjects()
          .then((rows) => setProjects(rows))
          .catch((e: unknown) => {
            setProjectsError(
              e instanceof Error ? e.message : "fetch failed",
            );
          })
          .finally(() => setProjectsLoading(false));
      }
      return next;
    });
  };

  // Click-outside dismissal for both menus.
  useEffect(() => {
    if (!projectMenuOpen && !newMenuOpen) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node | null;
      if (
        projectMenuOpen &&
        projectMenuRef.current &&
        target &&
        !projectMenuRef.current.contains(target)
      ) {
        setProjectMenuOpen(false);
      }
      if (
        newMenuOpen &&
        newMenuRef.current &&
        target &&
        !newMenuRef.current.contains(target)
      ) {
        setNewMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [projectMenuOpen, newMenuOpen]);

  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        // Compact padding — prototype legacy-standalone-v6.html line
        // 31 sets the top row to ~44px. The earlier 16/14 vertical
        // padding pushed Topbar to 66px, overflowing the v-next
        // grid's first row and visually piling onto the ProjectBar.
        padding: "6px 16px",
        borderBottom: "1px solid var(--wg-line-soft)",
        // Subtle frosted band — sits above the page content but below
        // any modal / drawer.
        background: "rgba(255,255,255,0.78)",
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        position: "sticky",
        top: 0,
        zIndex: 5,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          minWidth: 0,
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          letterSpacing: "0.08em",
          color: "var(--wg-ink-soft)",
        }}
      >
        <span
          aria-hidden
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: "var(--wg-accent)",
            boxShadow: "0 0 0 3px rgba(37,99,235,0.18)",
            flexShrink: 0,
          }}
        />
        <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {crumbs}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div
          aria-hidden
          title={t("searchComingSoon")}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "0 14px",
            height: 32,
            borderRadius: 999,
            border: "1px dashed var(--wg-line)",
            background: "rgba(255,255,255,0.5)",
            color: "var(--wg-ink-faint)",
            fontSize: 12,
            minWidth: 220,
            cursor: "not-allowed",
          }}
        >
          <span style={{ fontFamily: "var(--wg-font-mono)" }}>⌕</span>
          <span style={{ flex: 1 }}>{t("searchPlaceholder")}</span>
          <span
            style={{
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-faint)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            {t("searchSoonBadge")}
          </span>
        </div>
        <button
          type="button"
          onClick={openInbox}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            height: 32,
            padding: "0 14px",
            borderRadius: 12,
            border: "1px solid var(--wg-line)",
            background: "var(--wg-surface)",
            color: "var(--wg-ink)",
            cursor: "pointer",
            fontSize: 12,
            fontWeight: 600,
          }}
          aria-label={t("notifications")}
        >
          <span aria-hidden>✦</span>
          <span>{t("notifications")}</span>
          {inboxCount > 0 ? (
            <span
              style={{
                background: "var(--wg-accent)",
                color: "#fff",
                borderRadius: 999,
                fontSize: 10,
                padding: "1px 6px",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {inboxCount > 99 ? "99+" : inboxCount}
            </span>
          ) : null}
        </button>
        <div ref={projectMenuRef} style={{ position: "relative" }}>
          <button
            type="button"
            data-testid="project-switcher-button"
            onClick={openProjectMenu}
            aria-expanded={projectMenuOpen}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 32,
              padding: "0 14px",
              borderRadius: 12,
              border: "1px solid var(--wg-line)",
              background: projectMenuOpen
                ? "var(--wg-accent-soft)"
                : "var(--wg-surface)",
              color: "var(--wg-ink)",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            <span>{t("switchProject")}</span>
            <span aria-hidden style={{ fontSize: 9, opacity: 0.6 }}>
              ▾
            </span>
          </button>
          {projectMenuOpen && (
            <div
              data-testid="project-switcher-menu"
              role="menu"
              style={topbarDropdownStyle()}
            >
              {projectsLoading ? (
                <div style={dropdownNoteStyle()}>
                  {t("projectMenu.loading")}
                </div>
              ) : projectsError ? (
                <div
                  style={{
                    ...dropdownNoteStyle(),
                    color: "var(--wg-warn, #b94a48)",
                  }}
                >
                  {projectsError}
                </div>
              ) : projects && projects.length > 0 ? (
                projects.map((p) => {
                  const isCurrent = p.id === currentProjectId;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      role="menuitem"
                      onClick={() => {
                        setProjectMenuOpen(false);
                        router.push(`/projects/${p.id}`);
                      }}
                      style={dropdownItemStyle(isCurrent)}
                    >
                      <span
                        style={{
                          flex: 1,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {p.title}
                      </span>
                      {isCurrent && (
                        <span style={{ color: "var(--wg-accent)" }}>✓</span>
                      )}
                    </button>
                  );
                })
              ) : (
                <div style={dropdownNoteStyle()}>
                  {t("projectMenu.empty")}
                </div>
              )}
              <div style={dropdownSeparatorStyle()} />
              <Link
                href="/projects"
                onClick={() => setProjectMenuOpen(false)}
                style={{
                  ...dropdownItemStyle(false),
                  textDecoration: "none",
                  color: "var(--wg-accent)",
                }}
              >
                <span>{t("projectMenu.viewAll")}</span>
              </Link>
            </div>
          )}
        </div>
        <div ref={newMenuRef} style={{ position: "relative" }}>
          <button
            type="button"
            data-testid="topbar-new-button"
            onClick={() => setNewMenuOpen((o) => !o)}
            aria-expanded={newMenuOpen}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 32,
              padding: "0 16px",
              borderRadius: 12,
              background: "var(--wg-accent)",
              color: "#fff",
              border: "none",
              fontSize: 12,
              fontWeight: 700,
              boxShadow: "0 6px 14px rgba(37,99,235,0.22)",
              cursor: "pointer",
            }}
          >
            <span aria-hidden>+</span>
            <span>{t("newCta")}</span>
            <span aria-hidden style={{ fontSize: 9, opacity: 0.7 }}>
              ▾
            </span>
          </button>
          {newMenuOpen && (
            <div
              data-testid="topbar-new-menu"
              role="menu"
              style={topbarDropdownStyle()}
            >
              <Link
                href="/projects"
                onClick={() => setNewMenuOpen(false)}
                style={{
                  ...dropdownItemStyle(false),
                  textDecoration: "none",
                }}
              >
                <span aria-hidden style={{ marginRight: 6 }}>＋</span>
                {t("newMenu.project")}
              </Link>
              <button
                type="button"
                disabled
                title={t("newMenu.comingSoon")}
                style={dropdownItemStyle(false, true)}
              >
                <span aria-hidden style={{ marginRight: 6 }}>＋</span>
                {t("newMenu.agent")}
              </button>
              <button
                type="button"
                disabled
                title={t("newMenu.comingSoon")}
                style={dropdownItemStyle(false, true)}
              >
                <span aria-hidden style={{ marginRight: 6 }}>＋</span>
                {t("newMenu.channel")}
              </button>
              <button
                type="button"
                disabled
                title={t("newMenu.comingSoon")}
                style={dropdownItemStyle(false, true)}
              >
                <span aria-hidden style={{ marginRight: 6 }}>＋</span>
                {t("newMenu.task")}
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

function topbarDropdownStyle(): React.CSSProperties {
  return {
    position: "absolute",
    top: "calc(100% + 6px)",
    right: 0,
    minWidth: 240,
    maxHeight: 360,
    overflowY: "auto",
    padding: 6,
    background: "#fff",
    border: "1px solid var(--wg-line)",
    borderRadius: 10,
    boxShadow: "0 10px 24px rgba(0,0,0,0.10)",
    zIndex: 30,
    display: "flex",
    flexDirection: "column",
    gap: 2,
  };
}

function dropdownItemStyle(
  active: boolean,
  disabled = false,
): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 4,
    padding: "8px 10px",
    background: active ? "var(--wg-accent-soft)" : "transparent",
    border: "none",
    borderRadius: 6,
    textAlign: "left",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.55 : 1,
    fontSize: 13,
    color: "var(--wg-ink)",
    fontFamily: "var(--wg-font-sans)",
    width: "100%",
  };
}

function dropdownNoteStyle(): React.CSSProperties {
  return {
    padding: "8px 10px",
    fontSize: 12,
    color: "var(--wg-ink-soft)",
  };
}

function dropdownSeparatorStyle(): React.CSSProperties {
  return {
    height: 1,
    background: "var(--wg-line)",
    margin: "4px 0",
  };
}
