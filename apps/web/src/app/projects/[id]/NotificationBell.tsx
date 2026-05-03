"use client";

import { useEffect, useRef, useState } from "react";
import { formatIso } from "@/lib/time";

type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string;
  target_kind: string | null;
  target_id: string | null;
  read_at: string | null;
  created_at: string;
};

type NotifListResponse = {
  items: Notification[];
  unread_count: number;
};

// Polls /api/notifications every 20s and renders a bell with an unread
// badge. WS push also nudges us via a custom event (see ChatPane — future
// wiring). For now: polling is the single source of truth.
export function NotificationBell({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch("/api/notifications?limit=20", {
          credentials: "include",
          cache: "no-store",
        });
        if (!res.ok) return;
        const data = (await res.json()) as NotifListResponse;
        if (cancelled) return;
        setItems(data.items);
        setUnread(data.unread_count);
      } catch {
        // Ignore transient network failures.
      }
    };
    load();
    const iv = window.setInterval(load, 20_000);
    return () => {
      cancelled = true;
      window.clearInterval(iv);
    };
  }, [projectId]);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  async function markRead(n: Notification) {
    if (n.read_at) return;
    const res = await fetch(`/api/notifications/${n.id}/read`, {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return;
    setItems((prev) =>
      prev.map((x) =>
        x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x,
      ),
    );
    setUnread((u) => Math.max(0, u - 1));
  }

  async function markAllRead() {
    const res = await fetch("/api/notifications/read_all", {
      method: "POST",
      credentials: "include",
    });
    if (!res.ok) return;
    const now = new Date().toISOString();
    setItems((prev) => prev.map((x) => ({ ...x, read_at: x.read_at ?? now })));
    setUnread(0);
  }

  return (
    <div ref={rootRef} style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="notifications"
        style={{
          position: "relative",
          padding: "6px 10px",
          background: "transparent",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          cursor: "pointer",
          fontSize: 14,
        }}
      >
        🔔
        {unread > 0 && (
          <span
            style={{
              position: "absolute",
              top: -6,
              right: -6,
              background: "var(--wg-accent)",
              color: "#fff",
              borderRadius: 999,
              padding: "1px 6px",
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              fontWeight: 700,
              minWidth: 16,
              textAlign: "center",
            }}
          >
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div
          role="menu"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            width: 360,
            maxHeight: 480,
            overflowY: "auto",
            background: "#fff",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            boxShadow: "0 4px 16px rgba(0,0,0,0.06)",
            zIndex: 10,
          }}
        >
          <div
            style={{
              padding: "10px 12px",
              borderBottom: "1px solid var(--wg-line)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
            }}
          >
            <span>Notifications · {unread} unread</span>
            {unread > 0 && (
              <button
                type="button"
                onClick={markAllRead}
                style={{
                  background: "transparent",
                  color: "var(--wg-accent)",
                  border: "none",
                  cursor: "pointer",
                  fontSize: 12,
                  fontFamily: "var(--wg-font-mono)",
                }}
              >
                mark all read
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <div
              style={{
                padding: 20,
                textAlign: "center",
                color: "var(--wg-ink-soft)",
                fontSize: 13,
              }}
            >
              Nothing new.
            </div>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {items.map((n) => (
                <li
                  key={n.id}
                  onClick={() => markRead(n)}
                  style={{
                    padding: "10px 12px",
                    borderBottom: "1px solid var(--wg-line)",
                    background: n.read_at ? "#fff" : "#f6efe8",
                    cursor: "pointer",
                    fontSize: 13,
                  }}
                >
                  <div
                    style={{
                      fontWeight: n.read_at ? 400 : 600,
                    }}
                  >
                    {n.title}
                  </div>
                  {n.body && (
                    <div
                      style={{
                        marginTop: 2,
                        color: "var(--wg-ink-soft)",
                        fontSize: 12,
                      }}
                    >
                      {n.body}
                    </div>
                  )}
                  <div
                    style={{
                      marginTop: 4,
                      fontFamily: "var(--wg-font-mono)",
                      fontSize: 11,
                      color: "var(--wg-ink-soft)",
                    }}
                  >
                    {formatIso(n.created_at)} · {n.kind}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
