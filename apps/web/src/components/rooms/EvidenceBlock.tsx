"use client";

// EvidenceBlock — Slice D compact evidence rendering for a Flow Packet.
//
// Goal (per user direction): one glance of confidence. Three lines max:
//   • Asked: <source> at <time>
//   • Replied: <target> at <time> (option / custom-text indicator)
//   • Closed: <last source action> at <time>
//
// Reads ONLY the projection's `evidence.human_gates` + the packet's
// metadata (created_at / source_user_id). Does not query users itself
// — name resolution comes from the `participants` sidecar passed in
// as a prop. Slice E will widen to `timeline` rendering for a richer
// detail surface, but this slice intentionally stays tight.

import { useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import type { FlowPacket, ParticipantInfo } from "@/lib/flows";
import { formatIso } from "@/lib/time";

interface Props {
  packet: FlowPacket;
  participants: Record<string, ParticipantInfo>;
  // Viewer's user id — used to render "you" instead of the viewer's
  // own display name. Optional so the component is testable without
  // an auth context.
  viewerUserId?: string;
}

export function EvidenceBlock({ packet, participants, viewerUserId }: Props) {
  const t = useTranslations("flows.evidence");
  const [open, setOpen] = useState(false);

  const lines = derivedLines(packet, participants, viewerUserId, t);

  return (
    <div data-testid="evidence-block" style={{ marginTop: open ? 6 : 0 }}>
      <button
        type="button"
        data-testid="evidence-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={toggleStyle(open)}
      >
        <span aria-hidden style={{ fontSize: 11 }}>
          {open ? "▾" : "▸"}
        </span>
        <span>{open ? t("hide") : t("show")}</span>
        {!open && lines.length > 0 ? (
          <span
            style={{
              fontSize: 10,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-faint)",
            }}
          >
            {lines.length}
          </span>
        ) : null}
      </button>
      {open ? (
        <div
          data-testid="evidence-body"
          style={{
            marginTop: 6,
            padding: "8px 10px",
            background: "var(--wg-surface, #fafafa)",
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            fontSize: 11,
            lineHeight: 1.6,
            color: "var(--wg-ink)",
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}
        >
          {lines.length === 0 ? (
            <span
              style={{ color: "var(--wg-ink-soft)", fontStyle: "italic" }}
            >
              {t("noEvidence")}
            </span>
          ) : (
            lines.map((line, idx) => (
              <span
                key={idx}
                data-testid="evidence-line"
                style={{ fontFamily: "var(--wg-font-mono)", fontSize: 11 }}
              >
                {line}
              </span>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

// ---- derivation ---------------------------------------------------------
//
// Build the three-line summary from the packet's evidence.human_gates
// plus the synthetic "Asked" line derived from packet metadata. Order
// is canonical: Asked → Replied → terminal action.

type Translator = ReturnType<typeof useTranslations>;

function derivedLines(
  packet: FlowPacket,
  participants: Record<string, ParticipantInfo>,
  viewerUserId: string | undefined,
  t: Translator,
): string[] {
  const lines: string[] = [];
  // Asked: derived from packet metadata. Not in human_gates because
  // dispatching isn't a gate decision.
  if (packet.source_user_id) {
    lines.push(
      t("asked", {
        who: nameFor(packet.source_user_id, participants, viewerUserId, t),
        when: formatIso(packet.created_at),
      }),
    );
  }
  // Replied + closing actions: walk human_gates in chronological
  // order. Target's reply lands first (recorded with action 'accept'
  // for option pick or 'counter' for custom text); subsequent
  // entries are source-side.
  const gates = packet.evidence.human_gates ?? [];
  for (const g of gates) {
    const who = nameFor(g.user_id, participants, viewerUserId, t);
    const when = formatIso(g.at);
    const isTarget =
      packet.target_user_ids.includes(g.user_id) &&
      g.user_id !== packet.source_user_id;
    if (isTarget) {
      // Distinguish option-pick replies from free-text replies.
      const key = g.note ? "repliedCustom" : "repliedWithOption";
      lines.push(t(key, { who, when }));
      continue;
    }
    // Source-side gate.
    if (g.action === "accept") lines.push(t("accepted", { who, when }));
    else if (g.action === "counter") lines.push(t("countered", { who, when }));
    else if (g.action === "escalate_to_gate")
      lines.push(t("escalated", { who, when }));
    // Followed-up isn't in human_gates by design (continuation, not
    // gate). It surfaces here only when extracted from the timeline,
    // which Slice E will pull in. For now it's silently absent — the
    // evidence remains accurate for terminal actions.
  }
  return lines;
}

function nameFor(
  userId: string | null | undefined,
  participants: Record<string, ParticipantInfo>,
  viewerUserId: string | undefined,
  t: Translator,
): string {
  if (!userId) return t("unknown");
  if (userId === viewerUserId) return t("you");
  const info = participants[userId];
  if (info) return info.display_name || info.username;
  return t("unknown");
}

// ---- styles -------------------------------------------------------------

function toggleStyle(open: boolean): CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    padding: "2px 6px",
    fontSize: 10,
    fontFamily: "var(--wg-font-mono)",
    background: open ? "var(--wg-accent-soft, rgba(21,91,213,0.06))" : "#fff",
    border: "1px solid var(--wg-line)",
    borderRadius: 3,
    color: "var(--wg-ink-soft)",
    cursor: "pointer",
  };
}
