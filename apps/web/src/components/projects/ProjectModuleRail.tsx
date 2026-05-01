"use client";

// ProjectModuleRail — port of workgraph-ts-prototype's Rail (App.tsx
// Rail + railItems) adapted to a horizontal icon strip.
//
// Sits below ProjectBar in the global project layout. Lets users jump
// between project-scoped surfaces (stream / team room / status / KB /
// audit / skills / meetings / renders / settings) without going up
// through AppSidebar's global-scope navigation.
//
// The prototype renders this as a vertical icon column on the far
// left. We render horizontally because adding a vertical column
// would shift every existing page's content width — high regression
// risk for marginal product win. Horizontal is additive (~32px
// vertical real estate) and matches the existing ProjectBar
// layout pattern.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

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
      key: "audit",
      // Audit lands on the graph view as the canonical entry — same
      // convention the prototype's auditView uses.
      href: `${base}/detail/graph`,
      icon: "📊",
      matches: (p) => p.startsWith(`${base}/detail`),
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
        padding: "4px 14px",
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
