"use client";

// Scrimmage cards — Phase 2.B surface.
//
// Three cards render the lifecycle of an agent-vs-agent debate:
//   * ScrimmageRunningCard — while the POST is in flight.
//   * DecisionProposalCard — outcome=converged_proposal: "Approve as
//     decision" primary action (navigates to the pending DecisionRow).
//   * DebateSummaryCard — outcome=unresolved_crux: both closing stances
//     side-by-side with citation chips; "Ask [target] directly" falls
//     back to the classic routing flow.
//
// Cards are rendered locally inside RouteProposalCard — they do NOT hit
// the personal stream WebSocket (no message row is emitted for scrimmage
// runs; the transcript lives on ScrimmageRow and is fetched via GET).

import Link from "next/link";
import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";

import type { ScrimmageResult, ScrimmageTurn } from "@/lib/api";

import { CitedClaimList } from "./CitedClaimList";

const STANCE_LABEL_KEY: Record<ScrimmageTurn["stance"], string> = {
  agree_with_other: "stance.agree",
  propose_compromise: "stance.compromise",
  hold_position: "stance.hold",
};

const cardShell: CSSProperties = {
  marginTop: 8,
  padding: "10px 14px",
  background: "var(--wg-surface)",
  border: "1px solid var(--wg-line)",
  borderLeft: "3px solid var(--wg-accent)",
  borderRadius: "0 var(--wg-radius) var(--wg-radius) 0",
  fontSize: 13,
};

const headerRow: CSSProperties = {
  fontFamily: "var(--wg-font-mono)",
  fontSize: 11,
  color: "var(--wg-accent)",
  letterSpacing: "0.04em",
  textTransform: "uppercase",
  fontWeight: 600,
  marginBottom: 8,
};

const primaryBtn: CSSProperties = {
  padding: "6px 12px",
  background: "var(--wg-accent)",
  color: "#fff",
  border: "none",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  fontWeight: 600,
  cursor: "pointer",
  textDecoration: "none",
  display: "inline-block",
};

const secondaryBtn: CSSProperties = {
  padding: "6px 10px",
  background: "var(--wg-surface)",
  color: "var(--wg-ink)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  cursor: "pointer",
};

// ---- running card -------------------------------------------------------

export function ScrimmageRunningCard({
  sourceName,
  targetName,
}: {
  sourceName: string;
  targetName: string;
}) {
  const t = useTranslations("scrimmage");
  return (
    <div
      data-testid="scrimmage-running"
      style={{
        ...cardShell,
        borderLeftColor: "var(--wg-ink-soft)",
      }}
    >
      <div style={{ ...headerRow, color: "var(--wg-ink-soft)" }}>
        {t("running.header")}
      </div>
      <div
        style={{
          display: "flex",
          gap: 10,
          alignItems: "center",
          color: "var(--wg-ink)",
        }}
      >
        <Spinner />
        <span>
          {t("running.body", { source: sourceName, target: targetName })}
        </span>
      </div>
    </div>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden
      style={{
        width: 12,
        height: 12,
        border: "2px solid var(--wg-line)",
        borderTopColor: "var(--wg-accent)",
        borderRadius: "50%",
        animation: "wgSpin 0.8s linear infinite",
        display: "inline-block",
      }}
    />
  );
}

// ---- converged result ---------------------------------------------------

export function DecisionProposalCard({
  projectId,
  result,
  sourceName,
  targetName,
  onReject,
}: {
  projectId: string;
  result: ScrimmageResult;
  sourceName: string;
  targetName: string;
  onReject: () => void;
}) {
  const t = useTranslations("scrimmage");
  const proposal = result.proposal;
  if (!proposal) return null;
  return (
    <div data-testid="scrimmage-proposal" style={cardShell}>
      <div style={headerRow}>{t("converged.header")}</div>
      <div
        style={{
          fontSize: 13,
          color: "var(--wg-ink)",
          marginBottom: 10,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {proposal.proposal_text || "(no proposal text)"}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 10,
          marginBottom: 10,
        }}
      >
        <StanceColumn
          role={sourceName}
          stanceKey={proposal.source_stance}
          closing={proposal.source_closing}
          turn={findLast(result.transcript, "source")}
          projectId={projectId}
        />
        <StanceColumn
          role={targetName}
          stanceKey={proposal.target_stance}
          closing={proposal.target_closing}
          turn={findLast(result.transcript, "target")}
          projectId={projectId}
        />
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {proposal.decision_id ? (
          <Link
            href={`/projects/${projectId}/detail/decisions`}
            style={primaryBtn}
            data-testid="scrimmage-approve-btn"
            data-decision-id={proposal.decision_id}
          >
            {t("converged.approve")}
          </Link>
        ) : null}
        <button
          type="button"
          onClick={onReject}
          style={secondaryBtn}
          data-testid="scrimmage-reject-btn"
        >
          {t("converged.reject", { name: targetName })}
        </button>
      </div>
    </div>
  );
}

// ---- unresolved summary -------------------------------------------------

export function DebateSummaryCard({
  projectId,
  result,
  sourceName,
  targetName,
  onAskDirectly,
}: {
  projectId: string;
  result: ScrimmageResult;
  sourceName: string;
  targetName: string;
  onAskDirectly: () => void;
}) {
  const t = useTranslations("scrimmage");
  const sourceTurn = findLast(result.transcript, "source");
  const targetTurn = findLast(result.transcript, "target");
  return (
    <div data-testid="scrimmage-summary" style={cardShell}>
      <div style={headerRow}>{t("unresolved.header")}</div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 10,
          marginBottom: 10,
        }}
      >
        <StanceColumn
          role={sourceName}
          stanceKey={sourceTurn?.stance ?? null}
          closing={sourceTurn?.text ?? null}
          turn={sourceTurn}
          projectId={projectId}
        />
        <StanceColumn
          role={targetName}
          stanceKey={targetTurn?.stance ?? null}
          closing={targetTurn?.text ?? null}
          turn={targetTurn}
          projectId={projectId}
        />
      </div>

      <button
        type="button"
        onClick={onAskDirectly}
        style={primaryBtn}
        data-testid="scrimmage-ask-directly-btn"
      >
        {t("unresolved.ask", { name: targetName })}
      </button>
    </div>
  );
}

// ---- shared stance column ----------------------------------------------

function StanceColumn({
  role,
  stanceKey,
  closing,
  turn,
  projectId,
}: {
  role: string;
  stanceKey: ScrimmageTurn["stance"] | null;
  closing: string | null;
  turn: ScrimmageTurn | undefined;
  projectId: string;
}) {
  const t = useTranslations("scrimmage");
  return (
    <div
      style={{
        padding: "8px 10px",
        background: "var(--wg-surface-sunk, #faf8f4)",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        minWidth: 0,
      }}
      data-testid="scrimmage-stance-column"
    >
      <div
        style={{
          fontFamily: "var(--wg-font-mono)",
          fontSize: 10,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          color: "var(--wg-ink-faint)",
          marginBottom: 4,
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>{role}</span>
        <span>
          {stanceKey ? t(STANCE_LABEL_KEY[stanceKey]) : "—"}
        </span>
      </div>
      <div
        style={{
          fontSize: 12,
          color: "var(--wg-ink)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          marginBottom: 4,
        }}
      >
        {closing || "(no text)"}
      </div>
      {turn && turn.citations && turn.citations.length > 0 ? (
        <CitedClaimList projectId={projectId} claims={turn.citations} />
      ) : null}
    </div>
  );
}

function findLast(
  turns: ScrimmageTurn[],
  speaker: ScrimmageTurn["speaker"],
): ScrimmageTurn | undefined {
  for (let i = turns.length - 1; i >= 0; i--) {
    if (turns[i].speaker === speaker) return turns[i];
  }
  return undefined;
}
