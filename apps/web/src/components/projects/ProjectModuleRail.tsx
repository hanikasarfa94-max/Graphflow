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

import { MODULE_MATCHERS } from "./projectModuleRail.matchers";

interface Props {
  projectId: string;
}

// Icon-by-key lookup. The matchers file is pure (no JSX-friendly
// strings) — keep visual glyph mapping in the component layer.
const MODULE_ICONS: Record<string, string> = {
  stream: "💬",
  team: "🏛",
  status: "📋",
  kb: "📚",
  tasks: "✓",
  reviews: "🛡",
  audit: "📊",
  skills: "🎨",
  meetings: "📅",
  renders: "📤",
  settings: "⚙",
};

export function ProjectModuleRail({ projectId }: Props) {
  const pathname = usePathname() ?? "";
  const t = useTranslations("projects.moduleRail");
  const base = `/projects/${projectId}`;

  const modules = MODULE_MATCHERS.map((m) => ({
    key: m.key,
    href: m.href(base),
    icon: MODULE_ICONS[m.key] ?? "•",
    matches: (p: string) => m.matches(p, base),
  }));

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
