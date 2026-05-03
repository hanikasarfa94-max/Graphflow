"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import type { Delivery, ProjectState } from "@/lib/api";
import { formatIso } from "@/lib/time";

export function DeliveryCanvas({
  projectId,
  state,
  deliveryHistory,
  setState,
  setDeliveryHistory,
}: {
  projectId: string;
  state: ProjectState;
  deliveryHistory: Delivery[];
  setState: React.Dispatch<React.SetStateAction<ProjectState>>;
  setDeliveryHistory: React.Dispatch<React.SetStateAction<Delivery[]>>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const t = useTranslations("qaSweep.consoleLegacy");

  const latest = state.delivery;

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/projects/${projectId}/delivery`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setError(j.detail ?? `generate failed (${res.status})`);
        return;
      }
      const body = await res.json();
      if (body.delivery) {
        setState((prev) => ({ ...prev, delivery: body.delivery }));
        setDeliveryHistory((prev) => {
          const without = prev.filter((x) => x.id !== body.delivery.id);
          return [body.delivery, ...without];
        });
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      data-testid="canvas-delivery"
      style={{ maxWidth: 760, margin: "0 auto", padding: "28px 32px" }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 20,
        }}
      >
        <div>
          <div
            style={{
              fontFamily: "var(--wg-font-mono)",
              fontSize: 11,
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
              letterSpacing: "0.1em",
              marginBottom: 6,
            }}
          >
            Delivery summary
          </div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 600 }}>
            {state.project.title}
          </h2>
        </div>
        <button
          data-testid="generate-delivery"
          onClick={generate}
          disabled={busy}
          style={{
            padding: "10px 18px",
            background: "var(--wg-accent)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--wg-radius)",
            fontWeight: 600,
            fontSize: 13,
            cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? t("generating") : latest ? t("regenerate") : t("generate")}
        </button>
      </header>

      {error ? (
        <div
          role="alert"
          style={{
            marginBottom: 16,
            padding: 12,
            background: "var(--wg-accent-soft)",
            border: "1px solid var(--wg-accent)",
            borderRadius: "var(--wg-radius)",
            fontSize: 13,
          }}
        >
          {error}
        </div>
      ) : null}

      {latest ? <DeliveryDoc delivery={latest} /> : <EmptyDelivery />}

      {deliveryHistory.length > 1 ? (
        <HistoryStrip
          history={deliveryHistory}
          currentId={latest?.id ?? null}
        />
      ) : null}
    </div>
  );
}

function EmptyDelivery() {
  return (
    <div
      data-testid="delivery-empty"
      style={{
        padding: 48,
        border: "1px dashed var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        textAlign: "center",
        color: "var(--wg-ink-soft)",
        background: "var(--wg-surface-raised)",
      }}
    >
      <div style={{ fontSize: 14, marginBottom: 8 }}>
        No delivery summary yet.
      </div>
      <div style={{ fontSize: 13 }}>
        Click{" "}
        <strong style={{ color: "var(--wg-ink)" }}>Generate</strong> to
        produce one from the current plan + decisions.
      </div>
    </div>
  );
}

function DeliveryDoc({ delivery }: { delivery: Delivery }) {
  const t = useTranslations("qaSweep.consoleLegacy");
  const c = delivery.content;
  const qa = delivery.qa_report;
  const showWarning =
    delivery.parse_outcome === "manual_review" || qa.uncovered.length > 0;

  return (
    <article
      data-testid="delivery-doc"
      style={{
        background: "var(--wg-surface-raised)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        padding: 28,
      }}
    >
      <h1
        data-testid="delivery-headline"
        style={{ margin: 0, fontSize: 22, fontWeight: 600, lineHeight: 1.3 }}
      >
        {c.headline}
      </h1>
      <div
        style={{
          marginTop: 8,
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: "var(--wg-ink-soft)",
        }}
      >
        {delivery.created_at
          ? formatIso(delivery.created_at)
          : ""}
        {delivery.prompt_version
          ? ` · prompt ${delivery.prompt_version}`
          : ""}
        {` · ${delivery.parse_outcome}`}
      </div>

      {showWarning ? (
        <div
          data-testid="delivery-qa-warning"
          style={{
            marginTop: 16,
            padding: 12,
            background: "var(--wg-amber-soft)",
            border: "1px solid var(--wg-amber)",
            borderRadius: "var(--wg-radius-sm)",
            fontSize: 13,
            color: "var(--wg-ink)",
          }}
        >
          <strong>{t("checkpoint")}</strong> {qa.uncovered.length} scope item
          {qa.uncovered.length === 1 ? "" : "s"} uncovered
          {qa.uncovered.length > 0 ? ` — ${qa.uncovered.join(", ")}` : ""}
        </div>
      ) : null}

      {c.narrative ? (
        <p
          data-testid="delivery-narrative"
          style={{
            marginTop: 18,
            fontSize: 15,
            lineHeight: 1.65,
            whiteSpace: "pre-wrap",
          }}
        >
          {c.narrative}
        </p>
      ) : null}

      <Section title="Completed scope">
        {c.completed_scope.length === 0 ? (
          <Empty>None.</Empty>
        ) : (
          <ul
            data-testid="delivery-completed"
            style={{ margin: 0, padding: 0, listStyle: "none" }}
          >
            {c.completed_scope.map((i) => (
              <li
                key={i.scope_item}
                data-testid="completed-item"
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  padding: "6px 0",
                }}
              >
                <span className="wg-dot" style={{ marginTop: 8 }} />
                <span style={{ fontSize: 14 }}>{i.scope_item}</span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {c.deferred_scope.length > 0 ? (
        <Section title="Deferred scope">
          <ul
            data-testid="delivery-deferred"
            style={{ margin: 0, padding: 0, listStyle: "none" }}
          >
            {c.deferred_scope.map((i) => (
              <li
                key={i.scope_item}
                data-testid="deferred-item"
                style={{
                  padding: "8px 0",
                  borderBottom: "1px solid var(--wg-line-soft)",
                }}
              >
                <div style={{ fontSize: 14, fontWeight: 500 }}>
                  {i.scope_item}
                </div>
                <div
                  style={{
                    fontSize: 13,
                    color: "var(--wg-ink-soft)",
                    marginTop: 2,
                  }}
                >
                  {i.reason}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {c.key_decisions.length > 0 ? (
        <Section title="Key decisions">
          <ul
            data-testid="delivery-decisions"
            style={{ margin: 0, padding: 0, listStyle: "none" }}
          >
            {c.key_decisions.map((d) => (
              <li
                key={d.decision_id}
                style={{
                  padding: "8px 0",
                  borderBottom: "1px solid var(--wg-line-soft)",
                }}
              >
                <div style={{ fontSize: 14, fontWeight: 500 }}>
                  {d.headline}
                </div>
                {d.rationale ? (
                  <div
                    style={{
                      fontSize: 13,
                      color: "var(--wg-ink-soft)",
                      marginTop: 2,
                    }}
                  >
                    {d.rationale}
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {c.remaining_risks.length > 0 ? (
        <Section title="Remaining risks">
          <ul
            data-testid="delivery-risks"
            style={{ margin: 0, padding: 0, listStyle: "none" }}
          >
            {c.remaining_risks.map((r) => (
              <li
                key={r.title}
                style={{
                  padding: "8px 0",
                  borderBottom: "1px solid var(--wg-line-soft)",
                  display: "flex",
                  gap: 12,
                }}
              >
                <span
                  style={{
                    fontFamily: "var(--wg-font-mono)",
                    fontSize: 10,
                    padding: "2px 6px",
                    border: `1px solid ${
                      r.severity === "high"
                        ? "var(--wg-accent)"
                        : r.severity === "medium"
                          ? "var(--wg-amber)"
                          : "var(--wg-ink-soft)"
                    }`,
                    borderRadius: 10,
                    color:
                      r.severity === "high"
                        ? "var(--wg-accent)"
                        : r.severity === "medium"
                          ? "var(--wg-amber)"
                          : "var(--wg-ink-soft)",
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                    height: 18,
                    flexShrink: 0,
                  }}
                >
                  {r.severity}
                </span>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 500 }}>{r.title}</div>
                  {r.content ? (
                    <div
                      style={{
                        fontSize: 13,
                        color: "var(--wg-ink-soft)",
                        marginTop: 2,
                      }}
                    >
                      {r.content}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}
    </article>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ marginTop: 24 }}>
      <h3
        style={{
          margin: 0,
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: "var(--wg-ink-soft)",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
          marginBottom: 10,
        }}
      >
        {title}
      </h3>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p style={{ margin: 0, color: "var(--wg-ink-soft)", fontSize: 13 }}>
      {children}
    </p>
  );
}

function HistoryStrip({
  history,
  currentId,
}: {
  history: Delivery[];
  currentId: string | null;
}) {
  return (
    <section
      data-testid="delivery-history"
      style={{ marginTop: 24 }}
    >
      <h3
        style={{
          margin: "0 0 10px",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: "var(--wg-ink-soft)",
          textTransform: "uppercase",
          letterSpacing: "0.1em",
        }}
      >
        Regenerations · {history.length}
      </h3>
      <ol
        style={{
          margin: 0,
          padding: 0,
          listStyle: "none",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          background: "var(--wg-surface-raised)",
        }}
      >
        {history.map((d) => (
          <li
            key={d.id}
            data-testid="history-row"
            style={{
              padding: "10px 14px",
              borderBottom: "1px solid var(--wg-line-soft)",
              display: "flex",
              gap: 12,
              alignItems: "center",
              opacity: d.id === currentId ? 1 : 0.6,
              fontSize: 13,
            }}
          >
            <span
              style={{
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-soft)",
                fontSize: 11,
                width: 160,
                flexShrink: 0,
              }}
            >
              {d.created_at
                ? formatIso(d.created_at)
                : d.id.slice(0, 8)}
            </span>
            <span style={{ flex: 1 }}>{d.content.headline}</span>
            <span
              style={{
                fontFamily: "var(--wg-font-mono)",
                fontSize: 10,
                textTransform: "uppercase",
                color:
                  d.parse_outcome === "manual_review"
                    ? "var(--wg-amber)"
                    : "var(--wg-ink-soft)",
              }}
            >
              {d.parse_outcome}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
