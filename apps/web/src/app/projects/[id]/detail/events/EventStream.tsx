"use client";

import { useEffect, useRef, useState } from "react";

type SSEEvent = {
  id: string;
  name: string;
  trace_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

type Connection = "connecting" | "open" | "closed";

export function EventStream({ projectId }: { projectId: string }) {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [status, setStatus] = useState<Connection>("connecting");
  const [err, setErr] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    // Same-origin EventSource — Next rewrites /api to FastAPI, cookie flows
    // through. No token query param needed in this deployment; we support
    // it server-side for completeness but cookies are the primary path.
    const es = new EventSource(
      `/api/events/stream?project_id=${encodeURIComponent(projectId)}`,
      { withCredentials: true },
    );
    setStatus("connecting");

    es.onopen = () => setStatus("open");
    es.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (data.type === "hello") return;
        setEvents((prev) => {
          if (prev.some((e) => e.id === data.id)) return prev;
          return [...prev, data as SSEEvent].slice(-200);
        });
      } catch {
        // Ignore malformed frame — server always sends JSON.
      }
    };
    es.onerror = () => {
      setStatus("closed");
      setErr("stream disconnected — the browser will retry");
    };
    return () => es.close();
  }, [projectId]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          padding: "10px 14px",
          background: "var(--wg-surface)",
          borderBottom: "1px solid var(--wg-line)",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 12,
          color: "var(--wg-ink-soft)",
        }}
      >
        <span>
          <StatusDot status={status} />{" "}
          <span data-testid="sse-status">{status}</span>
          {err && status !== "open" ? ` · ${err}` : ""}
        </span>
        <span>{events.length} events</span>
      </div>

      <div
        ref={containerRef}
        style={{
          height: 560,
          overflowY: "auto",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 12,
          padding: "8px 0",
        }}
      >
        {events.length === 0 ? (
          <div
            style={{
              padding: 24,
              textAlign: "center",
              color: "var(--wg-ink-soft)",
            }}
          >
            Waiting for events…
          </div>
        ) : (
          events.map((e) => (
            <div
              key={e.id}
              style={{
                padding: "6px 14px",
                borderBottom: "1px dashed var(--wg-line)",
                lineHeight: 1.5,
              }}
            >
              <div style={{ color: "var(--wg-ink-soft)" }}>
                {new Date(e.created_at).toLocaleTimeString()} ·{" "}
                <span style={{ color: "var(--wg-ink)" }}>{e.name}</span>
                {e.trace_id ? ` · ${e.trace_id.slice(0, 8)}` : ""}
              </div>
              {Object.keys(e.payload).length > 0 && (
                <div
                  style={{
                    color: "var(--wg-ink)",
                    paddingLeft: 12,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {JSON.stringify(e.payload)}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: Connection }) {
  const color =
    status === "open"
      ? "#7ab87a"
      : status === "connecting"
        ? "#d97706"
        : "var(--wg-accent)";
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: color,
        marginRight: 6,
        verticalAlign: "middle",
      }}
    />
  );
}
