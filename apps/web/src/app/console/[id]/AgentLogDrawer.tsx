"use client";

import { useEffect, useRef } from "react";

type SSEEvent = {
  id: string;
  name: string;
  trace_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

export function AgentLogDrawer({
  open,
  events,
  onClose,
}: {
  open: boolean;
  events: SSEEvent[];
  onClose: () => void;
}) {
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [open, events.length]);

  return (
    <section
      data-testid="agent-log-drawer"
      aria-hidden={!open}
      style={{
        gridColumn: "1 / 3",
        gridRow: "3 / 4",
        borderTop: "1px solid var(--wg-line)",
        background: "var(--wg-surface-raised)",
        maxHeight: open ? 280 : 0,
        overflow: "hidden",
        transition: "max-height var(--wg-motion-base)",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 20px",
          borderBottom: "1px solid var(--wg-line-soft)",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
        }}
      >
        <span>Agent log · tail</span>
        <button
          onClick={onClose}
          aria-label="close agent log"
          style={{
            border: "none",
            background: "transparent",
            color: "var(--wg-ink-soft)",
            cursor: "pointer",
            fontFamily: "var(--wg-font-mono)",
            fontSize: 12,
          }}
        >
          close ×
        </button>
      </header>
      <div
        ref={bodyRef}
        style={{
          maxHeight: 240,
          overflow: "auto",
          padding: "10px 20px",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 12,
          lineHeight: 1.6,
        }}
      >
        {events.length === 0 ? (
          <div style={{ color: "var(--wg-ink-faint)" }}>
            Waiting for agent events…
          </div>
        ) : (
          events.map((e) => (
            <div
              key={e.id}
              data-testid="agent-log-row"
              style={{
                display: "grid",
                gridTemplateColumns: "160px 200px 1fr",
                gap: 12,
              }}
            >
              <span style={{ color: "var(--wg-ink-faint)" }}>
                {e.created_at
                  ? new Date(e.created_at).toLocaleTimeString()
                  : "—"}
              </span>
              <span style={{ color: "var(--wg-accent)" }}>{e.name}</span>
              <span
                style={{
                  color: "var(--wg-ink)",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
                title={JSON.stringify(e.payload)}
              >
                {summarizePayload(e.payload)}
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function summarizePayload(payload: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(payload)) {
    if (v === null || v === undefined) continue;
    if (typeof v === "object") continue;
    parts.push(`${k}=${String(v)}`);
    if (parts.length >= 4) break;
  }
  return parts.join("  ");
}
