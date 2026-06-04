"use client";

// useInboxCount — pending-routed-signal count for the sidebar footer Inbox
// badge. Refreshes on mount, window focus, and a gentle interval. Best-
// effort: a failed fetch keeps the prior count rather than flashing zero.
// Read-only; uses the existing GET /api/routing/inbox?status=pending.

import { useEffect, useState } from "react";

import { listRoutedInbox } from "@/lib/api";

const REFRESH_MS = 30000;
const FETCH_LIMIT = 100;

// Pure: badge text from a count. Null hides the badge; caps at "99+".
export function formatBadgeCount(count: number): string | null {
  if (!Number.isFinite(count) || count <= 0) return null;
  if (count > 99) return "99+";
  return String(Math.floor(count));
}

export function useInboxCount(): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const r = await listRoutedInbox({ status: "pending", limit: FETCH_LIMIT });
        if (!cancelled) setCount(r.signals.length);
      } catch {
        // keep prior count on transient failure
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), REFRESH_MS);
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  return count;
}
