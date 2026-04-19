import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import {
  DEFAULT_LOCALE,
  isLocale,
  LOCALE_COOKIE,
  pickLocaleFromHeader,
  type Locale,
} from "./config";

// Resolve the user's display language per request.
// Precedence: NEXT_LOCALE cookie → backend user profile (display_language)
// → Accept-Language header → DEFAULT_LOCALE.
//
// We deliberately do NOT use URL-based routing (no /en/... or /zh/... prefix)
// — language is per-user, persisted in the profile, and toggled by a UI
// switcher that writes the cookie. See docs/north-star.md item 3 in
// "Resolved product questions".
async function resolveLocale(): Promise<Locale> {
  const cookieStore = await cookies();
  const fromCookie = cookieStore.get(LOCALE_COOKIE)?.value;
  if (isLocale(fromCookie)) return fromCookie;

  // Ask the backend for the logged-in user's preferred language. If the
  // endpoint is unavailable (backend down, or /api/users/me not yet
  // implemented by the parallel agent), swallow the error and fall through.
  try {
    const headerStore = await headers();
    const cookieHeader = cookieStore.toString();
    const apiBase =
      process.env.WORKGRAPH_API_BASE_SERVER ??
      process.env.WORKGRAPH_API_BASE ??
      "http://127.0.0.1:8000";
    const res = await fetch(`${apiBase}/api/users/me`, {
      headers: cookieHeader ? { cookie: cookieHeader } : undefined,
      cache: "no-store",
      // Short timeout: don't let a hung backend block page render.
      signal: AbortSignal.timeout(1500),
    });
    // headerStore reserved for future locale negotiation signals; suppress
    // unused-var by intentionally referencing it.
    void headerStore;
    if (res.ok) {
      const body = (await res.json().catch(() => null)) as
        | { display_language?: string }
        | null;
      if (body && isLocale(body.display_language)) return body.display_language;
    }
  } catch {
    // Fall through to Accept-Language.
  }

  const headerStore = await headers();
  const accept = headerStore.get("accept-language");
  const fromHeader = pickLocaleFromHeader(accept);
  if (fromHeader) return fromHeader;

  return DEFAULT_LOCALE;
}

export default getRequestConfig(async () => {
  const locale = await resolveLocale();
  const messages = (await import(`./locales/${locale}.json`)).default;
  return { locale, messages };
});
