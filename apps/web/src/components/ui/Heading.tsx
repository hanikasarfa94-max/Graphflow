// Heading — typography primitive. Renders h1/h2/h3 with the
// `--wg-fs-*` tokens + normalized line-height and margin. Anchoring
// via `id` is preserved for documentation-style deep links.

import type { CSSProperties, ReactNode } from "react";

type Props = {
  level: 1 | 2 | 3;
  id?: string;
  children: ReactNode;
  // Optional layout escape hatch — margin / text-align only. Don't
  // override font-size here; pick a different level.
  style?: CSSProperties;
};

function tokenFor(level: 1 | 2 | 3): CSSProperties {
  if (level === 1) {
    return {
      fontSize: "var(--wg-fs-h1)",
      lineHeight: "var(--wg-lh-tight)",
      fontWeight: 600,
      letterSpacing: "-0.01em",
    };
  }
  if (level === 2) {
    return {
      fontSize: "var(--wg-fs-h2)",
      lineHeight: "var(--wg-lh-tight)",
      fontWeight: 600,
    };
  }
  return {
    fontSize: "var(--wg-fs-h3)",
    lineHeight: "var(--wg-lh-tight)",
    fontWeight: 600,
  };
}

export function Heading({ level, id, children, style }: Props) {
  const base: CSSProperties = {
    margin: 0,
    color: "var(--wg-ink)",
    fontFamily: "var(--wg-font-sans)",
    ...tokenFor(level),
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
