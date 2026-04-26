// PageHeader — the kicker + h1 + subtitle pattern that the html2
// redesign uses for every page (Status, Org, KB, Skills, Inbox, Audit,
// Renders). Standardising on one component means future pages
// inherit the rhythm without re-deriving spacing or font sizing.
//
// Anatomy (top → bottom):
//   <kicker>  small uppercase mono · accent-tinted
//   <h1>      display-serif page title
//   <subtitle> body-size muted prose, max ~760px
//   right-slot (optional) — actions or a stamp aligned to the right
//
// Use this from server components — no client state, just props.

import type { ReactNode } from "react";

import { Heading, Text } from "./index";

export function PageHeader({
  kicker,
  title,
  subtitle,
  right,
}: {
  kicker?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  right?: ReactNode;
}) {
  return (
    <header
      style={{
        display: "flex",
        alignItems: "flex-end",
        justifyContent: "space-between",
        gap: 16,
        margin: "8px 0 24px",
        flexWrap: "wrap",
      }}
    >
      <div style={{ minWidth: 0, flex: 1 }}>
        {kicker ? (
          <div
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "var(--wg-accent)",
              fontWeight: 600,
              marginBottom: 6,
            }}
          >
            {kicker}
          </div>
        ) : null}
        <Heading
          level={1}
          variant="display"
          style={{ margin: 0, letterSpacing: "-0.02em" }}
        >
          {title}
        </Heading>
        {subtitle ? (
          <Text
            variant="body"
            style={{
              margin: "8px 0 0",
              color: "var(--wg-ink-soft)",
              maxWidth: 760,
              lineHeight: 1.6,
            }}
          >
            {subtitle}
          </Text>
        ) : null}
      </div>
      {right ? (
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {right}
        </div>
      ) : null}
    </header>
  );
}
