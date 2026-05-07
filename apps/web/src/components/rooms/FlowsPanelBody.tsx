"use client";

// FlowsPanelBody — Slice B drawer body inside the workbench shell.
//
// Reads three buckets in parallel from /api/projects/{id}/flows and
// renders compact rows. The packet contract lives in lib/flows.ts; this
// component never touches the raw projection shape directly.
//
// Slice B is intentionally read-only. The only action exposed is
// "Open", and Open follows next_actions[0].href verbatim. No
// accept/counter/dismiss buttons; those land in Slice C alongside
// FlowActionService. The empty-state copy is intentionally specific
// to each bucket so an empty workbench reads as quietness, not as
// "this feature is broken."
//
// Phase E (Architecture Organization Pass v1) — the per-row renderer
// and the empty/error placeholder were extracted into
// `@/features/flows`. The fetch/state-machine + bucket-section header
// stay here; they're tied to the panel's lifecycle and don't have a
// clean lift target without a hook extraction (deferred).

import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import {
  BUCKETS,
  listFlows,
  type FlowBucket,
  type FlowPacket,
  type ParticipantInfo,
} from "@/lib/flows";
import { FlowEmptyState, FlowPacketRow } from "@/features/flows";

interface Props {
  projectId: string;
  viewerUserId?: string;
}

interface BucketState {
  loading: boolean;
  error: string | null;
  packets: FlowPacket[];
  // Slice D — participants sidecar accompanies each bucket fetch. The
  // EvidenceBlock reads it for user_id → display_name resolution
  // without N+1.
  participants: Record<string, ParticipantInfo>;
}

const initial: BucketState = {
  loading: true,
  error: null,
  packets: [],
  participants: {},
};

export function FlowsPanelBody({ projectId, viewerUserId }: Props) {
  const t = useTranslations("flows");
  const [byBucket, setByBucket] = useState<Record<FlowBucket, BucketState>>({
    needs_me: initial,
    waiting_on_others: initial,
    awaiting_membrane: initial,
    // `recent` is in the union (used by detail views later) but the
    // drawer doesn't render it; keeping the shape exhaustive keeps
    // the typed accessor honest.
    recent: initial,
  });

  // Three parallel fetches. Each bucket has its own state slot so a
  // slow / failed bucket doesn't block the other two from rendering.
  // Extracted into a refresh callback so action rows can re-trigger
  // it after a successful mutation (C.1.c).
  const refresh = useCallback(() => {
    let cancelled = false;
    BUCKETS.forEach((bucket) => {
      void (async () => {
        try {
          const res = await listFlows(projectId, { bucket });
          if (cancelled) return;
          setByBucket((prev) => ({
            ...prev,
            [bucket]: {
              loading: false,
              error: null,
              packets: res.packets,
              participants: res.participants ?? {},
            },
          }));
        } catch (err) {
          if (cancelled) return;
          setByBucket((prev) => ({
            ...prev,
            [bucket]: {
              loading: false,
              error: err instanceof Error ? err.message : "fetch_failed",
              packets: [],
              participants: {},
            },
          }));
        }
      })();
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    return refresh();
  }, [refresh]);

  return (
    <div
      data-testid="flows-panel"
      style={{ display: "flex", flexDirection: "column", gap: 14 }}
    >
      <p
        style={{
          margin: 0,
          fontSize: 11,
          color: "var(--wg-ink-soft)",
          lineHeight: 1.5,
        }}
      >
        {t("subtitle")}
      </p>
      {BUCKETS.map((bucket) => (
        <BucketSection
          key={bucket}
          bucket={bucket}
          state={byBucket[bucket]}
          onActed={refresh}
          viewerUserId={viewerUserId}
        />
      ))}
    </div>
  );
}

function BucketSection({
  bucket,
  state,
  onActed,
  viewerUserId,
}: {
  bucket: FlowBucket;
  state: BucketState;
  onActed: () => void;
  viewerUserId?: string;
}) {
  const t = useTranslations("flows");
  // i18n key for the bucket header — `needs_me` → `needsMe`. Camel-
  // case the second word so the JSON tree stays compact.
  const labelKey = camelBucket(bucket);
  return (
    <section
      data-testid={`flows-bucket-${bucket}`}
      style={{ display: "flex", flexDirection: "column", gap: 6 }}
    >
      <header style={bucketHeaderStyle}>
        <span style={{ fontSize: 12, fontWeight: 600 }}>
          {t(`buckets.${labelKey}`)}
        </span>
        <span
          style={{
            fontSize: 10,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
          }}
        >
          {state.loading ? "…" : state.packets.length}
        </span>
      </header>
      {state.loading ? (
        <FlowEmptyState text={t("loading")} />
      ) : state.error ? (
        <FlowEmptyState text={t("error")} variant="error" />
      ) : state.packets.length === 0 ? (
        <FlowEmptyState text={t(`empty.${labelKey}`)} />
      ) : (
        state.packets.map((p) => (
          <FlowPacketRow
            key={p.id}
            packet={p}
            participants={state.participants}
            onActed={onActed}
            viewerUserId={viewerUserId}
          />
        ))
      )}
    </section>
  );
}

function camelBucket(b: FlowBucket): "needsMe" | "waitingOnOthers" | "awaitingMembrane" | "recent" {
  switch (b) {
    case "needs_me":
      return "needsMe";
    case "waiting_on_others":
      return "waitingOnOthers";
    case "awaiting_membrane":
      return "awaitingMembrane";
    case "recent":
      return "recent";
  }
}

const bucketHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  paddingBottom: 4,
  borderBottom: "1px solid var(--wg-line-faint, #f0f0f0)",
};
