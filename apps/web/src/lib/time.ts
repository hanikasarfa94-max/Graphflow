// Time formatting — pinned to Asia/Shanghai (UTC+8, no DST).
//
// Why hard-pin a timezone instead of using the browser default:
//
//   1. SSR vs CSR mismatch. Server renders in UTC, client renders in the
//      browser's TZ — `new Date(iso).toLocaleString()` produces different
//      strings on each side, which trips React #418 hydration warnings
//      (already hit once on home, see commit c9c2267).
//   2. The product targets China-team coordination; users expect 北京时间.
//   3. Non-China viewers (overseas teammates, demo audiences) still need
//      a consistent shared reference for "when did this happen on the
//      project's clock," not their own laptop's clock.
//
// This file is the single place that formats human-facing timestamps. New
// code should import from here, not call `toLocaleString()` directly.

export const DISPLAY_TZ = "Asia/Shanghai";
export const DISPLAY_LOCALE = "en-CA"; // YYYY-MM-DD ordering, ISO-friendly

// Per-user feedback 2026-05-06: visible "GMT+8" suffix read as too
// English / acronym-y in zh demo. The hard-pin to Asia/Shanghai stays
// (SSR/CSR consistency reason from the file header), but we no longer
// append a textual zone marker. Times read as plain "14:30" / "Yesterday
// 14:30" — and since every render pulls from this module, every visible
// time is implicitly Beijing time. Tooltips that need full precision
// keep formatIsoSeconds, also un-suffixed.
//
// Kept as a no-op export so any external import compiles, but new code
// should not consume it.
export const DISPLAY_TZ_LABEL = "";

// M1.2 — parse an ISO string honoring "the server emitted offsetless UTC".
// SQLite + Python `datetime.utcnow().isoformat()` produces strings like
// "2026-05-06T01:41:45.811226" with NO timezone suffix. `new Date(s)` then
// interprets them as the BROWSER's local time, which on a CN machine
// shifts every timestamp by -8h: "01:41 UTC" gets read as "01:41 CST",
// formatted into Shanghai TZ as "01:41 GMT+8" — wrong by exactly one
// timezone. This is the dogfood drift point.
//
// Fix: any ISO string lacking a TZ marker (`Z` or `±HH[:MM]`) is treated
// as UTC by appending `Z` before construction. All formatters in this
// module funnel through here. Strings that already carry a TZ are
// passed through untouched.
const _TZ_SUFFIX = /([Zz]|[+-]\d{2}:?\d{2})$/;

export function parseServerTime(
  iso: string | number | Date | null | undefined,
): Date | null {
  if (iso == null) return null;
  if (iso instanceof Date) {
    return Number.isFinite(iso.getTime()) ? iso : null;
  }
  if (typeof iso === "number") {
    const d = new Date(iso);
    return Number.isFinite(d.getTime()) ? d : null;
  }
  const s = iso.trim();
  if (!s) return null;
  const normalized = _TZ_SUFFIX.test(s) ? s : `${s}Z`;
  const d = new Date(normalized);
  return Number.isFinite(d.getTime()) ? d : null;
}

// ISO-style absolute. "2026-05-03 14:30" — 24h, hyphenated date,
// always rendered in Asia/Shanghai. No textual zone marker appended.
// Use for tooltips and audit-log rows where date precision matters.
export function formatIso(iso?: string | number | Date | null): string {
  if (iso === undefined) iso = new Date();
  const d = parseServerTime(iso);
  if (!d) return "";
  // en-CA gives "YYYY-MM-DD, HH:mm" format which is ISO-friendly.
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    timeZone: DISPLAY_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .format(d)
    .replace(",", "");
}

// Same as formatIso plus seconds. Reserved for audit / debug surfaces
// where second-precision matters. Most user-visible chrome should use
// formatIso (minute precision is the chat rhythm).
export function formatIsoSeconds(iso: string | number | Date | null): string {
  const d = parseServerTime(iso);
  if (!d) return "";
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    timeZone: DISPLAY_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
    .format(d)
    .replace(",", "");
}

// "14:30" clock-only — for in-stream message rows where the date is
// implied by the message group divider above.
export function formatTime(iso: string | number | Date | null): string {
  const d = parseServerTime(iso);
  if (!d) return "";
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    timeZone: DISPLAY_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

// "2026-05-03" — date-only, ISO-formatted, in GMT+8.
export function formatDate(iso: string | number | Date | null): string {
  const d = parseServerTime(iso);
  if (!d) return "";
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    timeZone: DISPLAY_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

// "May 3" — short date for narrow chips. Locale-independent.
export function formatShortDate(iso: string | number | Date | null): string {
  const d = parseServerTime(iso);
  if (!d) return "";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: DISPLAY_TZ,
    month: "short",
    day: "numeric",
  }).format(d);
}

// Returns the calendar-day string in GMT+8, used for the "same day" /
// "yesterday" comparison in formatMessageTime. Stable across SSR/CSR.
export function gmt8DayKey(iso: string | number | Date): string {
  return formatDate(iso);
}
