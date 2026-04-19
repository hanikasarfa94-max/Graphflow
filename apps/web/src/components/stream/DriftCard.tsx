"use client";

// DriftCard — vision.md §5.8.
//
// Renders a drift-alert message in the user's personal project stream.
// Drift-alerts are ambient signal cards: the edge agent noticed that
// recent execution has diverged from the committed thesis or a recent
// decision, and routed the observation to the people whose work is
// driving the divergence (or who decided the thing being drifted from).
//
// The message body is a JSON-encoded DriftItem (plus `project_id`),
// produced server-side by DriftService._encode_drift_body. We parse
// defensively — on parse failure the card degrades to a plain body
// render so a schema change downstream never crashes the stream.
//
// The "Discuss with edge" button pre-fills the composer with the
// headline as a follow-up question, so the user can escalate the drift
// into a conversation with their sub-agent in one click.

import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";

import type { PersonalMessage } from "@/lib/api";

import { relativeTime } from "./types";

type Props = {
  message: PersonalMessage;
  onDiscuss?: (prefill: string) => void;
};

// Parsed shape — mirrors agents/src/workgraph_agents/drift.py DriftItem
// plus a project_id the service inlines at post time.
type DriftSeverity = "low" | "medium" | "high";
interface ParsedDriftItem {
  headline: string;
  severity: DriftSeverity;
  what_drifted: string;
  vs_thesis_or_decision: string;
  suggested_next_step: string;
  affected_user_ids: string[];
  project_id?: string;
}

function parseBody(body: string): ParsedDriftItem | null {
  try {
    const parsed = JSON.parse(body) as Partial<ParsedDriftItem>;
    if (
      typeof parsed.headline !== "string" ||
      typeof parsed.what_drifted !== "string" ||
      typeof parsed.vs_thesis_or_decision !== "string" ||
      typeof parsed.suggested_next_step !== "string"
    ) {
      return null;
    }
    const severity =
      parsed.severity === "low" ||
      parsed.severity === "medium" ||
      parsed.severity === "high"
        ? parsed.severity
        : "medium";
    return {
      headline: parsed.headline,
      severity,
      what_drifted: parsed.what_drifted,
      vs_thesis_or_decision: parsed.vs_thesis_or_decision,
      suggested_next_step: parsed.suggested_next_step,
      affected_user_ids: Array.isArray(parsed.affected_user_ids)
        ? (parsed.affected_user_ids.filter(
            (s): s is string => typeof s === "string",
          ) as string[])
        : [],
      project_id:
        typeof parsed.project_id === "string" ? parsed.project_id : undefined,
    };
  } catch {
    return null;
  }
}

// Severity → accent colour + label variant. We lean on the existing
// amber/red tokens where available, with conservative fallbacks so the
// card still reads if the tokens aren't loaded.
function severityStyle(severity: DriftSeverity): {
  borderLeft: string;
  background: string;
  badge: string;
  icon: string;
} {
  if (severity === "high") {
    return {
      borderLeft: "3px solid var(--wg-danger, #c33b3b)",
      background: "#fbecec",
      badge: "var(--wg-danger, #c33b3b)",
      icon: "⚠️",
    };
  }
  if (severity === "medium") {
    return {
      borderLeft: "3px solid var(--wg-accent, #c58a3f)",
      background: "#fbf0dd",
      badge: "var(--wg-accent, #c58a3f)",
      icon: "⚠️",
    };
  }
  return {
    borderLeft: "3px solid var(--wg-amber, #d9a520)",
    background: "#fbf6e5",
    badge: "var(--wg-amber, #d9a520)",
    icon: "⚠️",
  };
}

const headerRow: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  fontFamily: "var(--wg-font-mono)",
  fontSize: 11,
  color: "var(--wg-ink-soft)",
  marginBottom: 6,
};

const severityBadge = (color: string): CSSProperties => ({
  display: "inline-block",
  padding: "1px 6px",
  borderRadius: "var(--wg-radius-sm, 4px)",
  background: color,
  color: "#fff",
  fontSize: 10,
  fontFamily: "var(--wg-font-mono)",
  letterSpacing: 0.5,
  textTransform: "uppercase",
  marginLeft: 6,
});

const discussBtn: CSSProperties = {
  marginTop: 10,
  padding: "5px 12px",
  background: "transparent",
  color: "var(--wg-ink-soft)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  cursor: "pointer",
};

const fieldLabel: CSSProperties = {
  fontFamily: "var(--wg-font-mono)",
  fontSize: 10,
  letterSpacing: 0.4,
  textTransform: "uppercase",
  color: "var(--wg-ink-soft)",
  marginTop: 8,
  marginBottom: 2,
};

const fieldValue: CSSProperties = {
  color: "var(--wg-ink)",
  fontStyle: "italic",
  fontSize: 13,
  lineHeight: "18px",
};

export function DriftCard({ message, onDiscuss }: Props) {
  const t = useTranslations("drift");
  const parsed = parseBody(message.body);

  // Degrade to a plain text render when the body doesn't parse; keeps
  // the stream functional if the server ships a new shape we don't yet
  // understand.
  if (parsed === null) {
    return (
      <div
        data-testid="personal-drift-card-fallback"
        data-message-id={message.id}
        style={{
          marginBottom: 12,
          marginLeft: 42,
          padding: "10px 14px",
          background: "#fbf6e5",
          border: "1px solid var(--wg-line)",
          borderLeft: "3px solid var(--wg-amber, #d9a520)",
          borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
          fontSize: 13,
          color: "var(--wg-ink)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        <div style={headerRow}>
          <span>
            <strong>{t("alertTitle")}</strong>
          </span>
          <span title={new Date(message.created_at).toLocaleString()}>
            {relativeTime(message.created_at)}
          </span>
        </div>
        {message.body}
      </div>
    );
  }

  const style = severityStyle(parsed.severity);

  function handleDiscuss() {
    if (!onDiscuss) return;
    onDiscuss(parsed!.headline);
  }

  return (
    <div
      data-testid="personal-drift-card"
      data-message-id={message.id}
      data-severity={parsed.severity}
      style={{
        marginBottom: 12,
        marginLeft: 42,
        padding: "10px 14px",
        background: style.background,
        border: "1px solid var(--wg-line)",
        borderLeft: style.borderLeft,
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontSize: 13,
      }}
    >
      <div style={headerRow}>
        <span>
          <span aria-hidden="true" style={{ marginRight: 6 }}>
            {style.icon}
          </span>
          <strong style={{ color: "var(--wg-ink)" }}>{t("alertTitle")}</strong>
          <span style={severityBadge(style.badge)}>
            {t(`severity.${parsed.severity}`)}
          </span>
        </span>
        <span title={new Date(message.created_at).toLocaleString()}>
          {relativeTime(message.created_at)}
        </span>
      </div>

      <div
        style={{
          fontSize: 15,
          fontWeight: 600,
          color: "var(--wg-ink)",
          lineHeight: "20px",
          marginBottom: 4,
        }}
      >
        {parsed.headline}
      </div>

      <div style={fieldLabel}>{t("driftingFrom")}</div>
      <div style={fieldValue}>{parsed.vs_thesis_or_decision}</div>

      <div style={fieldLabel}>{t("whatChanged")}</div>
      <div style={fieldValue}>{parsed.what_drifted}</div>

      <div style={fieldLabel}>{t("suggestedNext")}</div>
      <div style={{ ...fieldValue, fontStyle: "normal" }}>
        {parsed.suggested_next_step}
      </div>

      {onDiscuss && (
        <button
          type="button"
          onClick={handleDiscuss}
          data-testid="personal-drift-discuss-btn"
          style={discussBtn}
        >
          {t("discussWithEdge")}
        </button>
      )}
    </div>
  );
}
