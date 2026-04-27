"use client";

// SlaCard — Sprint 2b.
//
// Renders a sla-alert message in the owner's personal project stream.
// SlaService.check_project fanned the alert out when the backing
// commitment crossed either the DUE-SOON or OVERDUE band. The body
// is a JSON blob ({band, commitment_id, project_id, headline,
// target_date, seconds_remaining, sla_window_seconds}); we parse it
// and render a compact ambient card styled like DriftCard — amber for
// due-soon, accent-red for overdue.

import { useTranslations } from "next-intl";

import type { PersonalMessage } from "@/lib/api";

import { relativeTime,
  formatMessageTime } from "./types";

type SlaBand = "due_soon" | "overdue";

interface SlaPayload {
  band: SlaBand;
  commitment_id: string;
  project_id: string;
  headline: string;
  target_date: string;
  seconds_remaining: number;
  sla_window_seconds: number;
}

function parseBody(body: string): SlaPayload | null {
  try {
    const parsed = JSON.parse(body) as SlaPayload;
    if (!parsed || typeof parsed !== "object") return null;
    if (parsed.band !== "due_soon" && parsed.band !== "overdue") return null;
    if (typeof parsed.headline !== "string") return null;
    return parsed;
  } catch {
    return null;
  }
}

function humanize(totalSeconds: number): string {
  const abs = Math.abs(totalSeconds);
  const minutes = Math.round(abs / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(abs / 3600);
  if (hours < 48) return `${hours}h`;
  const days = Math.round(abs / 86400);
  return `${days}d`;
}

interface Props {
  message: PersonalMessage;
  onOpen?: (projectId: string, commitmentId: string) => void;
}

export function SlaCard({ message, onOpen }: Props) {
  const t = useTranslations();
  const payload = parseBody(message.body);
  if (payload === null) {
    // Malformed body — render a minimal fallback rather than crashing.
    return (
      <div
        data-testid="sla-card"
        style={{
          padding: "10px 14px",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          color: "var(--wg-ink-soft)",
          fontSize: 13,
        }}
      >
        {message.body}
      </div>
    );
  }

  const isOverdue = payload.band === "overdue";
  const accent = isOverdue ? "var(--wg-accent)" : "var(--wg-amber)";
  const bg = isOverdue
    ? "rgba(37, 99, 235,0.05)"
    : "var(--wg-amber-soft)";
  const bandLabel = isOverdue
    ? t("sla.overdue", { when: humanize(payload.seconds_remaining) })
    : t("sla.dueSoon", { when: humanize(payload.seconds_remaining) });

  return (
    <div
      data-testid="sla-card"
      role="status"
      style={{
        padding: "12px 14px",
        background: bg,
        border: `1px solid ${accent}`,
        borderRadius: "var(--wg-radius)",
        display: "flex",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: 10,
        }}
      >
        <strong
          style={{
            fontSize: 12,
            color: accent,
            fontFamily: "var(--wg-font-mono)",
            textTransform: "uppercase",
            letterSpacing: "0.06em",
          }}
        >
          {bandLabel}
        </strong>
        <span
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-faint)",
          }}
        >
          {formatMessageTime(message.created_at)}
        </span>
      </div>
      <div style={{ fontSize: 14, color: "var(--wg-ink)", lineHeight: 1.4 }}>
        ◎ {payload.headline}
      </div>
      <div
        style={{
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
        }}
      >
        target {new Date(payload.target_date).toLocaleString()}
      </div>
      {onOpen && (
        <button
          type="button"
          onClick={() => onOpen(payload.project_id, payload.commitment_id)}
          style={{
            marginTop: 2,
            alignSelf: "flex-start",
            background: "transparent",
            border: 0,
            padding: 0,
            color: accent,
            fontFamily: "var(--wg-font-mono)",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          {t("sla.ok") /* reuse an existing short label as "view" hint */}
          {" →"}
        </button>
      )}
    </div>
  );
}
