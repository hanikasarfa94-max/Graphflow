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

// ISO-style absolute. "2026-05-03 14:30" — 24h, hyphenated date, no TZ
// in the string (the surrounding context establishes "this is GMT+8").
// Use for tooltips and audit-log rows where ambiguity must be zero.
export function formatIso(iso?: string | number | Date | null): string {
  if (iso === undefined) iso = new Date();
  if (iso == null) return "";
  const d = iso instanceof Date ? iso : new Date(iso);
  if (!Number.isFinite(d.getTime())) return "";
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
  if (iso == null) return "";
  const d = iso instanceof Date ? iso : new Date(iso);
  if (!Number.isFinite(d.getTime())) return "";
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
  if (iso == null) return "";
  const d = iso instanceof Date ? iso : new Date(iso);
  if (!Number.isFinite(d.getTime())) return "";
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    timeZone: DISPLAY_TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

// "2026-05-03" — date-only, ISO-formatted, in GMT+8.
export function formatDate(iso: string | number | Date | null): string {
  if (iso == null) return "";
  const d = iso instanceof Date ? iso : new Date(iso);
  if (!Number.isFinite(d.getTime())) return "";
  return new Intl.DateTimeFormat(DISPLAY_LOCALE, {
    timeZone: DISPLAY_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

// "May 3" — short date for narrow chips. Locale-independent.
export function formatShortDate(iso: string | number | Date | null): string {
  if (iso == null) return "";
  const d = iso instanceof Date ? iso : new Date(iso);
  if (!Number.isFinite(d.getTime())) return "";
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
