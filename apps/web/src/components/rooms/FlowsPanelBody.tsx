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

import Link from "next/link";
import { useEffect, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import {
  BUCKETS,
  RECIPE_ICON,
  listFlows,
  type FlowBucket,
  type FlowPacket,
} from "@/lib/flows";
import { formatIso } from "@/lib/time";

interface Props {
  projectId: string;
}

interface BucketState {
  loading: boolean;
  error: string | null;
  packets: FlowPacket[];
}

const initial: BucketState = { loading: true, error: null, packets: [] };

export function FlowsPanelBody({ projectId }: Props) {
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
  useEffect(() => {
    let cancelled = false;
    BUCKETS.forEach((bucket) => {
      void (async () => {
        try {
          const res = await listFlows(projectId, { bucket });
          if (cancelled) return;
          setByBucket((prev) => ({
            ...prev,
            [bucket]: { loading: false, error: null, packets: res.packets },
          }));
        } catch (err) {
          if (cancelled) return;
          setByBucket((prev) => ({
            ...prev,
            [bucket]: {
              loading: false,
              error: err instanceof Error ? err.message : "fetch_failed",
              packets: [],
            },
          }));
        }
      })();
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

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
        />
      ))}
    </div>
  );
}

function BucketSection({
  bucket,
  state,
}: {
  bucket: FlowBucket;
  state: BucketState;
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
        <Empty text={t("loading")} />
      ) : state.error ? (
        <Empty text={t("error")} variant="error" />
      ) : state.packets.length === 0 ? (
        <Empty text={t(`empty.${labelKey}`)} />
      ) : (
        state.packets.map((p) => <FlowRow key={p.id} packet={p} />)
      )}
    </section>
  );
}

function FlowRow({ packet }: { packet: FlowPacket }) {
  const t = useTranslations("flows");
  // Spec §6: drawer reads `current_target_user_ids` for who is
  // currently blocking, not `target_user_ids`. We surface the count
  // as a tiny meta chip; resolving user_ids → display_names is a
  // Slice D concern (members hook would add a client-side lookup).
  const currentBlocking = packet.current_target_user_ids.length;
  const recipeLabel = t(`recipes.${packet.recipe_id}`);
  const stageLabel = stageDisplay(packet.stage, t);
  const updated = packet.updated_at ?? packet.created_at;
  // Open follows next_actions[0].href verbatim. We do NOT compute
  // routes from recipe_id — that would re-bake the routing logic the
  // BE already encoded.
  const openAction = packet.next_actions.find((a) => a.kind === "open");
  const href = openAction?.href ?? null;
  return (
    <div
      data-testid="flow-row"
      data-recipe={packet.recipe_id}
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr auto",
        alignItems: "start",
        gap: 8,
        padding: "8px 10px",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "#fff",
      }}
    >
      <span
        aria-hidden
        style={{ fontSize: 16, lineHeight: "20px", marginTop: 2 }}
      >
        {RECIPE_ICON[packet.recipe_id] ?? "•"}
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
        <strong
          style={{
            fontSize: 13,
            color: "var(--wg-ink)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={packet.title}
        >
          {packet.title}
        </strong>
        <span
          style={{
            fontSize: 11,
            color: "var(--wg-ink-soft)",
            display: "flex",
            gap: 6,
            flexWrap: "wrap",
          }}
        >
          <span style={metaChipStyle}>{recipeLabel}</span>
          <span style={metaChipStyle}>{stageLabel}</span>
          {currentBlocking > 0 ? (
            <span style={metaChipStyle}>
              {currentBlocking === 1 ? "1 actor" : `${currentBlocking} actors`}
            </span>
          ) : null}
          <span style={{ color: "var(--wg-ink-faint)" }}>
            {t("metaUpdated", { time: formatIso(updated) })}
          </span>
        </span>
      </div>
      {href ? (
        <Link
          href={href}
          data-testid="flow-row-open"
          style={openLinkStyle}
        >
          {t("open")}
        </Link>
      ) : (
        <span style={{ ...openLinkStyle, opacity: 0.5, cursor: "default" }}>
          {t("openMissing")}
        </span>
      )}
    </div>
  );
}

function Empty({
  text,
  variant,
}: {
  text: string;
  variant?: "error";
}) {
  return (
    <p
      data-testid={variant === "error" ? "flows-bucket-error" : "flows-bucket-empty"}
      style={{
        margin: 0,
        padding: "8px 10px",
        fontSize: 12,
        color: variant === "error" ? "var(--wg-accent)" : "var(--wg-ink-soft)",
        fontStyle: variant === "error" ? "normal" : "italic",
        background: "var(--wg-surface, #fafafa)",
        border: "1px dashed var(--wg-line)",
        borderRadius: "var(--wg-radius)",
      }}
    >
      {text}
    </p>
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

const bucketHeaderStyle: CSSProperties = {
  display: "flex",
  alignItems: "baseline",
  justifyContent: "space-between",
  paddingBottom: 4,
  borderBottom: "1px solid var(--wg-line-faint, #f0f0f0)",
};

const metaChipStyle: CSSProperties = {
  padding: "1px 6px",
  fontSize: 10,
  fontFamily: "var(--wg-font-mono)",
  background: "var(--wg-surface, #fafafa)",
  border: "1px solid var(--wg-line)",
  borderRadius: 10,
  color: "var(--wg-ink-soft)",
};

const openLinkStyle: CSSProperties = {
  alignSelf: "center",
  padding: "4px 10px",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  border: "1px solid var(--wg-line)",
  borderRadius: 3,
  background: "#fff",
  color: "var(--wg-accent)",
  textDecoration: "none",
  whiteSpace: "nowrap",
};
