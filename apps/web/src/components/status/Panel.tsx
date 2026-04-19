import type { ReactNode } from "react";

// Shared visual shell for a status-dashboard panel. Muted header, neutral
// card body, consistent spacing. Server component — no state.
export function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  return (
    <section
      style={{
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
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
        <h2
          style={{
            margin: 0,
            fontSize: 12,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wg-ink-soft)",
            fontWeight: 600,
          }}
        >
          {title}
        </h2>
        {subtitle ? (
          <span
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
            }}
          >
            {subtitle}
          </span>
        ) : null}
      </header>
      <div style={{ padding: 16 }}>{children}</div>
    </section>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        padding: "16px 12px",
        color: "var(--wg-ink-soft)",
        fontSize: 13,
        textAlign: "center",
        border: "1px dashed var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      {children}
    </div>
  );
}
