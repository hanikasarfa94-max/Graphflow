// Shared locale config. Kept separate so both server (`request.ts`) and
// client code (LanguageSwitcher) import the same constants.
export const LOCALES = ["en", "zh"] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";
export const LOCALE_COOKIE = "NEXT_LOCALE";

export function isLocale(value: string | undefined | null): value is Locale {
  return !!value && (LOCALES as readonly string[]).includes(value);
}

// Minimal Accept-Language parser: returns the first tag whose primary subtag
// matches a supported locale (e.g. `zh-CN` → `zh`). Avoids pulling in a full
// language-negotiation dependency for a 2-locale app.
export function pickLocaleFromHeader(header: string | null): Locale | null {
  if (!header) return null;
  const tags = header
    .split(",")
    .map((part) => part.trim().split(";")[0].toLowerCase())
    .filter(Boolean);
  for (const tag of tags) {
    const primary = tag.split("-")[0];
    if (isLocale(primary)) return primary;
  }
  return null;
}
