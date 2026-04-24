// Offline fallback page served by the service worker when a navigation
// request fails with no cached response. Kept intentionally plain — no
// client components, no i18n — so it's guaranteed renderable offline.

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Offline — graphflow",
  description: "You're offline. Reconnect to pick up where you left off.",
};

export default function OfflinePage() {
  return (
    <main
      style={{
        minHeight: "100dvh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "2rem",
        textAlign: "center",
        gap: "0.75rem",
      }}
    >
      <h1 style={{ fontSize: "1.5rem", margin: 0 }}>You&apos;re offline</h1>
      <p style={{ maxWidth: "32ch", margin: 0, opacity: 0.7 }}>
        graphflow needs a connection for votes and live updates. Reconnect
        and the app will pick up where you left off.
      </p>
    </main>
  );
}
