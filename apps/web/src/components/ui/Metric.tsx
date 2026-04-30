// Metric — single number + label primitive used by every dashboard
// strip in the html2 redesign (Status, Projects portfolio, Profile,
// Home Pulse). Big display number on top, small mono label below.
//
// Tones:
//   neutral — bordered white card with the standard surface gradient
//   accent  — soft-blue tinted (positive emphasis, e.g. "active")
//   amber   — soft-amber tinted (attention, e.g. "needing review")
//   danger  — soft-red tinted (alarm, e.g. "single-point risks")
//   onDark  — for the navy pulse card on the home hero — translucent
//             white surface, light label
//
// All tones use the same dimensions so a row of mixed-tone metrics
// stays a clean strip.

import type { CSSProperties, ReactNode } from "react";

type Tone = "neutral" | "accent" | "amber" | "danger" | "onDark";

const TONE: Record<
  Tone,
  { bg: string; border: string; value: string; label: string }
> = {
  neutral: {
    bg: "var(--wg-surface)",
    border: "var(--wg-line)",
    value: "var(--wg-ink)",
    label: "var(--wg-ink-soft)",
  },
  accent: {
    bg: "var(--wg-accent-soft)",
    border: "transparent",
    value: "var(--wg-accent)",
    label: "var(--wg-accent)",
  },
  amber: {
    bg: "var(--wg-amber-soft)",
    border: "transparent",
    value: "var(--wg-amber)",
    label: "var(--wg-amber)",
  },
  danger: {
    bg: "rgba(220, 38, 38, 0.08)",
    border: "transparent",
    value: "var(--wg-danger)",
    label: "var(--wg-danger)",
  },
  onDark: {
    bg: "rgba(255,255,255,0.10)",
    border: "rgba(255,255,255,0.14)",
    value: "#ffffff",
    label: "rgba(199,208,224,0.82)",
  },
};

export function Metric({
  value,
  label,
  tone = "neutral",
  hint,
  style,
}: {
  value: number | string;
  label: ReactNode;
  tone?: Tone;
  /** Optional sub-label shown beneath the main label in slightly
   *  smaller text. Use for "(7d)" / "open only" framing. */
  hint?: ReactNode;
  style?: CSSProperties;
}) {
  const t = TONE[tone];
  return (
    <div
      style={{
        background: t.bg,
        border: `1px solid ${t.border}`,
        borderRadius: 14,
        padding: "12px 14px",
        minWidth: 0,
        ...style,
      }}
    >
      <div
        style={{
          fontSize: 26,
          fontWeight: 600,
          lineHeight: 1.1,
          letterSpacing: "-0.02em",
          color: t.value,
          fontFamily: "var(--wg-font-sans)",
        }}
      >
        {value}
      </div>
      <div
        style={{
          marginTop: 4,
          fontSize: 11,
          color: t.label,
          fontFamily: "var(--wg-font-mono)",
          letterSpacing: "0.04em",
        }}
      >
        {label}
      </div>
      {hint ? (
        <div
          style={{
            marginTop: 2,
            fontSize: 10,
            color: tone === "onDark" ? "rgba(199,208,224,0.6)" : "var(--wg-ink-faint)",
          }}
        >
          {hint}
        </div>
      ) : null}
    </div>
  );
}
