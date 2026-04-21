"use client";

// EdgeReplyCard — Phase N.
//
// Renders the sub-agent's direct reply in the user's personal project
// stream (north-star §"The canonical interaction" → "Answer" and
// "Clarify" outcomes). Two variants keyed by message kind:
//
//   * edge-answer   — neutral warm-beige card; the agent answered from
//                     graph/KB knowledge.
//   * edge-clarify  — amber-accented card; the agent is asking a
//                     clarifying question back.
//   * edge-thinking — soft placeholder "thinking" variant (unused in v1
//                     but supported so streaming UX can drop in later).
//
// The "Follow up…" button pre-fills the composer with `Re: <first 40>`
// via the `onFollowUp` callback. Parent owns the composer state.

import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";

import type { PersonalMessage } from "@/lib/api";

import { CitedClaimList } from "./CitedClaimList";
import { relativeTime } from "./types";

type Props = {
  message: PersonalMessage;
  projectId?: string;
  onFollowUp?: (prefill: string) => void;
};

// Variant styling — answer is the default warm surface; clarify leans on
// the amber token; thinking uses a faint surface with italic tone.
function variantStyle(kind: PersonalMessage["kind"]): {
  background: string;
  borderLeft: string;
  subLabelKey: "answer" | "clarify" | "thinking" | "unknown";
} {
  if (kind === "edge-clarify") {
    return {
      background: "#fdf6ea",
      borderLeft: "3px solid var(--wg-amber)",
      subLabelKey: "clarify",
    };
  }
  if (kind === "edge-thinking") {
    return {
      background: "var(--wg-surface-sunk, #faf8f4)",
      borderLeft: "3px solid var(--wg-ink-faint)",
      subLabelKey: "thinking",
    };
  }
  if (kind === "edge-answer") {
    return {
      background: "#f7f3ed",
      borderLeft: "3px solid var(--wg-accent-ring, var(--wg-accent))",
      subLabelKey: "answer",
    };
  }
  return {
    background: "#f7f3ed",
    borderLeft: "3px solid var(--wg-ink-faint)",
    subLabelKey: "unknown",
  };
}

const followUpBtn: CSSProperties = {
  marginTop: 8,
  padding: "4px 10px",
  background: "transparent",
  color: "var(--wg-ink-soft)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  cursor: "pointer",
};

export function EdgeReplyCard({ message, projectId, onFollowUp }: Props) {
  const t = useTranslations("personal");
  const variant = variantStyle(message.kind);
  const subLabel = t(`edge.${variant.subLabelKey}`);
  const effectiveProjectId = projectId ?? message.project_id ?? "";
  const claims = message.claims ?? [];
  const hasClaims = claims.length > 0;
  const isUncited = message.uncited === true;

  function handleFollowUp() {
    if (!onFollowUp) return;
    const snippet = message.body.slice(0, 40).replace(/\s+/g, " ").trim();
    onFollowUp(`${t("followUpPrefix")}${snippet}${snippet.length === 40 ? "…" : ""} `);
  }

  return (
    <div
      data-testid="personal-edge-card"
      data-message-id={message.id}
      data-kind={message.kind}
      style={{
        marginBottom: 12,
        marginLeft: 42,
        padding: "10px 14px",
        background: variant.background,
        border: "1px solid var(--wg-line)",
        borderLeft: variant.borderLeft,
        borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
        fontSize: 13,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontFamily: "var(--wg-font-mono)",
          fontSize: 11,
          color: "var(--wg-ink-soft)",
          marginBottom: 6,
        }}
      >
        <span>
          <strong style={{ color: "var(--wg-ink)" }}>{t("edge.attribution")}</strong>
          {" — "}
          <span>{subLabel}</span>
        </span>
        <span title={new Date(message.created_at).toLocaleString()}>
          {relativeTime(message.created_at)}
        </span>
      </div>
      {hasClaims ? (
        <CitedClaimList
          projectId={effectiveProjectId}
          claims={claims}
        />
      ) : (
        <div
          data-uncited={isUncited ? "true" : "false"}
          style={{
            color: isUncited ? "var(--wg-ink-faint)" : "var(--wg-ink)",
            fontStyle: isUncited ? "italic" : "normal",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {message.body}
        </div>
      )}
      {onFollowUp && (
        <button
          type="button"
          onClick={handleFollowUp}
          data-testid="personal-follow-up-btn"
          style={followUpBtn}
        >
          {t("followUp")}
        </button>
      )}
    </div>
  );
}
