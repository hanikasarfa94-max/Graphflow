"use client";

// RouteSuggestion — slim Phase-1 disappearing-broker SEND surface.
//
// Replaces the deleted 1.3k-LOC RouteProposalCard. When the edge agent
// returns a *discovery* route_proposal (My-AI composer), this renders a
// minimal inline "Route to {name}?" affordance per target: Send routes
// the ask, Edit reveals the editable B-facing draft (the disclosure
// gate), Dismiss hides it locally. Gated proposals are intentionally
// ignored here (no scrimmage / gated / pre-answer UI). Send posts to the
// canonical POST /api/routing/proposals/{id}/confirm via
// confirmRouteProposal. Semantics per docs/routing-broker-reference.md.
//
// Style note: named CSSProperties consts + CSS variables only (no
// anonymous style={{}} literals, no hex) so the design guard stays green
// without an allowlist entry.

import { useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { Button, Text } from "@/components/ui";
import {
  ApiError,
  confirmRouteProposal,
  type PersonalRouteTarget,
} from "@/lib/api";

export interface RouteProposalView {
  routeProposalId: string;
  framing: string;
  targets: PersonalRouteTarget[];
}

// Which draft text gets sent for a target: the user's edit wins, else the
// agent's B-facing draft, else the proposal framing (A-voice fallback).
export function resolveDraft(
  edited: string | undefined,
  target: PersonalRouteTarget,
  framing: string,
): string {
  if (edited !== undefined && edited.trim()) return edited.trim();
  if (target.b_facing_draft && target.b_facing_draft.trim()) {
    return target.b_facing_draft.trim();
  }
  return framing.trim();
}

const wrap: CSSProperties = {
  marginTop: 8,
  padding: "10px 12px",
  background: "var(--wg-surface-sunk)",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
};
const targetRow: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 6,
  paddingTop: 8,
};
const rowHead: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  gap: 8,
  flexWrap: "wrap",
};
const actions: CSSProperties = { display: "flex", gap: 8, alignItems: "center" };
const draftBox: CSSProperties = {
  width: "100%",
  minHeight: 56,
  padding: 8,
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  fontSize: 13,
  fontFamily: "inherit",
  background: "var(--wg-surface)",
  color: "var(--wg-ink)",
  boxSizing: "border-box",
};

export function RouteSuggestion({ proposal }: { proposal: RouteProposalView }) {
  const t = useTranslations("routeSuggestion");
  const [dismissed, setDismissed] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<Record<string, boolean>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (dismissed || proposal.targets.length === 0) return null;

  if (sentTo) {
    return (
      <div style={wrap} data-testid="route-suggestion">
        <Text variant="caption" muted>
          {t("sent", { name: sentTo })}
        </Text>
      </div>
    );
  }

  async function send(target: PersonalRouteTarget) {
    setBusyId(target.user_id);
    setError(null);
    try {
      await confirmRouteProposal(
        proposal.routeProposalId,
        target.user_id,
        resolveDraft(drafts[target.user_id], target, proposal.framing),
      );
      setSentTo(target.display_name);
    } catch (e) {
      setError(e instanceof ApiError ? t("failed") : t("failed"));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div style={wrap} data-testid="route-suggestion">
      <Text variant="caption" muted>
        {t("prompt")}
      </Text>
      {proposal.targets.map((target) => {
        const isEditing = !!editing[target.user_id];
        const busy = busyId === target.user_id;
        return (
          <div key={target.user_id} style={targetRow}>
            <div style={rowHead}>
              <Text>{t("ask", { name: target.display_name })}</Text>
              {target.rationale ? (
                <Text variant="caption" muted>
                  {target.rationale}
                </Text>
              ) : null}
            </div>
            {isEditing ? (
              <textarea
                style={draftBox}
                value={resolveDraft(
                  drafts[target.user_id],
                  target,
                  proposal.framing,
                )}
                disabled={busy}
                placeholder={t("draftPlaceholder", { name: target.display_name })}
                onChange={(e) =>
                  setDrafts((d) => ({ ...d, [target.user_id]: e.target.value }))
                }
              />
            ) : null}
            <div style={actions}>
              <Button
                variant="primary"
                disabled={busy}
                onClick={() => send(target)}
              >
                {busy ? t("sending") : t("send")}
              </Button>
              <Button
                variant="link"
                onClick={() =>
                  setEditing((s) => ({
                    ...s,
                    [target.user_id]: !s[target.user_id],
                  }))
                }
              >
                {isEditing ? t("hideEdit") : t("edit")}
              </Button>
            </div>
          </div>
        );
      })}
      <div style={actions}>
        <Button variant="link" onClick={() => setDismissed(true)}>
          {t("dismiss")}
        </Button>
      </div>
      {error ? (
        <Text variant="caption" muted>
          {error}
        </Text>
      ) : null}
    </div>
  );
}
