"use client";

// DecisionVoteControls — vote affordance + tally view for one decision.
//
// Mounted inside DecisionCard when the viewer is allowed to vote on
// this decision (caller decides, typically: scope_stream_id matches
// the current room AND viewer is a room member). Renders:
//
//   * Tally line — "👍 2 · 👎 0 · ⊘ 1 (3/4 cast · open)"
//   * Three action buttons (Yes / No / Abstain) with the viewer's
//     current vote highlighted.
//   * Inline status pill — open / passed / failed / tied.
//
// Tally seeds from the parent's `tally` prop (enriched by the backend
// at the timeline GET / WS upsert). `myVote` is GET'd once on mount
// because the timeline payload doesn't carry per-viewer state. After
// the first cast, the response carries my_vote so we don't poll
// again until the WS reducer updates the tally.

import { useEffect, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  castDecisionVote,
  getDecisionTally,
  type DecisionTally,
  type DecisionVoteCastResponse,
  type DecisionVoteRecord,
} from "@/lib/api";

type Verdict = DecisionVoteRecord["verdict"];

interface Props {
  decisionId: string;
  tally?: DecisionTally;
  // Optional callback fired AFTER a successful cast — lets the parent
  // (or workbench projection) update local state. The reducer in
  // useRoomTimeline reconciles via the WS frame the backend emits, so
  // the parent rarely needs to do anything beyond logging.
  onCast?: (response: DecisionVoteCastResponse) => void;
}

const containerStyle: CSSProperties = {
  marginTop: 8,
  paddingTop: 8,
  borderTop: "1px dashed var(--wg-line)",
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

const tallyRowStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  fontSize: 12,
  color: "var(--wg-ink-soft)",
  fontFamily: "var(--wg-font-mono)",
};

const buttonRowStyle: CSSProperties = {
  display: "flex",
  gap: 6,
  alignItems: "center",
};

function statusStyle(status: DecisionTally["status"]): CSSProperties {
  const color =
    status === "passed"
      ? "var(--wg-accent, #2451b5)"
      : status === "failed"
        ? "var(--wg-warn, #b94a48)"
        : status === "tied"
          ? "var(--wg-ink-soft)"
          : "var(--wg-ink-soft)";
  const background =
    status === "passed"
      ? "var(--wg-accent-soft, #eef3ff)"
      : status === "failed"
        ? "#fbe9e9"
        : "transparent";
  return {
    padding: "1px 6px",
    fontSize: 10,
    borderRadius: 8,
    border: `1px solid ${color}`,
    color,
    background,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
    fontWeight: 600,
  };
}

const baseBtnStyle = (active: boolean, disabled: boolean): CSSProperties => ({
  padding: "4px 12px",
  fontSize: 12,
  border: "1px solid",
  borderColor: active ? "var(--wg-accent, #2451b5)" : "var(--wg-line)",
  borderRadius: 3,
  background: active ? "var(--wg-accent, #2451b5)" : "#fff",
  color: active ? "#fff" : "var(--wg-ink-soft)",
  cursor: disabled ? "not-allowed" : "pointer",
  fontWeight: active ? 600 : 400,
  opacity: disabled ? 0.6 : 1,
});

export function DecisionVoteControls({ decisionId, tally, onCast }: Props) {
  const t = useTranslations("stream.decision");
  const [myVote, setMyVote] = useState<Verdict | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingVerdict, setPendingVerdict] = useState<Verdict | null>(
    null,
  );
  const [localTally, setLocalTally] = useState<DecisionTally | undefined>(
    tally,
  );

  // Lazy-fetch the viewer's vote (and refresh the tally) on mount.
  // Cheap — one GET per visible decision card, only the first time.
  useEffect(() => {
    let cancelled = false;
    void getDecisionTally(decisionId)
      .then((res) => {
        if (cancelled) return;
        if (res.my_vote) setMyVote(res.my_vote.verdict);
        setLocalTally(res.tally);
      })
      .catch(() => {
        // Silent — we already have the parent's tally as fallback;
        // worst case the user sees no "your vote" highlight until
        // they click.
      });
    return () => {
      cancelled = true;
    };
  }, [decisionId]);

  // Reconcile when the parent's tally prop changes (WS reducer
  // applied a timeline.update.patch.tally).
  useEffect(() => {
    if (tally) setLocalTally(tally);
  }, [tally]);

  async function cast(verdict: Verdict) {
    if (pendingVerdict !== null) return;
    setPendingVerdict(verdict);
    setError(null);
    try {
      const res = await castDecisionVote(decisionId, { verdict });
      setMyVote(res.my_vote.verdict);
      setLocalTally(res.tally);
      onCast?.(res);
    } catch (e) {
      if (e instanceof ApiError) {
        const detail =
          typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail?: unknown }).detail ?? e.message)
            : `error ${e.status}`;
        setError(detail);
      } else if (e instanceof Error) {
        setError(e.message);
      } else {
        setError(t("voteError"));
      }
    } finally {
      setPendingVerdict(null);
    }
  }

  const showTally = !!localTally;
  const status = localTally?.status ?? "open";

  return (
    <div style={containerStyle} data-testid="decision-vote-controls">
      {showTally && localTally && (
        <div style={tallyRowStyle}>
          <span title={t("voteApproveLabel")}>
            👍 <strong>{localTally.approve}</strong>
          </span>
          <span title={t("voteDenyLabel")}>
            👎 <strong>{localTally.deny}</strong>
          </span>
          <span title={t("voteAbstainLabel")}>
            ⊘ <strong>{localTally.abstain}</strong>
          </span>
          <span style={{ marginLeft: 4 }}>
            {t("voteTallyMeta", {
              cast: localTally.cast,
              quorum: localTally.quorum,
            })}
          </span>
          <span style={statusStyle(status)}>{t(`voteStatus.${status}`)}</span>
        </div>
      )}
      <div style={buttonRowStyle} data-testid="decision-vote-buttons">
        {(["approve", "deny", "abstain"] as Verdict[]).map((v) => (
          <button
            key={v}
            type="button"
            disabled={pendingVerdict !== null}
            onClick={() => void cast(v)}
            style={baseBtnStyle(myVote === v, pendingVerdict !== null)}
            aria-pressed={myVote === v}
            data-vote-verdict={v}
          >
            {pendingVerdict === v ? t("voting") : t(`voteVerdict.${v}`)}
          </button>
        ))}
      </div>
      {error && (
        <p
          style={{
            margin: 0,
            fontSize: 11,
            color: "var(--wg-warn, #b94a48)",
          }}
        >
          {error}
        </p>
      )}
    </div>
  );
}
