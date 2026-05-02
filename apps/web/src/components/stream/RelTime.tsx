"use client";

// RelTime — client-only relative-time renderer.
//
// Wraps relativeTime() in a way that avoids React #418 hydration
// mismatches caused by Date.now() differing between server-render
// and client-hydrate (a few hundred ms gap is enough to flip a
// "59 min ago" → "1 hr ago" boundary). The iso string is the same
// across server + client; the relative formatting runs only after
// mount on the client. Server emits the iso as a stable fallback so
// the SSR HTML still has SOMETHING legible if JS fails to hydrate.

import { useEffect, useState } from "react";

import { relativeTime } from "./types";

export function RelTime({
  iso,
  fallback = "",
}: {
  iso: string | null | undefined;
  fallback?: string;
}) {
  const [text, setText] = useState<string>(fallback);
  useEffect(() => {
    if (!iso) {
      setText(fallback);
      return;
    }
    setText(relativeTime(iso));
    // Re-tick once a minute so "5 min ago" eventually becomes "6 min ago"
    // without a page reload.
    const id = setInterval(() => {
      setText(relativeTime(iso));
    }, 60_000);
    return () => clearInterval(id);
  }, [iso, fallback]);
  // suppressHydrationWarning silences the brief mismatch on the very
  // first render (server emitted fallback, client hydrates with the
  // computed value once useEffect fires).
  return <span suppressHydrationWarning>{text}</span>;
}
