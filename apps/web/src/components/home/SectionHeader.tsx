import type { ReactNode } from "react";

// Small, consistent section header used across the personal home. Keeps
// the visual rhythm uniform so the eye can scan between sections quickly.
// Uses the caption mono scale directly (--wg-fs-caption). Wrapping it in
// <Heading> would be wrong — semantically this is an h2 but visually it
// wants the mono-caps treatment the Heading primitive intentionally
// doesn't do.
export function SectionHeader({
  title,
  right,
  subdued = false,
}: {
  title: string;
  right?: ReactNode;
  subdued?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        marginBottom: 12,
        gap: 12,
      }}
    >
      <h2
        style={{
          fontSize: "var(--wg-fs-caption)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: subdued ? "var(--wg-ink-faint)" : "var(--wg-ink-soft)",
          fontFamily: "var(--wg-font-mono)",
          margin: 0,
          fontWeight: 600,
        }}
      >
        {title}
      </h2>
      {right ? <div>{right}</div> : null}
    </div>
  );
}
