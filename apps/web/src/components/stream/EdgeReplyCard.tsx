"use client";

// EdgeReplyCard — chat-stream refactor.
//
// Renders the sub-agent's direct reply in the user's personal project
// stream (north-star §"The canonical interaction" → "Answer" and
// "Clarify" outcomes). Two variants keyed by message kind:
//
//   * edge-answer   — the agent answered from graph/KB knowledge
//   * edge-clarify  — amber-tinted attribution; the agent is asking back
//   * edge-thinking — placeholder "thinking" variant
//
// Visual: flat-flowing prose, NOT a card. Small attribution chip at the
// top-left, then the body flows left-aligned like ChatGPT/Claude. No
// background, no border, no box. Reserved for conversational turns.
//
// The "Follow up…" button pre-fills the composer via `onFollowUp`.

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import type { PersonalMessage } from "@/lib/api";

import { CitedClaimList } from "./CitedClaimList";
import { relativeTime,
  formatMessageTime } from "./types";
import { formatIso } from "@/lib/time";

type Props = {
  message: PersonalMessage;
  projectId?: string;
  onFollowUp?: (prefill: string) => void;
  // When true, this turn is consecutive with the previous agent turn
  // (same author chain). We suppress the attribution chip so stacked
  // turns read as one continuous response, like Claude streaming.
  continuation?: boolean;
};

function labelKey(
  kind: PersonalMessage["kind"],
): "answer" | "clarify" | "thinking" | "unknown" {
  if (kind === "edge-clarify") return "clarify";
  if (kind === "edge-thinking") return "thinking";
  if (kind === "edge-answer") return "answer";
  return "unknown";
}

function chipColor(kind: PersonalMessage["kind"]): string {
  if (kind === "edge-clarify") return "var(--wg-amber)";
  if (kind === "edge-thinking") return "var(--wg-ink-faint)";
  return "var(--wg-ink-soft)";
}

function chipIcon(kind: PersonalMessage["kind"]): string {
  if (kind === "edge-clarify") return "❓";
  return "🤖";
}

export function EdgeReplyCard({
  message,
  projectId,
  onFollowUp,
  continuation = false,
}: Props) {
  const t = useTranslations("personal");
  const subLabel = t(`edge.${labelKey(message.kind)}`);
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
        // No card shell — just left-aligned flowing prose. Padding keeps
        // some breathing room on the left so text doesn't kiss the
        // scroller edge. Right margin leaves ~30% gutter so the line
        // length stays readable.
        padding: "2px 4px",
        marginRight: "20%",
        fontSize: "var(--wg-fs-body)",
      }}
    >
      {!continuation && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontFamily: "var(--wg-font-mono)",
            fontSize: 10,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            color: chipColor(message.kind),
            marginBottom: 4,
          }}
        >
          <span>
            <span aria-hidden>{chipIcon(message.kind)}</span>{" "}
            <strong style={{ color: "var(--wg-ink)" }}>
              {t("edge.attribution")}
            </strong>
            {" · "}
            <span>{subLabel}</span>
          </span>
          <span
            title={formatIso(message.created_at)}
            style={{ color: "var(--wg-ink-faint)" }}
          >
            {formatMessageTime(message.created_at)}
          </span>
        </div>
      )}
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
            lineHeight: 1.55,
          }}
        >
          {message.body}
        </div>
      )}
      {onFollowUp && (
        <Button
          variant="ghost"
          size="sm"
          onClick={handleFollowUp}
          data-testid="personal-follow-up-btn"
          style={{ marginTop: 6 }}
        >
          {t("followUp")}
        </Button>
      )}
    </div>
  );
}
