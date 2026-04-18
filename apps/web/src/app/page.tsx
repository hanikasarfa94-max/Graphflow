import { GraphPreview } from "./GraphPreview";
import { LandingHero } from "./LandingHero";

export default function Home() {
  return (
    <main
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 320px",
        minHeight: "100vh",
      }}
    >
      <LandingHero />

      <aside
        style={{
          borderLeft: "1px solid var(--wg-line)",
          padding: "72px 20px 40px",
          display: "flex",
          flexDirection: "column",
          gap: 16,
          background: "var(--wg-surface)",
        }}
      >
        <div
          style={{
            fontSize: 11,
            letterSpacing: "0.08em",
            color: "var(--wg-ink-faint)",
            fontFamily: "var(--wg-font-mono)",
            textTransform: "uppercase",
          }}
        >
          Canonical flow
        </div>
        <GraphPreview />
        <div
          style={{
            fontSize: 12,
            color: "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
            textAlign: "center",
            lineHeight: 1.6,
          }}
        >
          Five stages. One graph.
          <br />
          Every decision on the record.
        </div>
      </aside>
    </main>
  );
}
