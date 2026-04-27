"use client";

// Migration 0014 / Phase R v1 — Scene 2 routing gate-keeper surface.
//
// Rendered for stream messages with kind='gated-proposal-pending'. The
// gate-keeper approves or denies; on approve the backend creates a
// DecisionRow with gated_via_proposal_id lineage + runs apply_actions;
// on deny no DecisionRow is created (denied proposals never crystallize).
// The card fetches the full GatedProposal on mount so it can show the
// proposer + decision-class chip; message.body already carries the
// proposal_body as fallback.

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  approveGatedProposal,
  denyGatedProposal,
  getGatedProposal,
  type GatedProposal,
  type PersonalMessage,
} from "@/lib/api";

import { relativeTime,
  formatMessageTime, type StreamMember } from "./types";

type Props = {
  message: PersonalMessage;
  memberById?: Map<string, StreamMember>;
};

const CLASS_LABELS: Record<
  string,
  { en: string; zh: string }
> = {
  budget: { en: "Budget", zh: "预算" },
  legal: { en: "Legal", zh: "法务" },
  hire: { en: "Hire", zh: "招聘" },
  scope_cut: { en: "Scope", zh: "范围" },
};

export function GatedProposalPendingCard({ message, memberById }: Props) {
  const t = useTranslations("personal.gatedProposal");
  const [proposal, setProposal] = useState<GatedProposal | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actioning, setActioning] = useState<"approve" | "deny" | null>(null);
  const [resolutionNote, setResolutionNote] = useState("");
  const [localStatus, setLocalStatus] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Fetch the full proposal on mount so we can render proposer +
  // decision-class. The message body already carries proposal_body as
  // display fallback, so even if the fetch fails we render something
  // sensible.
  useEffect(() => {
    if (!message.linked_id) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await getGatedProposal(message.linked_id!);
        if (!cancelled) setProposal(res.proposal);
      } catch (e) {
        if (!cancelled) {
          const msg = e instanceof ApiError ? `error ${e.status}` : "load failed";
          setLoadError(msg);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [message.linked_id]);

  const proposerName = useMemo(() => {
    if (!proposal) return null;
    const m = memberById?.get(proposal.proposer_user_id);
    return m?.display_name ?? m?.username ?? proposal.proposer_user_id;
  }, [proposal, memberById]);

  const classChip = useMemo(() => {
    const cls = proposal?.decision_class;
    if (!cls) return null;
    const label = CLASS_LABELS[cls]?.en ?? cls;
    return (
      <span
        data-testid="decision-class-chip"
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
          marginLeft: 4,
        }}
      >
        {label}
      </span>
    );
  }, [proposal]);

  async function handleApprove() {
    if (actioning) return;
    setActioning("approve");
    setActionError(null);
    try {
      await approveGatedProposal(
        message.linked_id!,
        resolutionNote.trim() || undefined,
      );
      setLocalStatus("approved");
    } catch (e) {
      setActionError(extractError(e, t("awaiting")));
    } finally {
      setActioning(null);
    }
  }

  async function handleDeny() {
    if (actioning) return;
    setActioning("deny");
    setActionError(null);
    try {
      await denyGatedProposal(
        message.linked_id!,
        resolutionNote.trim() || undefined,
      );
      setLocalStatus("denied");
    } catch (e) {
      setActionError(extractError(e, t("awaiting")));
    } finally {
      setActioning(null);
    }
  }

  const resolvedStatus = localStatus ?? proposal?.status;
  const isResolved =
    resolvedStatus === "approved" || resolvedStatus === "denied";

  return (
    <div
      data-testid="personal-gated-proposal-pending"
      data-proposal-id={message.linked_id}
      data-status={resolvedStatus ?? "pending"}
      style={{
        padding: "12px 14px",
        marginRight: "20%",
        background: "var(--wg-surface-sunk, var(--wg-surface))",
        border: "1px solid var(--wg-amber)",
        borderLeft: "3px solid var(--wg-amber)",
        borderRadius: "var(--wg-radius)",
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
          color: "var(--wg-amber)",
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          fontWeight: 600,
          marginBottom: 8,
          gap: 8,
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span aria-hidden="true">⚖</span>
          <span>
            {proposerName
              ? t("proposerPrefix", { name: proposerName })
              : t("awaiting")}
          </span>
          {classChip}
        </span>
        <span
          title={new Date(message.created_at).toLocaleString()}
          style={{
            color: "var(--wg-ink-soft)",
            textTransform: "none",
            fontWeight: 400,
          }}
        >
          {formatMessageTime(message.created_at)}
        </span>
      </div>

      {/*
        v0.5 — when the proposer's raw utterance is captured, render it
        first so the gate-keeper approves what the human actually said,
        not the agent's paraphrase. Suppressed when missing (pre-0015
        rows / programmatic callers) or when it's identical to
        message.body (no duplicative noise).
      */}
      {proposal?.decision_text &&
      proposal.decision_text.trim() !== message.body.trim() ? (
        <div
          data-testid="personal-gated-decision-text"
          style={{
            marginBottom: 10,
            padding: "8px 10px",
            background: "var(--wg-surface-raised, var(--wg-surface))",
            borderLeft: "2px solid var(--wg-ink-faint)",
            borderRadius: "var(--wg-radius-sm, 4px)",
          }}
        >
          <div
            style={{
              fontFamily: "var(--wg-font-mono)",
              fontSize: 10,
              color: "var(--wg-ink-faint)",
              letterSpacing: "0.04em",
              textTransform: "uppercase",
              fontWeight: 600,
              marginBottom: 4,
            }}
          >
            {t("rawUtteranceLabel")}
          </div>
          <div
            style={{
              color: "var(--wg-ink)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              lineHeight: 1.5,
              fontSize: 13,
            }}
          >
            {proposal.decision_text}
          </div>
        </div>
      ) : null}

      <div
        style={{
          color: "var(--wg-ink)",
          marginBottom: 12,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          lineHeight: 1.5,
        }}
      >
        {message.body}
      </div>

      {loadError ? (
        <div
          role="alert"
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-faint)",
            marginBottom: 8,
          }}
        >
          {loadError}
        </div>
      ) : null}

      {isResolved ? (
        <div
          data-testid="personal-gated-proposal-resolved-inline"
          style={{
            fontFamily: "var(--wg-font-mono)",
            fontSize: 12,
            color:
              resolvedStatus === "approved"
                ? "var(--wg-ok)"
                : "var(--wg-ink-soft)",
            fontWeight: 600,
          }}
        >
          {resolvedStatus === "approved" ? t("approved") : t("denied")}
        </div>
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <textarea
            value={resolutionNote}
            onChange={(e) => setResolutionNote(e.target.value)}
            placeholder={t("resolutionNotePlaceholder")}
            data-testid="personal-gated-note"
            rows={2}
            maxLength={2000}
            style={{
              width: "100%",
              padding: "6px 8px",
              background: "var(--wg-surface-raised, var(--wg-surface))",
              color: "var(--wg-ink)",
              border: "1px solid var(--wg-line)",
              borderRadius: "var(--wg-radius-sm, 4px)",
              fontSize: 12,
              fontFamily: "var(--wg-font-body, inherit)",
              resize: "vertical",
              boxSizing: "border-box",
            }}
          />
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              disabled={actioning !== null}
              onClick={() => void handleApprove()}
              data-testid="personal-gated-approve-btn"
              style={{
                padding: "6px 14px",
                background: "var(--wg-ok)",
                color: "#fff",
                border: "none",
                borderRadius: "var(--wg-radius)",
                fontSize: 12,
                fontWeight: 600,
                cursor: actioning ? "progress" : "pointer",
                opacity: actioning && actioning !== "approve" ? 0.5 : 1,
              }}
            >
              {actioning === "approve" ? t("approving") : t("approve")}
            </button>
            <button
              type="button"
              disabled={actioning !== null}
              onClick={() => void handleDeny()}
              data-testid="personal-gated-deny-btn"
              style={{
                padding: "6px 14px",
                background: "transparent",
                color: "var(--wg-ink)",
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius)",
                fontSize: 12,
                fontWeight: 600,
                cursor: actioning ? "progress" : "pointer",
                opacity: actioning && actioning !== "deny" ? 0.5 : 1,
              }}
            >
              {actioning === "deny" ? t("denying") : t("deny")}
            </button>
          </div>
        </div>
      )}

      {actionError ? (
        <div
          role="alert"
          style={{
            marginTop: 6,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
          }}
        >
          {actionError}
        </div>
      ) : null}
    </div>
  );
}

function extractError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    const body = e.body as { message?: unknown; detail?: unknown } | undefined;
    return (
      (body && typeof body.message === "string" && body.message) ||
      (body && typeof body.detail === "string" && body.detail) ||
      `error ${e.status}`
    );
  }
  return fallback;
}
