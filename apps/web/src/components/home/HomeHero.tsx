// HomeHero — Batch E.3 home rebuild.
//
// Two-card row that anchors the home page per the home_redesign html:
//   * Left: hero card with kicker, big serif welcome, prose subtitle
//     and three primary CTAs.
//   * Right: dark "System pulse" card showing how many human-attention
//     items are waiting + headline metrics (active projects, total graph
//     nodes, decisions in the last 7 days).
//
// Data is computed server-side in components/home/data.ts. The hero
// itself is a server component — no client state.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Heading, Metric, Text } from "@/components/ui";

import type {
  HomePulseAggregates,
  HomeTopProjectSnapshot,
} from "./data";

const heroCard: React.CSSProperties = {
  position: "relative",
  overflow: "hidden",
  borderRadius: 24,
  padding: "32px 32px 28px",
  // Light card with soft blue radial wash + faint diagonal stripes.
  // Uses CSS-var-resolvable colours so dark mode inherits cleanly.
  background:
    "linear-gradient(135deg, rgba(255,255,255,0.96), rgba(239,246,255,0.92)),\
     radial-gradient(circle at 80% 18%, rgba(37,99,235,0.14), transparent 36%)",
  border: "1px solid var(--wg-line)",
  boxShadow: "0 18px 40px rgba(30,64,175,0.08)",
};

const pulseCard: React.CSSProperties = {
  position: "relative",
  overflow: "hidden",
  borderRadius: 24,
  padding: "26px 26px 22px",
  // Deep navy, brand-accent radial in the bottom-right corner. The
  // pulse card is intentionally darker than everything else on the
  // page — that's what makes it read as "the system is talking to you."
  background: "linear-gradient(150deg, #0f172a 0%, #1d4ed8 100%)",
  color: "#ffffff",
  minHeight: 240,
  display: "flex",
  flexDirection: "column",
  justifyContent: "space-between",
};

const heroBtn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "10px 16px",
  borderRadius: 12,
  fontSize: 13,
  fontWeight: 600,
  textDecoration: "none",
  border: "1px solid var(--wg-line)",
  background: "var(--wg-surface)",
  color: "var(--wg-ink)",
  boxShadow: "0 6px 16px rgba(30,64,175,0.06)",
};

const heroBtnPrimary: React.CSSProperties = {
  ...heroBtn,
  background: "var(--wg-accent)",
  borderColor: "var(--wg-accent)",
  color: "#ffffff",
};

export async function HomeHero({
  displayName,
  pendingCount,
  pulse,
  topProject,
}: {
  displayName: string;
  pendingCount: number;
  pulse: HomePulseAggregates;
  // Most-relevant project to "resume" into, when one exists. The
  // prototype's home is the project's personal stream — surfacing a
  // direct CTA gets the chat-flow surface one click from the dashboard
  // without dropping the dashboard itself.
  topProject?: HomeTopProjectSnapshot | null;
}) {
  const t = await getTranslations("home.hero");

  // Pick a primary CTA target — if there's pending work, jump to it; if
  // not, surface the projects list as the "what now" option. The
  // resume CTA below is independent of this and always preferred when
  // a top project exists.
  const primaryHref = pendingCount > 0 ? "#pending" : "/projects";

  return (
    <section
      style={{
        display: "grid",
        gap: 18,
        gridTemplateColumns: "minmax(0, 1fr) 360px",
        marginBottom: 24,
      }}
    >
      <article style={heroCard}>
        <div
          style={{
            fontSize: 11,
            letterSpacing: "0.16em",
            textTransform: "uppercase",
            color: "var(--wg-accent)",
            fontFamily: "var(--wg-font-mono)",
            fontWeight: 700,
            marginBottom: 8,
          }}
        >
          {t("kicker")}
        </div>
        <Heading
          level={1}
          variant="display"
          style={{
            margin: "10px 0 8px",
            fontSize: 50,
            lineHeight: 1.04,
            letterSpacing: "-0.02em",
          }}
        >
          {t("welcome", { name: displayName })}
        </Heading>
        <Text
          variant="body"
          style={{
            margin: 0,
            color: "var(--wg-ink-soft)",
            lineHeight: 1.65,
            maxWidth: 640,
            fontSize: 15,
          }}
        >
          {t("subtitle")}
        </Text>
        <div
          style={{
            display: "flex",
            gap: 10,
            marginTop: 24,
            flexWrap: "wrap",
          }}
        >
          {topProject ? (
            <Link
              href={`/projects/${topProject.project_id}`}
              style={heroBtnPrimary}
              data-testid="home-resume-cta"
            >
              {t("resumeCta", { name: topProject.project_title })}
            </Link>
          ) : null}
          <Link
            href={primaryHref}
            style={topProject ? heroBtn : heroBtnPrimary}
          >
            {pendingCount > 0
              ? t("primaryCta", { count: pendingCount })
              : t("primaryCtaQuiet")}
          </Link>
          <Link href="/projects" style={heroBtn}>
            {t("secondaryCta")}
          </Link>
        </div>
      </article>

      <article style={pulseCard}>
        {/* Faint blue dot in the corner — visual anchor that ties the
            pulse card to the brand without overwhelming the metrics. */}
        <span
          aria-hidden
          style={{
            position: "absolute",
            right: -70,
            bottom: -80,
            width: 220,
            height: 220,
            borderRadius: "50%",
            background: "rgba(56,189,248,0.32)",
            filter: "blur(2px)",
          }}
        />
        <span
          aria-hidden
          style={{
            position: "absolute",
            inset: 0,
            backgroundImage:
              "linear-gradient(rgba(255,255,255,0.06) 1px, transparent 1px),\
               linear-gradient(90deg, rgba(255,255,255,0.05) 1px, transparent 1px)",
            backgroundSize: "28px 28px",
            opacity: 0.6,
          }}
        />
        <div style={{ position: "relative", zIndex: 1 }}>
          <div
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.78)",
              fontFamily: "var(--wg-font-mono)",
              fontWeight: 600,
            }}
          >
            {t("pulseEyebrow")}
          </div>
          <h2
            style={{
              margin: "10px 0 4px",
              fontSize: 28,
              fontWeight: 600,
              letterSpacing: "-0.02em",
            }}
          >
            {t("pulseHeadline", { count: pendingCount })}
          </h2>
          <p
            style={{
              margin: 0,
              color: "rgba(214,224,240,0.82)",
              fontSize: 13,
              lineHeight: 1.55,
            }}
          >
            {pendingCount > 0
              ? t("pulseBodyActive")
              : t("pulseBodyQuiet")}
          </p>
        </div>
        <div
          style={{
            position: "relative",
            zIndex: 1,
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 8,
            marginTop: 18,
          }}
        >
          <Metric tone="onDark" label={t("pulseStat.projects")} value={pulse.active_project_count} />
          <Metric tone="onDark" label={t("pulseStat.nodes")} value={pulse.total_graph_nodes} />
          <Metric tone="onDark" label={t("pulseStat.decisions7d")} value={pulse.decisions_last_7d} />
        </div>
      </article>
    </section>
  );
}
