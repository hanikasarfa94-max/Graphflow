"use client";

// FlowPacketRow — extracted from components/rooms/FlowsPanelBody.tsx
// during Phase E (Architecture Organization Pass v1). The original
// `FlowRow` helper rendered one packet inside the bucket section;
// hoisting it out lets the bucket loop stay legible while keeping the
// row component independently testable.
//
// Behaviour is unchanged: same DOM shape, same data-testids, same
// chip layout, same delegation to <FlowRowActions> and <EvidenceBlock>.
// Phase E's mandate is decomposition, not redesign — so a user looking
// at this row before and after the move sees pixel-identical output.

import type { CSSProperties } from "react";
import { useTranslations } from "next-intl";

import {
  RECIPE_ICON,
  type FlowPacket,
  type ParticipantInfo,
} from "@/lib/flows";
import { formatIso } from "@/lib/time";

import { EvidenceBlock } from "@/components/rooms/EvidenceBlock";
import { FlowRowActions } from "@/components/rooms/FlowRowActions";

export interface FlowPacketRowProps {
  packet: FlowPacket;
  // Participant sidecar map for evidence rendering — passed through
  // to EvidenceBlock without resolution work here.
  participants: Record<string, ParticipantInfo>;
  // Bubbled up from FlowRowActions so the parent panel can refresh
  // its three buckets after a successful mutation (C.1.c).
  onActed: () => void;
  // Optional viewer id — used by EvidenceBlock to render "you" in
  // place of the viewer's display name.
  viewerUserId?: string;
}

export function FlowPacketRow({
  packet,
  participants,
  onActed,
  viewerUserId,
}: FlowPacketRowProps) {
  const t = useTranslations("flows");
  // Spec §6: drawer reads `current_target_user_ids` for who is
  // currently blocking, not `target_user_ids`.
  const currentBlocking = packet.current_target_user_ids.length;
  const recipeLabel = t(`recipes.${packet.recipe_id}`);
  const stageLabel = stageDisplay(packet.stage, t);
  const updated = packet.updated_at ?? packet.created_at;
  return (
    <div
      data-testid="flow-row"
      data-recipe={packet.recipe_id}
      style={rowStyle}
    >
      <div style={rowGridStyle}>
        <span aria-hidden style={iconStyle}>
          {RECIPE_ICON[packet.recipe_id] ?? "•"}
        </span>
        <div style={rowTextColStyle}>
          <strong style={rowTitleStyle} title={packet.title}>
            {packet.title}
          </strong>
          <span style={rowMetaRowStyle}>
            <span style={metaChipStyle}>{recipeLabel}</span>
            <span style={metaChipStyle}>{stageLabel}</span>
            {currentBlocking > 0 ? (
              <span style={metaChipStyle}>
                {currentBlocking === 1
                  ? "1 actor"
                  : `${currentBlocking} actors`}
              </span>
            ) : null}
            <span style={faintMetaStyle}>
              {t("metaUpdated", { time: formatIso(updated) })}
            </span>
          </span>
        </div>
        {/* C.1.c — action surface. Reads packet.next_actions and renders
            Open + Accept + More-menu compactly. Form for counter_back /
            custom_followup expands inline. Read-only Open and unsupported
            recipes both fall through to the FlowRowActions empty state. */}
        <FlowRowActions packet={packet} onActed={onActed} />
      </div>
      {/* Slice D — compact evidence: Asked / Replied / Closed. Toggled
          per-row so default is calm; participants come from the panel
          state via the bucket's sidecar map. */}
      <EvidenceBlock
        packet={packet}
        participants={participants}
        viewerUserId={viewerUserId}
      />
    </div>
  );
}

function stageDisplay(
  stage: string,
  t: ReturnType<typeof useTranslations>,
): string {
  // Stage values are open-vocabulary on the BE; fall through to the
  // raw value when we don't have a translation. Spec §4 — stage is a
  // display label, not source of truth, so this is intentional.
  const known = new Set([
    "awaiting_target",
    "awaiting_membrane",
    "awaiting_owner",
    "completed",
    "published",
  ]);
  if (known.has(stage)) return t(`stage.${stage}`);
  return stage;
}

// ---- styles -------------------------------------------------------------
// Named CSSProperties objects (not anonymous inline literals) so the
// design-system static guard (apps/web/src/lib/design-system.test.ts)
// treats them as reusable tokens. Every colour references a `--wg-*`
// variable; no hex literals live in this file.

const rowStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  padding: "8px 10px",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  background: "var(--wg-surface)",
};

const rowGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "auto 1fr auto",
  alignItems: "start",
  gap: 8,
};

const iconStyle: CSSProperties = {
  fontSize: 16,
  lineHeight: "20px",
  marginTop: 2,
};

const rowTextColStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
  minWidth: 0,
};

const rowTitleStyle: CSSProperties = {
  fontSize: 13,
  color: "var(--wg-ink)",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const rowMetaRowStyle: CSSProperties = {
  fontSize: 11,
  color: "var(--wg-ink-soft)",
  display: "flex",
  gap: 6,
  flexWrap: "wrap",
};

const faintMetaStyle: CSSProperties = {
  color: "var(--wg-ink-faint)",
};

const metaChipStyle: CSSProperties = {
  padding: "1px 6px",
  fontSize: 10,
  fontFamily: "var(--wg-font-mono)",
  background: "var(--wg-surface)",
  border: "1px solid var(--wg-line)",
  borderRadius: 10,
  color: "var(--wg-ink-soft)",
};
