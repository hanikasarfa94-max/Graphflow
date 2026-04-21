// Text — typography primitive for non-heading copy. Replaces ad-hoc
// `<p style={{ fontSize: 13, color: "var(--wg-ink-soft)" }}>…</p>`
// that was written dozens of times.
//
// Variants:
//   body    → 13px sans, normal line-height, default ink. The default.
//   label   → 12px sans, used for form labels and dense metadata.
//   caption → 11px mono, used for timestamps / tags / annotations.
//   mono    → same as body but in the mono stack (for IDs / code).
//
// `muted` swaps the colour to ink-soft so short callouts ("your
// display name", "last generated 2h ago") can stay inline without
// a second wrapping <span>.

import type { CSSProperties, ElementType, ReactNode } from "react";

type Variant = "body" | "label" | "caption" | "mono";

type Props = {
  variant?: Variant;
  muted?: boolean;
  // Render as a span by default — safest for inline usage. Callers
  // that want a block paragraph pass `as="p"` or `as="div"`.
  as?: ElementType;
  children: ReactNode;
  style?: CSSProperties;
  title?: string;
  id?: string;
  "data-testid"?: string;
};

function variantStyle(variant: Variant): CSSProperties {
  switch (variant) {
    case "label":
      return {
        fontSize: "var(--wg-fs-label)",
        fontFamily: "var(--wg-font-sans)",
        lineHeight: "var(--wg-lh-normal)",
      };
    case "caption":
      return {
        fontSize: "var(--wg-fs-caption)",
        fontFamily: "var(--wg-font-mono)",
        lineHeight: "var(--wg-lh-normal)",
        letterSpacing: "0.02em",
      };
    case "mono":
      return {
        fontSize: "var(--wg-fs-body)",
        fontFamily: "var(--wg-font-mono)",
        lineHeight: "var(--wg-lh-normal)",
      };
    case "body":
    default:
      return {
        fontSize: "var(--wg-fs-body)",
        fontFamily: "var(--wg-font-sans)",
        lineHeight: "var(--wg-lh-normal)",
      };
  }
}

export function Text({
  variant = "body",
  muted = false,
  as: Tag = "span",
  children,
  style,
  title,
  id,
  "data-testid": testId,
}: Props) {
  const merged: CSSProperties = {
    margin: 0,
    color: muted ? "var(--wg-ink-soft)" : "var(--wg-ink)",
    ...variantStyle(variant),
    ...style,
  };
  return (
    <Tag style={merged} title={title} id={id} data-testid={testId}>
      {children}
    </Tag>
  );
}
