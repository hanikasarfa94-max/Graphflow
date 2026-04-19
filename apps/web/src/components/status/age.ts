// Pure helpers for the status dashboard. No React — just data shaping.

// Minimal translator shape shared between server/client pages. Matches
// both `getTranslations` and `useTranslations` return types closely enough
// that callers can pass either without a cast.
export type Translator = (
  key: string,
  values?: Record<string, string | number | Date>,
) => string;

export function ageSecondsFrom(timestamp: string | null | undefined, now: Date): number | null {
  if (!timestamp) return null;
  const t = Date.parse(timestamp);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.floor((now.getTime() - t) / 1000));
}

// Format an age in seconds into a short label (e.g., "3m", "2h", "5d").
// Takes a translator so callers can localize; keeps the component tree pure.
export function formatAge(seconds: number | null, t: Translator): string {
  if (seconds === null) return t("status.age.unknown");
  if (seconds < 60) return t("status.age.justNow");
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t("status.age.minutes", { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return t("status.age.hours", { n: hours });
  const days = Math.floor(hours / 24);
  return t("status.age.days", { n: days });
}
