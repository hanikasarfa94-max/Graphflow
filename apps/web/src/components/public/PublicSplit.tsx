import { getTranslations } from "next-intl/server";

import { Heading } from "@/components/ui";

import { MorphingGraphDemo } from "./MorphingGraphDemo";

// Public-facing split layout. Left pane shows the live morphing-graph demo
// and the hero copy; right pane slots the passed-in auth form (login or
// register). Used on / (logged-out) and /login.
//
// Responsive breakpoint is at 960px — below that, the display stacks on top
// of the auth form. See .wg-public-split in globals.css.
export async function PublicSplit({ children }: { children: React.ReactNode }) {
  const t = await getTranslations("landing");
  const tBrand = await getTranslations("brand");

  return (
    <main className="wg-public-split">
      <section className="wg-public-display">
        <div
          style={{
            fontSize: 12,
            letterSpacing: "0.12em",
            textTransform: "uppercase",
            color: "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          <span className="wg-dot" style={{ marginRight: 8 }} />
          {tBrand("name")}
        </div>

        <Heading level={1} variant="display" style={{ maxWidth: 560 }}>
          {t("title1")}
          <br />
          {t("title2")}
        </Heading>

        <MorphingGraphDemo />
      </section>

      <section className="wg-public-auth">{children}</section>
    </main>
  );
}
