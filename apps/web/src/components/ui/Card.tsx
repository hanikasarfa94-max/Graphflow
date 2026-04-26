// Card — unified surface primitive. Absorbs the three shapes the app
// kept reinventing:
//
//   1. Status-dashboard panels (components/status/Panel.tsx) — muted
//      small-caps header + bordered body with padded content.
//   2. Home section "notice" rows — padded box with dashed or solid
//      border, used for caught-up / empty states / approvals.
//   3. Stream severity cards (DriftCard, EdgeReplyCard, ScrimmageCards)
//      — padded box with a coloured 3px left border keyed to the
//      signal (terracotta / amber / sage / ink).
//
// Variants:
//   default → raised white surface, hairline border (Panel parity)
//   raised  → same + subtle shadow (for floating states / modals)
//   sunk    → --wg-surface-sunk background (ambient / low priority)
//
// `accent` paints a 3px left border in the signal color. Stick to the
// four house signals — any other colour is a token violation. Passing
// `null` (the default) means no accent rail.
//
// `title` renders the small-caps Panel header; `footer` adds a padded
// bottom strip. Both are optional — if neither is supplied, Card is
// just a padded surface.

import type { CSSProperties, ReactNode } from "react";

type Variant = "default" | "raised" | "sunk";
// Renamed 2026-04-26 with the v1→v2 palette shift (terracotta → blue,
// sage → green). Keeping the prop name `accent` but switching the
// variant names from colour-words to semantic words so future palette
// shifts don't strand misleading prop values. Old names accepted as
// aliases so callers can migrate gradually.
type Accent = "accent" | "amber" | "ok" | null;
type AccentInput = Accent | "terracotta" | "sage";

type Props = {
  variant?: Variant;
  accent?: AccentInput;
  title?: ReactNode;
  subtitle?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  // Escape hatch for layout-only tweaks (margin/grid-column/min-height).
  style?: CSSProperties;
  // When true, the children are rendered without the default 16px
  // padding — useful for tables or lists that manage their own
  // padding. Footer still gets its own padding.
  flush?: boolean;
  // Optional for a11y / testing.
  "data-testid"?: string;
  role?: string;
  "aria-labelledby"?: string;
};

function background(variant: Variant): string {
  switch (variant) {
    case "raised":
      return "var(--wg-surface-raised)";
    case "sunk":
      return "var(--wg-surface-sunk)";
    case "default":
    default:
      return "var(--wg-surface-raised)";
  }
}

function accentColor(accent: AccentInput): string | null {
  // Both old (terracotta/sage) and new (accent/ok) names are accepted
  // so the rename can land without touching every caller in the same
  // commit. Resolve to the same CSS var either way.
  if (accent === "accent" || accent === "terracotta") return "var(--wg-accent)";
  if (accent === "amber") return "var(--wg-amber)";
  if (accent === "ok" || accent === "sage") return "var(--wg-ok)";
  return null;
}

export function Card({
  variant = "default",
  accent = null,
  title,
  subtitle,
  children,
  footer,
  style,
  flush = false,
  "data-testid": testId,
  role,
  "aria-labelledby": ariaLabelledBy,
}: Props) {
  const accentC = accentColor(accent);
  const shell: CSSProperties = {
    background: background(variant),
    border: "1px solid var(--wg-line)",
    borderRadius: "var(--wg-radius)",
    ...(accentC
      ? {
          borderLeft: `3px solid ${accentC}`,
          borderTopLeftRadius: 0,
          borderBottomLeftRadius: 0,
        }
      : null),
    ...(variant === "raised"
      ? { boxShadow: "0 4px 12px rgba(0,0,0,0.04)" }
      : null),
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
    ...style,
  };

  return (
    <section
      style={shell}
      data-testid={testId}
      role={role}
      aria-labelledby={ariaLabelledBy}
    >
      {title ? (
        <header
          style={{
            padding: "12px 16px",
            borderBottom: "1px solid var(--wg-line)",
            background: "var(--wg-surface)",
            display: "flex",
            alignItems: "baseline",
            justifyContent: "space-between",
            gap: 8,
          }}
        >
          <h3
            style={{
              margin: 0,
              fontSize: "var(--wg-fs-label)",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--wg-ink-soft)",
              fontWeight: 600,
              fontFamily: "var(--wg-font-sans)",
            }}
          >
            {title}
          </h3>
          {subtitle ? (
            <span
              style={{
                fontSize: "var(--wg-fs-caption)",
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-soft)",
              }}
            >
              {subtitle}
            </span>
          ) : null}
        </header>
      ) : null}
      <div style={{ padding: flush ? 0 : 16 }}>{children}</div>
      {footer ? (
        <div
          style={{
            padding: "10px 16px",
            borderTop: "1px solid var(--wg-line-soft)",
            background: "var(--wg-surface)",
          }}
        >
          {footer}
        </div>
      ) : null}
    </section>
  );
}

// EmptyState — shared "nothing here yet" surface. Used inside a Card
// body or standalone on home sections. Kept in this file so the
// severity / empty visual grammar travels together.
export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        padding: "16px 12px",
        color: "var(--wg-ink-soft)",
        fontSize: "var(--wg-fs-body)",
        textAlign: "center",
        border: "1px dashed var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      {children}
    </div>
  );
}
