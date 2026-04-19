"use client";

// RouteProposalCard — Phase N.
//
// Renders the edge-agent's "route proposal" turn in the user's personal
// stream (north-star §"Sub-agent and routing architecture" → "Route
// proposal"). The body shows the agent's framing; 1–3 "Ask [name]"
// buttons fire the confirm endpoint which dispatches via the parent
// agent. A dismiss (×) control hides the card locally (backend decline
// endpoint TBD — see report).
//
// Targets are either pre-parsed on the message (`route_targets`) or
// extracted client-side from a `<route-proposal>{targets:[…]}</…>`
// marker in the body (see `parseRouteProposalTargets` in lib/api).

import { useMemo, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import {
  ApiError,
  confirmRouteProposal,
  parseRouteProposalFromBody,
  stripRouteProposalMarker,
  type PersonalMessage,
  type PersonalRouteTarget,
} from "@/lib/api";

import { relativeTime } from "./types";

type Props = {
  message: PersonalMessage;
  // Parent may want to refresh its timeline after a dispatch so the new
  // "routed-reply" card can land. We fire-and-forget here; parent is
  // informed via the optional callback.
  onConfirmed?: (signalId: string) => void;
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

const dismissBtn: CSSProperties = {
  marginLeft: "auto",
  padding: "2px 8px",
  background: "transparent",
  color: "var(--wg-ink-soft)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius-sm, 4px)",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  cursor: "pointer",
};

export function RouteProposalCard({ message, onConfirmed }: Props) {
  const t = useTranslations("personal");

  // Prefer pre-parsed backend metadata; fall back to embedded marker if
  // the payload wasn't shaped (e.g. older API build).
  const proposal = useMemo(() => {
    if (message.route_proposal) return message.route_proposal;
    return parseRouteProposalFromBody(message.body);
  }, [message]);

  const targets = useMemo<PersonalRouteTarget[]>(
    () => proposal?.targets ?? [],
    [proposal],
  );

  // If the backend stripped the marker for us, use body as-is; otherwise
  // strip defensively. Prefer proposal.framing when present because that
  // is the canonical framing text the agent composed.
  const displayBody = useMemo(() => {
    if (proposal?.framing) return proposal.framing;
    return stripRouteProposalMarker(message.body);
  }, [message.body, proposal]);

  // Local state — backend decline endpoint not yet wired.
  const [dismissed, setDismissed] = useState(false);
  const [confirmedName, setConfirmedName] = useState<string | null>(null);
  const [pendingTargetId, setPendingTargetId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (dismissed) {
    return (
      <div
        data-testid="personal-route-proposal-dismissed"
        style={{
          marginBottom: 8,
          marginLeft: 42,
          padding: "4px 10px",
          fontSize: 11,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-ink-soft)",
        }}
      >
        {t("routeProposal.dismissed")}
      </div>
    );
  }

  async function handleAsk(target: PersonalRouteTarget) {
    if (pendingTargetId) return;
    setPendingTargetId(target.user_id);
    setError(null);
    try {
      const result = await confirmRouteProposal(message.id, target.user_id);
      setConfirmedName(target.display_name);
      onConfirmed?.(result.signal_id);
    } catch (e) {
      setPendingTargetId(null);
      if (e instanceof ApiError) {
        const detail =
          typeof e.body === "object" && e.body && "detail" in e.body
            ? String((e.body as { detail?: unknown }).detail ?? "")
            : `error ${e.status}`;
        setError(detail || `error ${e.status}`);
      } else {
        setError("ask failed");
      }
    }
  }

  return (
    <div
      data-testid="personal-route-proposal"
      data-message-id={message.id}
      style={{
        marginBottom: 12,
        marginLeft: 42,
        padding: "10px 14px",
        background: "var(--wg-accent-soft, #fdf4ec)",
        border: "1px solid var(--wg-accent-ring, var(--wg-accent))",
        borderLeft: "3px solid var(--wg-accent)",
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
          color: "var(--wg-accent)",
          letterSpacing: "0.04em",
          textTransform: "uppercase",
          fontWeight: 600,
          marginBottom: 6,
        }}
      >
        <span>{t("routeProposal.header")}</span>
        <span
          title={new Date(message.created_at).toLocaleString()}
          style={{ color: "var(--wg-ink-soft)", textTransform: "none", fontWeight: 400 }}
        >
          {relativeTime(message.created_at)}
        </span>
      </div>

      {displayBody && (
        <div
          style={{
            color: "var(--wg-ink)",
            marginBottom: 10,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {displayBody}
        </div>
      )}

      {confirmedName ? (
        <div
          data-testid="personal-route-proposal-confirmed"
          style={{
            fontFamily: "var(--wg-font-mono)",
            fontSize: 12,
            color: "var(--wg-ok, #2f8f4f)",
            fontWeight: 600,
          }}
        >
          {t("routeProposal.confirmed", { name: confirmedName })}
        </div>
      ) : (
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            alignItems: "center",
          }}
        >
          {targets.length === 0 && (
            <span
              style={{
                fontSize: 12,
                color: "var(--wg-ink-soft)",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {t("routeProposal.noTargets")}
            </span>
          )}
          {targets.map((tg) => {
            const busy = pendingTargetId === tg.user_id;
            return (
              <button
                key={tg.user_id}
                type="button"
                disabled={pendingTargetId !== null}
                onClick={() => void handleAsk(tg)}
                data-testid="personal-route-ask-btn"
                data-target-user-id={tg.user_id}
                style={{
                  ...primaryBtn,
                  opacity: pendingTargetId && !busy ? 0.5 : 1,
                  cursor: pendingTargetId ? "progress" : "pointer",
                }}
                title={tg.rationale}
              >
                {busy
                  ? t("routeProposal.asking", { name: tg.display_name })
                  : t("routeProposal.ask", { name: tg.display_name })}
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => setDismissed(true)}
            aria-label={t("routeProposal.dismiss")}
            title={t("routeProposal.dismiss")}
            data-testid="personal-route-dismiss-btn"
            style={dismissBtn}
          >
            ×
          </button>
        </div>
      )}

      {error && (
        <div
          role="alert"
          style={{
            marginTop: 6,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}
