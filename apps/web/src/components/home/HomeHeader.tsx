import { getTranslations } from "next-intl/server";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button, Heading, Text } from "@/components/ui";

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
        <Text
          as="div"
          variant="label"
          muted
          style={{
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <span className="wg-dot" />
          {t("brand.name")}
        </Text>
        <Heading level={1} style={{ margin: "8px 0 0" }}>
          {t("home.welcome", { name: displayName })}
        </Heading>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <LanguageSwitcher />
        <form
          action="/api/auth/logout?redirect=/"
          method="POST"
          style={{ display: "inline" }}
        >
          <Button type="submit" variant="link" size="sm">
            {t("nav.signOut")}
          </Button>
        </form>
      </div>
    </header>
  );
}
