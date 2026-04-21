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

import { Button } from "@/components/ui";
import type { CitedClaim, PersonalMessage } from "@/lib/api";

import { CitedClaimList } from "./CitedClaimList";
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
  claims?: CitedClaim[];
  uncited?: boolean;
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
      claims: Array.isArray(parsed.claims)
        ? (parsed.claims.filter(
            (c): c is CitedClaim =>
              c !== null &&
              typeof c === "object" &&
              typeof (c as CitedClaim).text === "string",
          ) as CitedClaim[])
        : undefined,
      uncited: typeof parsed.uncited === "boolean" ? parsed.uncited : undefined,
    };
  } catch {
    return null;
  }
}

// Severity → accent colour + label variant. House signal-color rule
// (2026-04-21 unification pass): drift severity rides the same
// terracotta / amber / sunk triad as the rest of the product. The
// previous `#fbecec` / `#fbf0dd` / `#fbf6e5` hex soups are gone — they
// drifted away from the token palette and from risk severity in status
// panels.
//
//   high    → terracotta accent (same as risk critical/high) — this is
//             the alarm signal the user is most likely to react to.
//   medium  → amber accent (same as risk medium / manual_review) — an
//             escalation, not a crash.
//   low     → neutral sunk surface + ink-soft rail — ambient.
function severityStyle(severity: DriftSeverity): {
  borderLeft: string;
  background: string;
  badge: string;
  icon: string;
} {
  if (severity === "high") {
    return {
      borderLeft: "3px solid var(--wg-accent)",
      background: "var(--wg-accent-soft)",
      badge: "var(--wg-accent)",
      icon: "⚠️",
    };
  }
  if (severity === "medium") {
    return {
      borderLeft: "3px solid var(--wg-amber)",
      background: "var(--wg-amber-soft)",
      badge: "var(--wg-amber)",
      icon: "⚠️",
    };
  }
  return {
    borderLeft: "3px solid var(--wg-ink-soft)",
    background: "var(--wg-surface-sunk)",
    badge: "var(--wg-ink-soft)",
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
  borderRadius: "var(--wg-radius-sm)",
  background: color,
  color: "var(--wg-surface-raised)",
  fontSize: 10,
  fontFamily: "var(--wg-font-mono)",
  letterSpacing: 0.5,
  textTransform: "uppercase",
  marginLeft: 6,
});

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
          marginBottom: 10,
          marginLeft: 42,
          padding: "14px",
          background: "var(--wg-surface-sunk)",
          border: "1px solid var(--wg-line)",
          borderLeft: "3px solid var(--wg-amber)",
          borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
          fontSize: "var(--wg-fs-body)",
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
        marginBottom: 10,
        marginLeft: 42,
        padding: "14px",
        background: style.background,
        border: "1px solid var(--wg-line)",
        borderLeft: style.borderLeft,
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontSize: "var(--wg-fs-body)",
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

      {parsed.claims && parsed.claims.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <CitedClaimList
            projectId={parsed.project_id ?? message.project_id ?? ""}
            claims={parsed.claims}
          />
        </div>
      )}

      {onDiscuss && (
        <Button
          variant="ghost"
          size="sm"
          onClick={handleDiscuss}
          data-testid="personal-drift-discuss-btn"
          style={{ marginTop: 10 }}
        >
          {t("discussWithEdge")}
        </Button>
      )}
    </div>
  );
}
