"use client";

// RoutedInboxBadge — Phase Q sidebar entry for routed inbound.
//
// Renders as a sidebar Link item: "✦ Routed inbox (N)" with the count
// highlighted. F.17: dropped the dual-click dance (single → drawer,
// double → page). Single-click goes straight to /inbox. The 220ms
// timer that used to make every click feel laggy is gone. The
// per-project notification bell at top-right covers the
// quick-glance use case the drawer used to serve.
//
// Count of zero still renders the item — users need to be able to
// reach the inbox to see history even when empty.
//
// Kept as a button (not a Link) because the AppShellClient still
// passes a no-op onClick callback for symmetry with the legacy
// drawer-opener slot. We just navigate manually instead of opening it.

import Link from "next/link";
import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";

const base: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "7px 12px",
  fontSize: 13,
  width: "100%",
  textDecoration: "none",
  textAlign: "left",
  color: "var(--wg-ink)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontFamily: "inherit",
  lineHeight: 1.3,
};

export function RoutedInboxBadge({
  count,
}: {
  count: number;
  // onClick kept on the prop signature for backward-compat with
  // AppSidebar's prop wiring; the badge no longer uses it (we
  // navigate to /inbox directly). Removing requires touching
  // AppShellClient + AppSidebar, defer to a follow-up.
  onClick?: () => void;
}) {
  const t = useTranslations("shell");
  const tInbox = useTranslations("inbox");
  const hasPending = count > 0;

  return (
    <Link
      href="/inbox"
      data-testid="sidebar-inbox-badge"
      data-count={count}
      aria-label={
        hasPending ? tInbox("openDrawerN", { n: count }) : tInbox("openDrawer")
      }
      style={{
        ...base,
        color: hasPending ? "var(--wg-accent)" : "var(--wg-ink)",
        fontWeight: hasPending ? 600 : 400,
      }}
    >
      <span aria-hidden>✦</span>
      <span>{t("routedInbox")}</span>
      {count > 0 && (
        <span
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
      )}
    </Link>
  );
}
