import { NextResponse, type NextRequest } from "next/server";

import {
  DEFAULT_LOCALE,
  isLocale,
  LOCALE_COOKIE,
  pickLocaleFromHeader,
} from "./i18n/config";

// Without-i18n-routing middleware (cookie-based). We do NOT rewrite paths
// for locale — language is per-user and persisted in the backend profile.
// The middleware's sole job is to make sure every request carries a
// NEXT_LOCALE cookie so that request.ts has something to read before the
// user ever clicks the switcher.
//
// On the very first visit the cookie is absent; we set it from the best
// guess (Accept-Language → default) and pass the request through. The
// switcher (and, eventually, the signed-in profile) can overwrite it later.
export function middleware(req: NextRequest) {
  const existing = req.cookies.get(LOCALE_COOKIE)?.value;
  if (isLocale(existing)) {
    return NextResponse.next();
  }
  const fromHeader = pickLocaleFromHeader(req.headers.get("accept-language"));
  const locale = fromHeader ?? DEFAULT_LOCALE;
  const res = NextResponse.next();
  res.cookies.set(LOCALE_COOKIE, locale, {
    path: "/",
    sameSite: "lax",
    // 1 year — the cookie is the cache; the authoritative value lives on
    // the user's profile once they log in.
    maxAge: 60 * 60 * 24 * 365,
  });
  return res;
}

export const config = {
  // Skip Next internals, static assets, and API proxies. The API proxy
  // rewrites forward to FastAPI; running middleware on them is wasted work.
  matcher: ["/((?!_next|api|ws|favicon.ico|.*\\..*).*)"],
};
