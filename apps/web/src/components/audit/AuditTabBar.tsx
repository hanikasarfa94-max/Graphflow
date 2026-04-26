"use client";

// AuditTabBar — Batch B IA reshape.
//
// Per the home_redesign_html2.html spec: the audit domain (graph,
// plan, tasks, risks, decisions) is ONE page with internal tabs —
// "the only place tabs are allowed in the per-project nav, because
// these belong to the same audit domain." Other /detail subpages
// (clarify, conflicts, delivery, events, im) are NOT audit; the
// tab bar self-hides on those routes so they keep their existing
// chrome.
//
// Implementation note: we kept the 5 separate routes (cheap, no
// content moves, browser back/forward + bookmarks all work). The
// "single page with tabs" experience is provided by this bar
// rendered at the layout level — visually it's one page with five
// switchable views.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

const AUDIT_TABS = [
  ["graph", "shell.project.detail_graph"],
  ["plan", "shell.project.detail_plan"],
  ["tasks", "shell.project.detail_tasks"],
  ["risks", "shell.project.detail_risks"],
  ["decisions", "shell.project.detail_decisions"],
] as const;

type AuditTab = (typeof AUDIT_TABS)[number][0];

const AUDIT_SLUGS = new Set<string>(AUDIT_TABS.map((t) => t[0]));

export function AuditTabBar({ projectId }: { projectId: string }) {
  const t = useTranslations();
  const pathname = usePathname() ?? "";

  // Self-hide on non-audit /detail pages (clarify/conflicts/delivery/
  // events/im). Match the slug right after /detail/ in the path.
  const match = pathname.match(/\/projects\/[^/]+\/detail\/([^/?#]+)/);
  const currentSlug = match?.[1] ?? "";
  if (!AUDIT_SLUGS.has(currentSlug)) {
    return null;
  }

  return (
    <nav
      aria-label="Audit view"
      data-testid="audit-tab-bar"
      style={{
        display: "flex",
        gap: 8,
        flexWrap: "wrap",
        padding: "12px 0 18px",
        borderBottom: "1px solid var(--wg-line-soft)",
        marginBottom: 18,
      }}
    >
      {AUDIT_TABS.map(([slug, key]) => {
        const href = `/projects/${projectId}/detail/${slug}`;
        const active = currentSlug === slug;
        return (
          <Link
            key={slug}
            href={href}
            aria-current={active ? "page" : undefined}
            style={{
              padding: "7px 14px",
              borderRadius: 999,
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
              fontWeight: 600,
              letterSpacing: "0.04em",
              textDecoration: "none",
              border: `1px solid ${active ? "var(--wg-ink)" : "var(--wg-line)"}`,
              background: active ? "var(--wg-ink)" : "var(--wg-surface)",
              color: active ? "var(--wg-surface-raised)" : "var(--wg-ink-soft)",
              transition: "background 140ms, color 140ms, border-color 140ms",
            }}
          >
            {t(key as never)}
          </Link>
        );
      })}
    </nav>
  );
}
