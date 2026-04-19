"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { LOCALE_COOKIE, LOCALES, type Locale } from "@/i18n/config";

// Toggle/dropdown that writes NEXT_LOCALE to the browser cookie and best-
// effort persists the choice to the backend profile. The cookie alone is
// enough for the UI to re-render in the new language — the profile write
// is so that other devices / server-rendered pages load in the right
// language even before the cookie is set.
//
// The backend endpoint may not yet exist (another agent owns
// PATCH /api/users/me). We intentionally fire-and-forget with graceful
// failure — a missing endpoint must not block the language change.
export function LanguageSwitcher({ className }: { className?: string }) {
  const currentLocale = useLocale() as Locale;
  const t = useTranslations("language");
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  async function change(next: Locale) {
    if (next === currentLocale) return;
    // Cookie first — this is what request.ts reads on the next render.
    document.cookie = `${LOCALE_COOKIE}=${next}; path=/; max-age=${60 * 60 * 24 * 365}; samesite=lax`;

    // Best-effort profile update. Swallow any failure; the cookie is
    // already set and the UI will reload into the new language below.
    try {
      await fetch("/api/users/me", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ display_language: next }),
      });
    } catch {
      // Endpoint may not exist yet; swallow.
    }

    // Re-render server components with the new locale.
    startTransition(() => router.refresh());
  }

  const label = (loc: Locale) =>
    loc === "en" ? t("english") : t("chinese");

  return (
    <div
      className={className}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontSize: 12,
        fontFamily: "var(--wg-font-mono)",
        color: "var(--wg-ink-soft)",
      }}
    >
      <span aria-hidden>{t("switcher")}:</span>
      <select
        value={currentLocale}
        onChange={(e) => change(e.target.value as Locale)}
        disabled={pending}
        aria-label={t("switcher")}
        style={{
          background: "transparent",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          padding: "2px 6px",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink)",
          cursor: pending ? "progress" : "pointer",
        }}
      >
        {LOCALES.map((loc) => (
          <option key={loc} value={loc}>
            {label(loc)}
          </option>
        ))}
      </select>
    </div>
  );
}
