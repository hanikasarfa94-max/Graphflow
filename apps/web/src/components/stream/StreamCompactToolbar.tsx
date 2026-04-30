// StreamCompactToolbar — Batch F.4 redesign chrome.
//
// Slim bar that sits above StreamView/PersonalStream on the chat
// surfaces (my-thread, team-room) per the html2 .compact-chat-toolbar
// pattern. Bold title + mono meta string on the left, optional action
// slot on the right. Server component — no state, just composition.

import type { ReactNode } from "react";

export function StreamCompactToolbar({
  title,
  meta,
  actions,
}: {
  title: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        margin: "16px 28px 12px",
        padding: "10px 16px",
        background: "rgba(255,253,248,0.78)",
        border: "1px solid var(--wg-line)",
        borderRadius: 16,
        boxShadow: "0 6px 14px rgba(30,64,175,0.05)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          minWidth: 0,
        }}
      >
        <span
          style={{
            fontSize: 15,
            fontWeight: 700,
            color: "var(--wg-ink)",
            letterSpacing: "-0.01em",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {title}
        </span>
        {meta ? (
          <span
            style={{
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {meta}
          </span>
        ) : null}
      </div>
      {actions ? (
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {actions}
        </div>
      ) : null}
    </div>
  );
}
