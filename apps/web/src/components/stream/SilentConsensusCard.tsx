"use client";

// SilentConsensusCard — Phase 1.A.
//
// Renders the scanner's "N members are silently agreeing on X" proposal
// in the user's personal stream. Visual treatment mirrors the routing-
// proposal card: lightened (sunk) surface, no hard accent border,
// member names rendered as inline chips, 20% right gutter.
//
// The backend emits a `silent-consensus-proposal` kind message whose
// body JSON payload embeds the SilentConsensusProposal shape. The card
// parses that payload on mount and renders ratify / reject buttons
// when the proposal is still `status='pending'`.

import { useMemo, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { Card } from "@/components/ui";
import {
  ApiError,
  ratifySilentConsensus,
  rejectSilentConsensus,
  type PersonalMessage,
  type SilentConsensusProposal,
} from "@/lib/api";

import { relativeTime } from "./types";

type Props = {
  message: PersonalMessage;
  projectId: string;
  onResolved?: (id: string, status: "ratified" | "rejected") => void;
};

function parseProposal(body: string): SilentConsensusProposal | null {
  try {
    const parsed = JSON.parse(body);
    if (parsed && typeof parsed === "object" && typeof parsed.id === "string") {
      return parsed as SilentConsensusProposal;
    }
  } catch {
    return null;
  }
  return null;
}

const chipStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "2px 8px",
  borderRadius: 10,
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  background: "var(--wg-surface-raised)",
  color: "var(--wg-ink)",
  border: "1px solid var(--wg-line)",
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
};

const secondaryBtn: CSSProperties = {
  padding: "6px 12px",
  background: "var(--wg-surface)",
  color: "var(--wg-ink)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontSize: 12,
  cursor: "pointer",
};

export function SilentConsensusCard({ message, projectId, onResolved }: Props) {
  const t = useTranslations("silentConsensus");
  const proposal = useMemo(() => parseProposal(message.body), [message.body]);

  const [status, setStatus] = useState<
    "pending" | "ratified" | "rejected"
  >(proposal?.status ?? "pending");
  const [showActions, setShowActions] = useState(false);
  const [busy, setBusy] = useState<"ratify" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (proposal == null) {
    // Forward-compat: if we can't parse the payload, fall through to a
    // plain text rendering so unknown versions don't crash the stream.
    return (
      <div
        data-testid="silent-consensus-card-unparsed"
        style={{
          padding: "8px 12px",
          background: "var(--wg-surface-sunk, var(--wg-surface-raised))",
          border: "1px solid var(--wg-line-soft, var(--wg-line))",
          borderRadius: "var(--wg-radius)",
          fontSize: 13,
          color: "var(--wg-ink-soft)",
          marginRight: "20%",
        }}
      >
        {message.body}
      </div>
    );
  }

  async function onRatify() {
    if (busy) return;
    setBusy("ratify");
    setError(null);
    try {
      await ratifySilentConsensus(projectId, proposal!.id);
      setStatus("ratified");
      onResolved?.(proposal!.id, "ratified");
    } catch (e) {
      if (e instanceof ApiError) {
        setError(String(e.status));
      } else {
        setError("err");
      }
    } finally {
      setBusy(null);
    }
  }

  async function onReject() {
    if (busy) return;
    setBusy("reject");
    setError(null);
    try {
      await rejectSilentConsensus(projectId, proposal!.id);
      setStatus("rejected");
      onResolved?.(proposal!.id, "rejected");
    } catch (e) {
      if (e instanceof ApiError) {
        setError(String(e.status));
      } else {
        setError("err");
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <div
      data-testid="silent-consensus-card"
      data-sc-id={proposal.id}
      style={{ marginRight: "20%" }}
    >
      <Card variant="sunk" style={{ borderColor: "var(--wg-line-soft, var(--wg-line))" }}>
        <div
          style={{
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
            marginBottom: 6,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            gap: 8,
          }}
        >
          <span style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}>
            {t("header")}
          </span>
          <span title={new Date(message.created_at).toLocaleString()}>
            {relativeTime(message.created_at)}
          </span>
        </div>
        <div
          style={{
            fontSize: 13,
            color: "var(--wg-ink)",
            marginBottom: 8,
            lineHeight: 1.45,
          }}
        >
          {proposal.inferred_decision_summary}
        </div>
        <div
          style={{
            fontSize: 12,
            color: "var(--wg-ink-soft)",
            marginBottom: 10,
          }}
        >
          <span style={{ marginRight: 6 }}>{t("bodyPrefix")}</span>
          <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
            {proposal.members.map((m) => (
              <span key={m.user_id} style={chipStyle}>
                {m.display_name}
              </span>
            ))}
          </span>
        </div>

        <button
          type="button"
          onClick={() => setShowActions((v) => !v)}
          style={{
            padding: 0,
            background: "transparent",
            border: "none",
            color: "var(--wg-ink-soft)",
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            cursor: "pointer",
            textDecoration: "underline",
            marginBottom: 8,
          }}
        >
          {showActions ? t("hideActions") : t("showActions")}
        </button>

        {showActions ? (
          <ul
            style={{
              margin: "0 0 10px",
              paddingLeft: 18,
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
            }}
          >
            {proposal.supporting_action_ids.map((a, idx) => (
              <li key={`${a.kind}-${a.id}-${idx}`}>
                {a.kind}:{a.id.slice(0, 8)}
              </li>
            ))}
          </ul>
        ) : null}

        {status === "pending" ? (
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button
              type="button"
              data-testid="silent-consensus-ratify"
              onClick={() => void onRatify()}
              disabled={busy !== null}
              style={primaryBtn}
            >
              {busy === "ratify" ? t("ratifying") : t("ratify")}
            </button>
            <button
              type="button"
              data-testid="silent-consensus-reject"
              onClick={() => void onReject()}
              disabled={busy !== null}
              style={secondaryBtn}
            >
              {busy === "reject" ? t("rejecting") : t("reject")}
            </button>
            {error ? (
              <span
                role="alert"
                style={{
                  fontSize: 11,
                  color: "var(--wg-accent)",
                  fontFamily: "var(--wg-font-mono)",
                }}
              >
                {t("errorGeneric")}
              </span>
            ) : null}
          </div>
        ) : (
          <div
            style={{
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color:
                status === "ratified"
                  ? "var(--wg-ok, #2f8f4f)"
                  : "var(--wg-ink-soft)",
            }}
          >
            {status === "ratified" ? t("ratified") : t("rejected")}
          </div>
        )}
      </Card>
    </div>
  );
}
