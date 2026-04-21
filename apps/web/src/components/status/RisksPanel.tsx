import { getTranslations } from "next-intl/server";

import type { ProjectState } from "@/lib/api";

import { ageSecondsFrom, formatAge, type Translator } from "./age";
import { EmptyState, Panel } from "./Panel";

type Risk = ProjectState["graph"]["risks"][number];

type Severity = "critical" | "high" | "medium" | "low";

const SEVERITY_RANK: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

// House signal-color rule (2026-04-21 unification pass):
//   critical / high → terracotta  (crystallization / critical)
//   medium          → amber       (escalation)
//   low             → ink-soft    (neutral / low priority)
// Was previously a custom mustard + cornflower-blue palette unrelated
// to the rest of the product.
const SEVERITY_COLOR: Record<Severity, string> = {
  critical: "var(--wg-accent)",
  high: "var(--wg-accent)",
  medium: "var(--wg-amber)",
  low: "var(--wg-ink-soft)",
};

// Open = anything NOT in this terminal set. Risks may have custom statuses
// across demos, so we allow the filter to be permissive.
const TERMINAL = new Set(["resolved", "dismissed", "closed", "mitigated"]);

function normalizeSeverity(s: string): Severity {
  if (s === "critical" || s === "high" || s === "medium" || s === "low") {
    return s;
  }
  return "medium";
}

function severityLabel(severity: Severity, t: Translator): string {
  switch (severity) {
    case "critical":
      return t("status.risks.severity.critical");
    case "high":
      return t("status.risks.severity.high");
    case "medium":
      return t("status.risks.severity.medium");
    case "low":
      return t("status.risks.severity.low");
  }
}

export async function RisksPanel({ risks }: { risks: Risk[] }) {
  const t = await getTranslations();
  const now = new Date();

  const open = risks
    .filter((r) => !TERMINAL.has(r.status))
    .map((r) => {
      const severity = normalizeSeverity(r.severity);
      // Risks in /state don't expose created_at today; degrade gracefully.
      const ageSeconds = ageSecondsFrom(
        (r as unknown as { created_at?: string }).created_at,
        now,
      );
      return { risk: r, severity, ageSeconds };
    })
    .sort((a, b) => {
      const s = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
      if (s !== 0) return s;
      // Older first within the same severity.
      return (b.ageSeconds ?? -1) - (a.ageSeconds ?? -1);
    });

  return (
    <Panel
      title={t("status.risks.title")}
      subtitle={open.length > 0 ? String(open.length) : undefined}
    >
      {open.length === 0 ? (
        <EmptyState>{t("status.risks.empty")}</EmptyState>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
            }}
          >
            <thead>
              <tr
                style={{
                  borderBottom: "1px solid var(--wg-line)",
                  textAlign: "left",
                }}
              >
                <Th>{t("status.risks.columnTitle")}</Th>
                <Th>{t("status.risks.columnSeverity")}</Th>
                <Th style={{ textAlign: "right" }}>
                  {t("status.risks.columnAge")}
                </Th>
              </tr>
            </thead>
            <tbody>
              {open.map(({ risk, severity, ageSeconds }) => (
                <tr
                  key={risk.id}
                  style={{ borderBottom: "1px solid var(--wg-line)" }}
                >
                  <Td>
                    <div style={{ fontWeight: 600 }}>{risk.title}</div>
                    {risk.content ? (
                      <div
                        style={{
                          fontSize: 12,
                          color: "var(--wg-ink-soft)",
                          marginTop: 2,
                        }}
                      >
                        {risk.content}
                      </div>
                    ) : null}
                  </Td>
                  <Td>
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: 6,
                        fontSize: 11,
                        fontFamily: "var(--wg-font-mono)",
                        color: SEVERITY_COLOR[severity],
                      }}
                    >
                      <span
                        aria-hidden="true"
                        style={{
                          width: 8,
                          height: 8,
                          borderRadius: "50%",
                          background: SEVERITY_COLOR[severity],
                        }}
                      />
                      {severityLabel(severity, t)}
                    </span>
                  </Td>
                  <Td
                    style={{
                      textAlign: "right",
                      fontFamily: "var(--wg-font-mono)",
                      color: "var(--wg-ink-soft)",
                      fontSize: 12,
                    }}
                  >
                    {formatAge(ageSeconds, t)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function Th({
  children,
  style,
}: {
  children?: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <th
      style={{
        padding: "8px 10px",
        fontSize: 11,
        letterSpacing: "0.04em",
        textTransform: "uppercase",
        color: "var(--wg-ink-soft)",
        fontWeight: 600,
        ...style,
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <td style={{ padding: "8px 10px", verticalAlign: "top", ...style }}>
      {children}
    </td>
  );
}
