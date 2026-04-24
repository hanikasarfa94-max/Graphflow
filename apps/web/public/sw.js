// WorkGraph service worker — minimal installable-PWA shell.
//
// Scope:
//   * Pre-cache the offline fallback page on install.
//   * Clean up old caches on activate.
//   * Network-first for /api/* and /ws/* (votes + inbox must be fresh —
//     we never serve stale data for them).
//   * Cache-first for static assets (/_next/static/*, /icons/*, /fonts/*,
//     manifest.json).
//   * Network-first with offline-page fallback for HTML navigations, so the
//     app still "opens" from the home screen when there's no connection.
//
// Intentionally NOT using Workbox or a precache manifest — the product needs
// the network for core flows, so we aim for "installable + offline shell",
// not full offline mode. Bump CACHE_VERSION whenever this file changes.

const CACHE_VERSION = "wg-v1";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;
const OFFLINE_URL = "/offline";
const PRECACHE_URLS = [OFFLINE_URL, "/manifest.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(STATIC_CACHE)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => !k.startsWith(CACHE_VERSION))
            .map((k) => caches.delete(k)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

function isStaticAsset(url) {
  return (
    url.pathname.startsWith("/_next/static/") ||
    url.pathname.startsWith("/icons/") ||
    url.pathname.startsWith("/fonts/") ||
    url.pathname === "/manifest.json"
  );
}

function isApiOrSocket(url) {
  return (
    url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")
  );
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // API + websocket upgrade — never cache. Let failures propagate so the UI
  // can show real error states (votes, inbox, SSE streams need freshness).
  if (isApiOrSocket(url)) {
    event.respondWith(fetch(request));
    return;
  }

  // Static assets — cache-first, fall back to network, store successful
  // responses for next time.
  if (isStaticAsset(url)) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(request, clone));
          }
          return response;
        });
      }),
    );
    return;
  }

  // Navigations (HTML) — network-first, fall back to a cached response or
  // the offline page. This is what makes the home-screen icon "open" when
  // the user is offline.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches
              .open(RUNTIME_CACHE)
              .then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() =>
          caches
            .match(request)
            .then((cached) => cached || caches.match(OFFLINE_URL)),
        ),
    );
  }
});
