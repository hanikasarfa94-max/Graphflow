"use client";

// Button — the one button in the app. Replaces the three CSSProperties
// objects (`primaryBtn`, `ghostBtn`, `amberBtn`) that were copy-pasted
// across ChatPane/cards.tsx/ScrimmageCards/DriftCard/RouteProposalCard
// + every page-level CTA that re-invented the pattern from scratch.
//
// Variants follow the house signal-color rule:
//   primary → terracotta (crystallization / commit) — the default CTA
//   ghost   → neutral outlined (cancel / "not now")
//   amber   → amber outline (escalation / medium severity)
//   danger  → filled amber → rare; reserved for irreversible actions
//   link    → underline-less text link in accent color
//
// Sizes are `sm` (compact, 11px label + 4/10px padding — replaces the
// "followUpBtn" / "discussBtn" micro-buttons inside cards) and `md`
// (default, 12px label + 6/12px padding). The props surface is kept
// intentionally small — anything richer (icon slots, full-width, etc.)
// can be added later when a concrete need shows up; inventing it now
// would just recreate the sprawl this primitive was built to kill.

import type {
  ButtonHTMLAttributes,
  CSSProperties,
  ReactNode,
} from "react";

type Variant = "primary" | "ghost" | "amber" | "danger" | "link";
type Size = "sm" | "md";

type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> & {
  variant?: Variant;
  size?: Size;
  children: ReactNode;
  // Allow a narrow style override for layout-only concerns (margin,
  // align-self, etc.). Font/color/padding overrides are discouraged —
  // if you need them, pick a different variant instead.
  style?: CSSProperties;
};

function baseStyle(size: Size): CSSProperties {
  if (size === "sm") {
    return {
      padding: "4px 10px",
      fontSize: "var(--wg-fs-caption)",
      fontFamily: "var(--wg-font-mono)",
      fontWeight: 600,
      borderRadius: "var(--wg-radius-sm)",
      cursor: "pointer",
      lineHeight: 1.2,
      letterSpacing: "0.02em",
    };
  }
  return {
    padding: "6px 12px",
    fontSize: "var(--wg-fs-label)",
    fontFamily: "var(--wg-font-sans)",
    fontWeight: 600,
    borderRadius: "var(--wg-radius)",
    cursor: "pointer",
    lineHeight: 1.3,
  };
}

function variantStyle(variant: Variant): CSSProperties {
  switch (variant) {
    case "primary":
      return {
        background: "var(--wg-accent)",
        color: "#fff",
        border: "1px solid var(--wg-accent)",
      };
    case "ghost":
      return {
        background: "transparent",
        color: "var(--wg-ink-soft)",
        border: "1px solid var(--wg-line)",
      };
    case "amber":
      return {
        background: "transparent",
        color: "var(--wg-amber)",
        border: "1px solid var(--wg-amber)",
      };
    case "danger":
      return {
        background: "var(--wg-amber)",
        color: "#fff",
        border: "1px solid var(--wg-amber)",
      };
    case "link":
      return {
        background: "transparent",
        color: "var(--wg-accent)",
        border: "none",
        padding: 0,
        fontFamily: "var(--wg-font-mono)",
        textDecoration: "none",
      };
  }
}

export function Button({
  variant = "primary",
  size = "md",
  disabled,
  type = "button",
  children,
  style,
  ...rest
}: Props) {
  const merged: CSSProperties = {
    ...baseStyle(size),
    ...variantStyle(variant),
    ...(disabled ? { opacity: 0.55, cursor: "not-allowed" } : null),
    ...style,
  };
  return (
    <button type={type} disabled={disabled} style={merged} {...rest}>
      {children}
    </button>
  );
}
