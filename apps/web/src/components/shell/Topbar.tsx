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
//   * "+ New" — links to /projects (where the new-project modal
//     lives). Once we have a global new-anything menu, this becomes
//     the dropdown.
//
// Pure client component. Reads pathname + the AppShell context for
// inbox count + open handler.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

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

function buildCrumbs(pathname: string): string {
  const segs = pathname
    .split("/")
    .filter(Boolean)
    .map((s) => (isOpaqueId(s) ? "·" : SEGMENT_LABELS[s] ?? s));
  if (segs.length === 0) return "WORKGRAPH / HOME";
  return ["WORKGRAPH", ...segs.map((s) => s.toUpperCase())].join(" / ");
}

export function Topbar() {
  const t = useTranslations("topbar");
  const pathname = usePathname() ?? "/";
  const { inboxCount, openInbox } = useAppShell();

  const crumbs = buildCrumbs(pathname);

  return (
    <header
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        padding: "16px 28px 14px",
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
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "0 14px",
            height: 36,
            borderRadius: 999,
            border: "1px solid var(--wg-line)",
            background: "rgba(255,255,255,0.84)",
            color: "var(--wg-ink-soft)",
            fontSize: 12,
            minWidth: 220,
          }}
        >
          <span style={{ fontFamily: "var(--wg-font-mono)" }}>⌕</span>
          <span style={{ flex: 1 }}>{t("searchPlaceholder")}</span>
          <kbd
            style={{
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              background: "var(--wg-surface-sunk)",
              border: "1px solid var(--wg-line)",
              borderRadius: 4,
              padding: "1px 5px",
              color: "var(--wg-ink-faint)",
            }}
          >
            ⌘K
          </kbd>
        </div>
        <button
          type="button"
          onClick={openInbox}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            height: 36,
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
        <Link
          href="/projects"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            height: 36,
            padding: "0 16px",
            borderRadius: 12,
            background: "var(--wg-accent)",
            color: "#fff",
            textDecoration: "none",
            fontSize: 12,
            fontWeight: 700,
            boxShadow: "0 6px 14px rgba(37,99,235,0.22)",
          }}
        >
          <span aria-hidden>+</span>
          <span>{t("newCta")}</span>
        </Link>
      </div>
    </header>
  );
}
