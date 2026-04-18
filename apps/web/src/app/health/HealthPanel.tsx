"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

export interface AgentSummary {
  count: number;
  outcomes: Record<string, number>;
  latency_ms: { p50: number; p95: number; max: number };
  prompt_tokens: number;
  completion_tokens: number;
  cache_read_tokens: number;
  last_seen: string | null;
}

export interface HealthSummary {
  window_minutes: number;
  since: string;
  now: string;
  totals: AgentSummary;
  agents: Record<string, AgentSummary>;
}

const WINDOWS: Array<{ label: string; minutes: number }> = [
  { label: "15m", minutes: 15 },
  { label: "1h", minutes: 60 },
  { label: "24h", minutes: 60 * 24 },
  { label: "7d", minutes: 60 * 24 * 7 },
];

const OUTCOME_COLORS: Record<string, string> = {
  ok: "var(--wg-ok)",
  retry: "var(--wg-amber)",
  manual_review: "var(--wg-accent)",
};

export function HealthPanel({ initial }: { initial: HealthSummary }) {
  const [summary, setSummary] = useState<HealthSummary>(initial);
  const [windowMinutes, setWindowMinutes] = useState<number>(
    initial.window_minutes,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    async (minutes: number) => {
      setLoading(true);
      setError(null);
      try {
        const data = await api<HealthSummary>(
          `/api/observability/health?window_minutes=${minutes}`,
        );
        setSummary(data);
        setWindowMinutes(minutes);
      } catch (e: unknown) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    const t = setInterval(() => {
      void refresh(windowMinutes);
    }, 15000);
    return () => clearInterval(t);
  }, [refresh, windowMinutes]);

  const agentNames = Object.keys(summary.agents);

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "var(--wg-surface)",
        color: "var(--wg-ink)",
        padding: "var(--wg-s-5)",
        fontFamily: "var(--wg-font-sans)",
      }}
      data-testid="health-panel"
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: "var(--wg-s-4)",
          marginBottom: "var(--wg-s-4)",
        }}
      >
        <div>
          <h1 style={{ fontSize: "24px", margin: 0, fontWeight: 600 }}>
            Agent health
          </h1>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: "13px",
              color: "rgba(26,26,26,0.6)",
            }}
          >
            Rolling window · {summary.totals.count} runs · since{" "}
            <code style={{ fontFamily: "var(--wg-font-mono)" }}>
              {new Date(summary.since).toLocaleString()}
            </code>
          </p>
        </div>
        <div style={{ display: "flex", gap: "var(--wg-s-2)" }}>
          {WINDOWS.map((w) => (
            <button
              key={w.minutes}
              data-testid={`window-${w.label}`}
              onClick={() => void refresh(w.minutes)}
              style={{
                padding: "6px 12px",
                border:
                  w.minutes === windowMinutes
                    ? "1px solid var(--wg-accent)"
                    : "1px solid rgba(26,26,26,0.15)",
                background:
                  w.minutes === windowMinutes
                    ? "var(--wg-accent)"
                    : "transparent",
                color:
                  w.minutes === windowMinutes ? "white" : "var(--wg-ink)",
                fontFamily: "var(--wg-font-mono)",
                fontSize: "12px",
                cursor: "pointer",
                borderRadius: "2px",
              }}
            >
              {w.label}
            </button>
          ))}
        </div>
      </header>

      {error && (
        <div
          role="alert"
          style={{
            padding: "var(--wg-s-3)",
            border: "1px solid var(--wg-accent)",
            color: "var(--wg-accent)",
            marginBottom: "var(--wg-s-4)",
          }}
        >
          {error}
        </div>
      )}

      <TotalsCard totals={summary.totals} loading={loading} />

      <section
        aria-label="Per-agent summary"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: "var(--wg-s-3)",
          marginTop: "var(--wg-s-4)",
        }}
      >
        {agentNames.length === 0 ? (
          <div
            style={{
              gridColumn: "1 / -1",
              padding: "var(--wg-s-5)",
              border: "1px dashed rgba(26,26,26,0.2)",
              textAlign: "center",
              color: "rgba(26,26,26,0.5)",
            }}
            data-testid="health-empty"
          >
            No agent runs in the selected window.
          </div>
        ) : (
          agentNames.map((name) => (
            <AgentCard key={name} name={name} summary={summary.agents[name]} />
          ))
        )}
      </section>
    </main>
  );
}

function TotalsCard({
  totals,
  loading,
}: {
  totals: AgentSummary;
  loading: boolean;
}) {
  return (
    <section
      aria-label="Totals"
      data-testid="totals-card"
      style={{
        padding: "var(--wg-s-4)",
        border: "1px solid rgba(26,26,26,0.1)",
        background: "white",
        borderRadius: "2px",
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: "var(--wg-s-4)",
      }}
    >
      <Stat
        label={loading ? "refreshing…" : "Runs"}
        value={String(totals.count)}
      />
      <Stat
        label="Latency p50 / p95"
        value={`${totals.latency_ms.p50} / ${totals.latency_ms.p95} ms`}
      />
      <Stat
        label="Prompt / completion tokens"
        value={`${totals.prompt_tokens.toLocaleString()} / ${totals.completion_tokens.toLocaleString()}`}
      />
      <Stat
        label="Cache read tokens"
        value={totals.cache_read_tokens.toLocaleString()}
      />
    </section>
  );
}

function AgentCard({ name, summary }: { name: string; summary: AgentSummary }) {
  const total = summary.count || 1;
  return (
    <article
      data-testid={`agent-card-${name}`}
      style={{
        padding: "var(--wg-s-3)",
        border: "1px solid rgba(26,26,26,0.1)",
        background: "white",
        borderRadius: "2px",
        display: "flex",
        flexDirection: "column",
        gap: "var(--wg-s-2)",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <h3
          style={{
            margin: 0,
            fontSize: "14px",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {name}
        </h3>
        <span style={{ fontSize: "12px", color: "rgba(26,26,26,0.6)" }}>
          {summary.count} runs
        </span>
      </header>
      <div
        style={{
          display: "flex",
          height: "8px",
          borderRadius: "4px",
          overflow: "hidden",
          background: "rgba(26,26,26,0.06)",
        }}
      >
        {Object.entries(summary.outcomes).map(([outcome, count]) => (
          <div
            key={outcome}
            title={`${outcome}: ${count}`}
            style={{
              width: `${(count / total) * 100}%`,
              background: OUTCOME_COLORS[outcome] ?? "#999",
            }}
          />
        ))}
      </div>
      <dl
        style={{
          margin: 0,
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: "6px 12px",
          fontSize: "12px",
        }}
      >
        <Row
          k="p50 / p95"
          v={`${summary.latency_ms.p50} / ${summary.latency_ms.p95} ms`}
        />
        <Row k="max" v={`${summary.latency_ms.max} ms`} />
        <Row k="prompt tok" v={summary.prompt_tokens.toLocaleString()} />
        <Row k="completion tok" v={summary.completion_tokens.toLocaleString()} />
        <Row
          k="cache read tok"
          v={summary.cache_read_tokens.toLocaleString()}
        />
        <Row
          k="last seen"
          v={summary.last_seen ? new Date(summary.last_seen).toLocaleTimeString() : "—"}
        />
      </dl>
    </article>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div
        style={{
          fontSize: "11px",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          color: "rgba(26,26,26,0.5)",
        }}
      >
        {label}
      </div>
      <div
        style={{
          marginTop: "4px",
          fontSize: "18px",
          fontFamily: "var(--wg-font-mono)",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt style={{ color: "rgba(26,26,26,0.55)" }}>{k}</dt>
      <dd
        style={{
          margin: 0,
          fontFamily: "var(--wg-font-mono)",
          textAlign: "right",
        }}
      >
        {v}
      </dd>
    </>
  );
}
