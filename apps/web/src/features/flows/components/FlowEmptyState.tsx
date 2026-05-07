"use client";

// FlowEmptyState — extracted from components/rooms/FlowsPanelBody.tsx
// during Phase E (Architecture Organization Pass v1).
//
// Renders the dashed-bordered placeholder used inside each bucket
// section for three indistinguishable-at-a-glance states: loading,
// error, and empty. The variant flag only changes the colour and
// emphasis; layout stays identical so the surface doesn't reflow as
// a fetch resolves.
//
// Behaviour and aesthetic must match the original `Empty` helper
// byte-for-byte — Phase E's mandate is decomposition without redesign.

import type { CSSProperties } from "react";

export interface FlowEmptyStateProps {
  text: string;
  variant?: "error";
}

export function FlowEmptyState({ text, variant }: FlowEmptyStateProps) {
  const isError = variant === "error";
  return (
    <p
      data-testid={isError ? "flows-bucket-error" : "flows-bucket-empty"}
      style={isError ? errorStateStyle : idleStateStyle}
    >
      {text}
    </p>
  );
}

// Named style objects (not inline literals) so the design-system
// guardrail (apps/web/src/lib/design-system.test.ts) treats them as
// reusable tokens rather than ad-hoc smell. Every colour references a
// `--wg-*` variable from globals.css; no hex literals live in this
// file.

const baseStateStyle: CSSProperties = {
  margin: 0,
  padding: "8px 10px",
  fontSize: 12,
  background: "var(--wg-surface)",
  border: "1px dashed var(--wg-line)",
  borderRadius: "var(--wg-radius)",
};

const idleStateStyle: CSSProperties = {
  ...baseStateStyle,
  color: "var(--wg-ink-soft)",
  fontStyle: "italic",
};

const errorStateStyle: CSSProperties = {
  ...baseStateStyle,
  color: "var(--wg-accent)",
  fontStyle: "normal",
};
