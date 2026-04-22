// Heading — typography primitive. Renders h1/h2/h3 with the
// `--wg-fs-*` tokens + normalized line-height and margin. Anchoring
// via `id` is preserved for documentation-style deep links.
//
// `variant` on level-1 headings selects:
//   * "default" (default) → General Sans, 28px (--wg-fs-h1). Used on
//     routine page titles (settings, dashboards, list views).
//   * "display"           → Instrument Serif, 40px (--wg-fs-hero). Used
//     on landing / marketing / node-detail primary titles (DESIGN.md
//     §Typography: "Display / Hero"). The biggest single taste lever —
//     signals "thoughtful instrument," not "messaging app."
// Level 2 + 3 ignore `variant` — the serif is never used below H1 per
// DESIGN.md: "Never at body scale."

import type { CSSProperties, ReactNode } from "react";

type Variant = "default" | "display";

type Props = {
  level: 1 | 2 | 3;
  variant?: Variant;
  id?: string;
  children: ReactNode;
  // Optional layout escape hatch — margin / text-align only. Don't
  // override font-size here; pick a different level.
  style?: CSSProperties;
};

function tokenFor(level: 1 | 2 | 3, variant: Variant): CSSProperties {
  if (level === 1) {
    if (variant === "display") {
      return {
        fontSize: "var(--wg-fs-hero)",
        lineHeight: "var(--wg-lh-display)",
        fontFamily: "var(--wg-font-display)",
        fontWeight: 400,
        letterSpacing: "-0.01em",
      };
    }
    return {
      fontSize: "var(--wg-fs-h1)",
      lineHeight: "var(--wg-lh-tight)",
      fontFamily: "var(--wg-font-sans)",
      fontWeight: 600,
      letterSpacing: "-0.01em",
    };
  }
  if (level === 2) {
    return {
      fontSize: "var(--wg-fs-h2)",
      lineHeight: "var(--wg-lh-tight)",
      fontFamily: "var(--wg-font-sans)",
      fontWeight: 600,
    };
  }
  return {
    fontSize: "var(--wg-fs-h3)",
    lineHeight: "var(--wg-lh-tight)",
    fontFamily: "var(--wg-font-sans)",
    fontWeight: 600,
  };
}

export function Heading({
  level,
  variant = "default",
  id,
  children,
  style,
}: Props) {
  const base: CSSProperties = {
    margin: 0,
    color: "var(--wg-ink)",
    ...tokenFor(level, variant),
    ...style,
  };
  if (level === 1) {
    return (
      <h1 id={id} style={base}>
        {children}
      </h1>
    );
  }
  if (level === 2) {
    return (
      <h2 id={id} style={base}>
        {children}
      </h2>
    );
  }
  return (
    <h3 id={id} style={base}>
      {children}
    </h3>
  );
}
