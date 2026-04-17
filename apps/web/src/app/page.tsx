// Phase 11 landing view — design decision 2A.
// Stage-driven canvas (1A) will swap this out once a workflow is running.
// Phase 1 skeleton: static landing; the "Run canonical demo" button is a noop
// until Phase 2 wires the intake endpoint.

export default function Home() {
  return (
    <main
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 280px",
        minHeight: "100vh",
      }}
    >
      <section
        style={{
          padding: "80px 72px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          maxWidth: 640,
        }}
      >
        <div
          style={{
            fontSize: 13,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--wg-ink-soft)",
            marginBottom: 48,
          }}
        >
          <span
            style={{
              display: "inline-block",
              width: "var(--wg-dot)",
              height: "var(--wg-dot)",
              borderRadius: "50%",
              background: "var(--wg-accent)",
              marginRight: 8,
              verticalAlign: "middle",
            }}
          />
          WorkGraph
        </div>

        <h1
          style={{
            fontSize: 44,
            lineHeight: 1.15,
            fontWeight: 600,
            margin: 0,
          }}
        >
          Coordination as a graph, not a document.
        </h1>

        <p
          style={{
            fontSize: 17,
            lineHeight: 1.55,
            color: "var(--wg-ink-soft)",
            marginTop: 20,
            marginBottom: 40,
            maxWidth: 520,
          }}
        >
          Turn a single message into a coordinated team plan.
        </p>

        <button
          type="button"
          disabled
          aria-disabled
          title="Intake lands in Phase 2"
          style={{
            alignSelf: "flex-start",
            padding: "12px 20px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--wg-radius)",
            fontFamily: "var(--wg-font-sans)",
            fontSize: 15,
            fontWeight: 600,
            cursor: "not-allowed",
            opacity: 0.6,
          }}
        >
          Run canonical demo ▶
        </button>
        <div
          style={{
            marginTop: 12,
            fontSize: 12,
            color: "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          intake lands in Phase 2 · skeleton only
        </div>
      </section>

      <aside
        style={{
          borderLeft: "1px solid var(--wg-line)",
          padding: "80px 28px",
          fontSize: 13,
          color: "var(--wg-ink-soft)",
          fontFamily: "var(--wg-font-mono)",
        }}
      >
        <div style={{ marginBottom: 12, letterSpacing: "0.08em" }}>GRAPH</div>
        <div style={{ color: "var(--wg-ink)" }}>
          Your workflow graph will appear here.
        </div>
      </aside>
    </main>
  );
}
