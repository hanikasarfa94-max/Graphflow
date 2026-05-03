"use client";

import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Delivery, ProjectState } from "@/lib/api";
import { formatIso } from "@/lib/time";

type WsFrame = { type: string; payload: Record<string, unknown> };

type Task = ProjectState["plan"]["tasks"][number];

const OUTCOME_LABEL: Record<Delivery["parse_outcome"], string> = {
  ok: "ready",
  retry: "retry",
  manual_review: "manual review",
};

const OUTCOME_COLOR: Record<Delivery["parse_outcome"], string> = {
  ok: "#4a7ac7",
  retry: "#d97706",
  manual_review: "var(--wg-accent)",
};

const SEVERITY_COLOR: Record<"low" | "medium" | "high", string> = {
  high: "var(--wg-accent)",
  medium: "#d97706",
  low: "var(--wg-ink-soft)",
};

export function DeliveryPane({
  projectId,
  initialLatest,
  initialHistory,
  initialTasks,
}: {
  projectId: string;
  initialLatest: Delivery | null;
  initialHistory: Delivery[];
  initialTasks: Task[];
}) {
  const t = useTranslations("qaSweep");
  const [latest, setLatest] = useState<Delivery | null>(initialLatest);
  const [history, setHistory] = useState<Delivery[]>(initialHistory);
  const [tasks] = useState<Task[]>(initialTasks);
  const [wsState, setWsState] = useState<"connecting" | "open" | "closed">(
    "connecting",
  );
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  const tasksById = useMemo(() => {
    const m = new Map<string, Task>();
    for (const t of tasks) m.set(t.id, t);
    return m;
  }, [tasks]);

  useEffect(() => {
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${proto}//${window.location.host}/ws/projects/${projectId}`,
    );
    setWsState("connecting");
    ws.onopen = () => setWsState("open");
    ws.onclose = () => setWsState("closed");
    ws.onerror = () => setWsState("closed");
    ws.onmessage = (ev) => {
      try {
        const frame = JSON.parse(ev.data) as WsFrame;
        if (frame.type === "delivery") {
          const d = frame.payload as unknown as Delivery;
          setLatest(d);
          setHistory((prev) => {
            const without = prev.filter((x) => x.id !== d.id);
            return [d, ...without];
          });
        }
      } catch {
        // ignore malformed frame
      }
    };
    return () => ws.close();
  }, [projectId]);

  async function generate() {
    setGenerating(true);
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
        setLatest(body.delivery);
        setHistory((prev) => {
          const without = prev.filter((x) => x.id !== body.delivery.id);
          return [body.delivery, ...without];
        });
      }
    } finally {
      if (mounted.current) setGenerating(false);
    }
  }

  return (
    <section
      data-testid="delivery-pane"
      style={{ display: "flex", flexDirection: "column", gap: 24, padding: 24 }}
    >
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: 20 }}>{t("deliverySummary")}</h2>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: 13,
              color: "var(--wg-ink-soft)",
            }}
          >
            Generated narrative covering every scope item, cited decisions, and
            remaining risks.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span
            aria-label={`ws ${wsState}`}
            title={`websocket ${wsState}`}
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              background:
                wsState === "open"
                  ? "#4ac78a"
                  : wsState === "connecting"
                    ? "#d97706"
                    : "var(--wg-ink-soft)",
            }}
          />
          <button
            data-testid="generate-delivery"
            onClick={generate}
            disabled={generating}
            style={{
              padding: "8px 14px",
              fontSize: 14,
              fontWeight: 600,
              background: "var(--wg-accent)",
              color: "#fff",
              border: 0,
              borderRadius: 6,
              cursor: generating ? "wait" : "pointer",
              opacity: generating ? 0.7 : 1,
            }}
          >
            {generating ? "Generating…" : latest ? "Regenerate" : "Generate"}
          </button>
        </div>
      </header>

      {error ? (
        <div
          role="alert"
          style={{
            padding: 12,
            background: "rgba(199,68,74,0.08)",
            border: "1px solid var(--wg-accent)",
            borderRadius: 4,
            fontSize: 13,
          }}
        >
          {error}
        </div>
      ) : null}

      {latest ? (
        <LatestSummary delivery={latest} tasksById={tasksById} />
      ) : (
        <div
          data-testid="delivery-empty"
          style={{
            padding: 32,
            border: "1px dashed var(--wg-line)",
            borderRadius: 6,
            textAlign: "center",
            color: "var(--wg-ink-soft)",
          }}
        >
          No delivery summary yet. Click{" "}
          <strong style={{ color: "var(--wg-ink)" }}>Generate</strong> to
          produce one from the current plan + decisions.
        </div>
      )}

      {history.length > 1 ? (
        <HistoryList history={history} currentId={latest?.id ?? null} />
      ) : null}
    </section>
  );
}

function LatestSummary({
  delivery,
  tasksById,
}: {
  delivery: Delivery;
  tasksById: Map<string, Task>;
}) {
  const c = delivery.content;
  const qa = delivery.qa_report;

  return (
    <article
      data-testid="delivery-latest"
      style={{
        border: "1px solid var(--wg-line)",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <header
        style={{
          padding: "16px 20px",
          borderBottom: "1px solid var(--wg-line)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 16,
        }}
      >
        <div>
          <h3
            data-testid="delivery-headline"
            style={{ margin: 0, fontSize: 18 }}
          >
            {c.headline}
          </h3>
          <div
            style={{
              marginTop: 6,
              fontSize: 12,
              color: "var(--wg-ink-soft)",
              fontFamily: "var(--wg-font-mono)",
            }}
          >
            {delivery.created_at
              ? formatIso(delivery.created_at)
              : ""}
            {delivery.prompt_version
              ? ` · prompt ${delivery.prompt_version}`
              : ""}
          </div>
        </div>
        <span
          data-testid="delivery-outcome"
          style={{
            fontSize: 11,
            fontWeight: 600,
            padding: "4px 8px",
            borderRadius: 10,
            background: OUTCOME_COLOR[delivery.parse_outcome],
            color: "#fff",
            whiteSpace: "nowrap",
          }}
        >
          {OUTCOME_LABEL[delivery.parse_outcome]}
        </span>
      </header>

      {c.narrative ? (
        <section style={{ padding: 20, borderBottom: "1px solid var(--wg-line)" }}>
          <p
            data-testid="delivery-narrative"
            style={{
              margin: 0,
              fontSize: 14,
              lineHeight: 1.55,
              whiteSpace: "pre-wrap",
            }}
          >
            {c.narrative}
          </p>
        </section>
      ) : null}

      {qa.uncovered.length > 0 ? (
        <section
          data-testid="delivery-qa-warning"
          style={{
            padding: "12px 20px",
            background: "rgba(199,68,74,0.06)",
            borderBottom: "1px solid var(--wg-line)",
            fontSize: 13,
          }}
        >
          <strong>QA flagged {qa.uncovered.length} uncovered scope item(s):</strong>{" "}
          {qa.uncovered.join(", ")}
        </section>
      ) : null}

      <section style={{ padding: 20, borderBottom: "1px solid var(--wg-line)" }}>
        <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>
          Completed scope ({c.completed_scope.length})
        </h4>
        {c.completed_scope.length === 0 ? (
          <p style={{ margin: 0, fontSize: 13, color: "var(--wg-ink-soft)" }}>
            None.
          </p>
        ) : (
          <ul
            data-testid="delivery-completed"
            style={{ margin: 0, padding: 0, listStyle: "none" }}
          >
            {c.completed_scope.map((item) => (
              <li
                key={item.scope_item}
                data-testid="completed-item"
                style={{
                  padding: "8px 0",
                  borderBottom: "1px solid var(--wg-line)",
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 16,
                }}
              >
                <span style={{ fontSize: 14 }}>{item.scope_item}</span>
                <span
                  style={{
                    fontSize: 12,
                    color: "var(--wg-ink-soft)",
                    fontFamily: "var(--wg-font-mono)",
                  }}
                >
                  {item.evidence_task_ids.length > 0
                    ? item.evidence_task_ids
                        .map((id) => tasksById.get(id)?.title ?? id)
                        .join(", ")
                    : "—"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {c.deferred_scope.length > 0 ? (
        <section
          style={{ padding: 20, borderBottom: "1px solid var(--wg-line)" }}
        >
          <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>
            Deferred scope ({c.deferred_scope.length})
          </h4>
          <ul
            data-testid="delivery-deferred"
            style={{ margin: 0, padding: 0, listStyle: "none" }}
          >
            {c.deferred_scope.map((item) => (
              <li
                key={item.scope_item}
                data-testid="deferred-item"
                style={{
                  padding: "8px 0",
                  borderBottom: "1px solid var(--wg-line)",
                }}
              >
                <div style={{ fontSize: 14, fontWeight: 500 }}>
                  {item.scope_item}
                </div>
                <div
                  style={{
                    fontSize: 13,
                    color: "var(--wg-ink-soft)",
                    marginTop: 2,
                  }}
                >
                  {item.reason}
                </div>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {c.key_decisions.length > 0 ? (
        <section
          style={{ padding: 20, borderBottom: "1px solid var(--wg-line)" }}
        >
          <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>
            Key decisions ({c.key_decisions.length})
          </h4>
          <ul
            data-testid="delivery-decisions"
            style={{ margin: 0, padding: 0, listStyle: "none" }}
          >
            {c.key_decisions.map((d) => (
              <li
                key={d.decision_id}
                data-testid="decision-item"
                style={{
                  padding: "8px 0",
                  borderBottom: "1px solid var(--wg-line)",
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
        </section>
      ) : null}

      {c.remaining_risks.length > 0 ? (
        <section style={{ padding: 20 }}>
          <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>
            Remaining risks ({c.remaining_risks.length})
          </h4>
          <ul
            data-testid="delivery-risks"
            style={{ margin: 0, padding: 0, listStyle: "none" }}
          >
            {c.remaining_risks.map((r) => (
              <li
                key={r.title}
                data-testid="risk-item"
                style={{
                  padding: "8px 0",
                  borderBottom: "1px solid var(--wg-line)",
                  display: "flex",
                  gap: 12,
                  alignItems: "flex-start",
                }}
              >
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    padding: "2px 6px",
                    borderRadius: 8,
                    background: SEVERITY_COLOR[r.severity],
                    color: "#fff",
                    whiteSpace: "nowrap",
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
        </section>
      ) : null}
    </article>
  );
}

function HistoryList({
  history,
  currentId,
}: {
  history: Delivery[];
  currentId: string | null;
}) {
  return (
    <section
      data-testid="delivery-history"
      style={{
        border: "1px solid var(--wg-line)",
        borderRadius: 8,
        padding: 16,
      }}
    >
      <h4 style={{ margin: "0 0 12px", fontSize: 14 }}>
        Regeneration history ({history.length})
      </h4>
      <ol style={{ margin: 0, padding: 0, listStyle: "none" }}>
        {history.map((d) => (
          <li
            key={d.id}
            data-testid="history-row"
            style={{
              padding: "8px 0",
              borderBottom: "1px solid var(--wg-line)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 12,
              fontSize: 13,
              opacity: d.id === currentId ? 1 : 0.7,
            }}
          >
            <span
              style={{
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-ink-soft)",
              }}
            >
              {d.created_at
                ? formatIso(d.created_at)
                : d.id.slice(0, 8)}
            </span>
            <span style={{ flex: 1, marginLeft: 12 }}>
              {d.content.headline}
            </span>
            <span
              style={{
                fontSize: 11,
                fontWeight: 600,
                padding: "2px 6px",
                borderRadius: 8,
                background: OUTCOME_COLOR[d.parse_outcome],
                color: "#fff",
              }}
            >
              {OUTCOME_LABEL[d.parse_outcome]}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
