"use client";

import { useEffect } from "react";

/**
 * Registers /sw.js on mount, once per page load.
 *
 * Guarded by a `serviceWorker in navigator` check so older browsers and
 * non-secure contexts (some dev setups) silently no-op. Registration
 * failures are logged but never thrown — a broken SW must not break the
 * app shell.
 */
export function ServiceWorkerRegister() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;
    // Defer until after first paint so it doesn't compete with hydration.
    const register = () => {
      navigator.serviceWorker
        .register("/sw.js", { scope: "/" })
        .catch((err) => {
          // eslint-disable-next-line no-console
          console.warn("[pwa] service worker registration failed:", err);
        });
    };
    if (document.readyState === "complete") {
      register();
    } else {
      window.addEventListener("load", register, { once: true });
    }
  }, []);

  return null;
}
