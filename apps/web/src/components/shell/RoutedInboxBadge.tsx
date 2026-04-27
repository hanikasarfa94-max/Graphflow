"use client";

// RoutedInboxBadge — Phase Q sidebar entry for routed inbound.
//
// Renders as a sidebar item: "✦ Routed inbox (N)" with the count
// highlighted. Click pattern (per html2 redesign):
//   single-click → opens the RoutedInboundDrawer for fast triage
//   double-click → navigates to the full /inbox surface for at-pace work
//
// Count of zero still renders the item — users need to be able to open
// the drawer to see history even when empty.

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, type CSSProperties } from "react";

const base: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "7px 12px",
  fontSize: 13,
  width: "100%",
  background: "transparent",
  border: "none",
  cursor: "pointer",
  textAlign: "left",
  color: "var(--wg-ink)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontFamily: "inherit",
  lineHeight: 1.3,
};

export function RoutedInboxBadge({
  count,
  onClick,
}: {
  count: number;
  onClick: () => void;
}) {
  const t = useTranslations("shell");
  const tInbox = useTranslations("inbox");
  const router = useRouter();

  // Distinguish single- vs double-click without firing the drawer
  // twice on a real double-click. We delay the single-click side-effect
  // by ~220ms — long enough that a follow-up click cancels it. If the
  // user only single-clicked, the timeout fires and the drawer opens.
  // Threshold tuned to feel responsive without misfiring.
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hasPending = count > 0;

  const handleClick = () => {
    if (clickTimer.current) {
      clearTimeout(clickTimer.current);
      clickTimer.current = null;
    }
    clickTimer.current = setTimeout(() => {
      clickTimer.current = null;
      onClick();
    }, 220);
  };

  const handleDoubleClick = () => {
    if (clickTimer.current) {
      clearTimeout(clickTimer.current);
      clickTimer.current = null;
    }
    router.push("/inbox");
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      data-testid="sidebar-inbox-badge"
      data-count={count}
      aria-label={
        hasPending ? tInbox("openDrawerN", { n: count }) : tInbox("openDrawer")
      }
      title={tInbox("doubleClickHint")}
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
    </button>
  );
}
