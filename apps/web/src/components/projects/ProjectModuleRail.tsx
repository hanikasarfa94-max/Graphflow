"use client";

// ProjectModuleRail — port of workgraph-ts-prototype's Rail (App.tsx
// Rail + railItems) adapted to a horizontal icon strip.
//
// Owns surface-nav (left) AND the scope-pill widget (right). Folding
// the scope pills in here let us delete the separate ProjectBar row —
// project-name text was redundant with the Topbar breadcrumb, and the
// surface-crumb was redundant with the active rail tab below it. The
// pills were the only functional widget that needed a home, so they
// ride along on this strip now.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { ScopeTierPills } from "@/components/stream/ScopeTierPills";

interface Props {
  projectId: string;
}

interface ModuleEntry {
  key: string;
  href: string;
  icon: string;
  // Predicate for "this module owns the current pathname". For most
  // entries it's a startsWith check; the personal-stream entry is
  // exact-match because /projects/[id] is the prefix of every other
  // project route.
  matches: (pathname: string) => boolean;
}

export function ProjectModuleRail({ projectId }: Props) {
  const pathname = usePathname() ?? "";
  const t = useTranslations("projects.moduleRail");
  const base = `/projects/${projectId}`;

  const modules: ModuleEntry[] = [
    {
      key: "stream",
      href: base,
      icon: "💬",
      matches: (p) =>
        p === base ||
        p === `${base}/` ||
        p.startsWith(`${base}/rooms/`),
    },
    {
      key: "team",
      href: `${base}/team`,
      icon: "🏛",
      matches: (p) => p.startsWith(`${base}/team`),
    },
    {
      key: "status",
      href: `${base}/status`,
      icon: "📋",
      matches: (p) => p.startsWith(`${base}/status`),
    },
    {
      key: "kb",
      href: `${base}/kb`,
      icon: "📚",
      matches: (p) => p.startsWith(`${base}/kb`),
    },
    {
      // Tasks gets a top-level rail entry so users have a one-click
      // path to "what do I need to do today?". The same view is also
      // reachable as the Tasks sub-tab inside Audit, but the QA
      // feedback "task view was missing" was about discoverability —
      // hiding tasks one tab deep behind Audit was a real bug.
      key: "tasks",
      href: `${base}/detail/tasks`,
      icon: "✓",
      matches: (p) => p.startsWith(`${base}/detail/tasks`),
    },
    {
      key: "audit",
      // Audit lands on the graph view as the canonical entry — same
      // convention the prototype's auditView uses. The Tasks sub-tab
      // here is unchanged; the new top-level Tasks entry above is an
      // additional shortcut, not a redirect.
      href: `${base}/detail/graph`,
      icon: "📊",
      matches: (p) =>
        p.startsWith(`${base}/detail`) &&
        !p.startsWith(`${base}/detail/tasks`),
    },
    {
      key: "skills",
      href: `${base}/skills`,
      icon: "🎨",
      matches: (p) => p.startsWith(`${base}/skills`),
    },
    {
      key: "meetings",
      href: `${base}/meetings`,
      icon: "📅",
      matches: (p) => p.startsWith(`${base}/meetings`),
    },
    {
      key: "renders",
      href: `${base}/renders`,
      icon: "📤",
      matches: (p) => p.startsWith(`${base}/renders`),
    },
    {
      key: "settings",
      href: `${base}/settings`,
      icon: "⚙",
      matches: (p) => p.startsWith(`${base}/settings`),
    },
  ];

  return (
    <nav
      data-testid="project-module-rail"
      aria-label={t("ariaLabel")}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 2,
        padding: "6px 14px",
        borderBottom: "1px solid var(--wg-line)",
        background: "#fff",
        overflowX: "auto",
        WebkitOverflowScrolling: "touch",
      }}
    >
      {modules.map((m) => {
        const active = m.matches(pathname);
        return (
          <Link
            key={m.key}
            href={m.href}
            data-testid={`module-rail-${m.key}`}
            data-active={active ? "true" : undefined}
            aria-current={active ? "page" : undefined}
            title={t(`module.${m.key}`)}
            style={moduleLinkStyle(active)}
          >
            <span aria-hidden style={{ fontSize: 14, lineHeight: 1 }}>
              {m.icon}
            </span>
            <span style={{ fontSize: 12, whiteSpace: "nowrap" }}>
              {t(`module.${m.key}`)}
            </span>
          </Link>
        );
      })}
      <div style={{ flex: 1 }} />
      <ScopeTierPills projectKey={`project:${projectId}`} />
    </nav>
  );
}

function moduleLinkStyle(active: boolean): React.CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "4px 10px",
    borderRadius: 6,
    textDecoration: "none",
    color: active ? "var(--wg-accent)" : "var(--wg-ink-soft)",
    background: active ? "var(--wg-accent-soft)" : "transparent",
    fontWeight: active ? 600 : 400,
    transition: "background 120ms, color 120ms",
    flexShrink: 0,
  };
}
