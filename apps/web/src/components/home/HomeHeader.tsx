import { getTranslations } from "next-intl/server";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";

// Welcome strip at the top of `/`. Keep it server-rendered — no state.
// Sign out is a regular HTML form so we don't need any client JS for it.
export async function HomeHeader({ displayName }: { displayName: string }) {
  const t = await getTranslations();
  return (
    <header
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        marginBottom: 32,
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div>
        <div
          style={{
            fontSize: 12,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wg-ink-soft)",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span className="wg-dot" />
          {t("brand.name")}
        </div>
        <h1
          style={{
            fontSize: 28,
            fontWeight: 600,
            margin: "8px 0 0",
            letterSpacing: "-0.01em",
          }}
        >
          {t("home.welcome", { name: displayName })}
        </h1>
      </div>
      <div
        style={{
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <LanguageSwitcher />
        <form
          action="/api/auth/logout"
          method="POST"
          style={{ display: "inline" }}
        >
          <button
            type="submit"
            style={{
              background: "transparent",
              border: "none",
              color: "var(--wg-accent)",
              cursor: "pointer",
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
            }}
          >
            {t("nav.signOut")}
          </button>
        </form>
      </div>
    </header>
  );
}
