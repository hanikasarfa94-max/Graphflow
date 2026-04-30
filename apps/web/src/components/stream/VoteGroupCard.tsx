"use client";

// VoteGroupCard — the group (team) stream's runtime-log rendering for
// Phase S vote events. Rendered inline in StreamView for three kinds:
//
//   * `vote-opened` — amber card with threshold pill, proposal body,
//     class chip. Links to the proposal.
//   * `vote-resolved-approved` — green success card with tally.
//   * `vote-resolved-denied` — muted card with tally.
//
// These are runtime logs — the actual voting UX lives in each voter's
// sidebar inbox (GatedInboxItem). The group-stream cards exist to make
// the decision visible to the rest of the team, give non-voters a
// spectator view of the resolution, and leave a canonical audit entry.

import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";

import type { IMMessage } from "@/lib/api";
import { relativeTime,
  formatMessageTime } from "./types";

type Props = {
  message: IMMessage;
};

const CLASS_LABELS: Record<string, { en: string; zh: string }> = {
  budget: { en: "Budget", zh: "预算" },
  legal: { en: "Legal", zh: "法务" },
  hire: { en: "Hire", zh: "招聘" },
  scope_cut: { en: "Scope", zh: "范围" },
};

export function VoteGroupCard({ message }: Props) {
  const tv = useTranslations("vote");
  const kind = message.kind ?? "";
  const status: "opened" | "approved" | "denied" =
    kind === "vote-resolved-approved"
      ? "approved"
      : kind === "vote-resolved-denied"
        ? "denied"
        : "opened";

  // Body text is already self-describing ("🗳 Vote opened on scope cut:
  // trim auth (threshold 2/3)"). Strip the leading emoji — we'll render
  // our own icon + chrome — and sniff the decision_class if recognizable
  // at the head of the phrase.
  const body = message.body ?? "";
  const cls = detectClass(body);
  const text = stripLeadingIcon(body);

  const palette = paletteFor(status);

  return (
    <div
      data-testid="group-vote-card"
      data-kind={kind}
      data-proposal-id={message.linked_id ?? undefined}
      className={
        status === "approved" ? "wg-motion-crystallize" : undefined
      }
      style={{
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
        padding: "10px 12px",
        margin: "6px 0",
        background: palette.bg,
        border: `1px solid ${palette.border}`,
        borderLeft: `3px solid ${palette.accent}`,
        borderRadius: "var(--wg-radius)",
      }}
    >
      <span
        aria-hidden
        style={{
          fontSize: 18,
          lineHeight: 1,
          marginTop: 1,
        }}
      >
        {palette.icon}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 4,
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              fontFamily: "var(--wg-font-mono)",
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              color: palette.accent,
            }}
          >
            {status === "opened"
              ? tv("openedGroupEyebrow")
              : tv("resolvedGroupEyebrow")}
          </span>
          {cls ? <ClassChip cls={cls} /> : null}
          <span
            title={new Date(message.created_at).toLocaleString()}
            style={{
              marginLeft: "auto",
              fontFamily: "var(--wg-font-mono)",
              fontSize: 11,
              color: "var(--wg-ink-faint)",
            }}
          >
            {formatMessageTime(message.created_at)}
          </span>
        </div>
        <div
          style={{
            color: "var(--wg-ink)",
            fontSize: 13,
            lineHeight: 1.5,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {text}
        </div>
      </div>
    </div>
  );
}

function ClassChip({ cls }: { cls: string }) {
  const label = CLASS_LABELS[cls]?.en ?? cls;
  return (
    <span
      data-decision-class={cls}
      style={{
        padding: "1px 6px",
        background: "var(--wg-amber-soft)",
        color: "var(--wg-amber)",
        border: "1px solid var(--wg-amber)",
        borderRadius: "var(--wg-radius-sm, 4px)",
        fontSize: 10,
        fontFamily: "var(--wg-font-mono)",
        textTransform: "uppercase",
        letterSpacing: "0.04em",
        fontWeight: 600,
      }}
    >
      {label}
    </span>
  );
}

function paletteFor(status: "opened" | "approved" | "denied"): {
  bg: CSSProperties["background"];
  border: CSSProperties["borderColor"];
  accent: CSSProperties["color"];
  icon: string;
} {
  if (status === "approved") {
    return {
      bg: "var(--wg-ok-soft, var(--wg-surface-sunk))",
      border: "var(--wg-line)",
      accent: "var(--wg-ok)",
      icon: "✓",
    };
  }
  if (status === "denied") {
    return {
      bg: "var(--wg-surface-sunk)",
      border: "var(--wg-line)",
      accent: "var(--wg-ink-soft)",
      icon: "✗",
    };
  }
  return {
    bg: "var(--wg-amber-soft, var(--wg-surface-sunk))",
    border: "var(--wg-line)",
    accent: "var(--wg-amber)",
    icon: "🗳",
  };
}

function stripLeadingIcon(s: string): string {
  // Strip the leading icon + any trailing space so our own icon slot
  // is the single source of visual truth.
  return s.replace(/^[\p{Emoji_Presentation}\p{Extended_Pictographic}☀-➿]\s*/u, "");
}

function detectClass(s: string): string | null {
  // The service composes "on {class_label}" — we look for a canonical
  // class label in the body to drive the chip without a separate
  // field. Best-effort; missing → no chip.
  const lower = s.toLowerCase();
  if (lower.includes("scope")) return "scope_cut";
  if (lower.includes("budget")) return "budget";
  if (lower.includes("legal")) return "legal";
  if (lower.includes("hire")) return "hire";
  return null;
}
