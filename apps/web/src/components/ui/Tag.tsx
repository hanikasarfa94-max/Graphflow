// Tag — soft-tinted pill primitive.
//
// The redesign relies heavily on these for status / classification /
// severity ribbons (red = critical / risk, amber = checkpoint, green
// = ok / committed, blue = brand / info, neutral = default). Single
// home for the styling so the visual grammar travels together.

import type { CSSProperties, ReactNode } from "react";

type Tone = "neutral" | "accent" | "amber" | "ok" | "danger";
type Size = "sm" | "md";

const TINT: Record<Tone, { bg: string; fg: string; border: string }> = {
  neutral: {
    bg: "var(--wg-surface-sunk)",
    fg: "var(--wg-ink-soft)",
    border: "var(--wg-line)",
  },
  accent: {
    bg: "var(--wg-accent-soft)",
    fg: "var(--wg-accent)",
    border: "transparent",
  },
  amber: {
    bg: "var(--wg-amber-soft)",
    fg: "var(--wg-amber)",
    border: "transparent",
  },
  ok: {
    bg: "var(--wg-ok-soft)",
    fg: "var(--wg-ok)",
    border: "transparent",
  },
  danger: {
    bg: "rgba(220, 38, 38, 0.10)",
    fg: "var(--wg-danger)",
    border: "transparent",
  },
};

export function Tag({
  tone = "neutral",
  size = "sm",
  children,
  style,
}: {
  tone?: Tone;
  size?: Size;
  children: ReactNode;
  style?: CSSProperties;
}) {
  const t = TINT[tone];
  const sizing =
    size === "md"
      ? { padding: "4px 10px", fontSize: 12 }
      : { padding: "2px 8px", fontSize: 11 };
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        borderRadius: "var(--wg-radius-full)",
        background: t.bg,
        color: t.fg,
        border: `1px solid ${t.border}`,
        fontFamily: "var(--wg-font-mono)",
        fontWeight: 600,
        lineHeight: 1.3,
        whiteSpace: "nowrap",
        ...sizing,
        ...style,
      }}
    >
      {children}
    </span>
  );
}
