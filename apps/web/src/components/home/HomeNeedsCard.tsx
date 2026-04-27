// HomeNeedsCard — Batch F.1 home row 2, left card.
//
// Replaces the flat PendingSection list with a Card-wrapped queue of
// task-row entries (icon tile + title + meta + tag) per the html2
// spec. When the queue is empty we fall back to the ActiveContext
// signal so the slot is never empty (caught-up / last-decision /
// active-task), keeping the "home is never empty" north-star.
//
// Server component — pending payload is already prepared by
// loadHomeData; nothing here needs client state.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { relativeTime } from "@/components/stream/types";
import { Card, EmptyState, Tag, Text } from "@/components/ui";
import type { PendingSignal } from "@/lib/api";

import type { ActiveContext } from "./data";

type Tone = React.ComponentProps<typeof Tag>["tone"];

function kindToTone(kind: PendingSignal["kind"]): Tone {
  switch (kind) {
    case "decision":
      return "accent";
    case "blocker":
      return "danger";
    case "tag":
      return "neutral";
    default:
      return "amber";
  }
}

function kindToIcon(kind: PendingSignal["kind"]): string {
  switch (kind) {
    case "decision":
      return "◇";
    case "blocker":
      return "↯";
    case "tag":
      return "✓";
    default:
      return "◦";
  }
}

const INITIAL_LIMIT = 6;

export async function HomeNeedsCard({
  pending,
  active,
}: {
  pending: PendingSignal[];
  active: ActiveContext;
}) {
  const t = await getTranslations();

  const subtitle =
    pending.length > 0 ? String(pending.length) : undefined;

  return (
    <Card title={t("home.pending.title")} subtitle={subtitle}>
      {pending.length === 0 ? (
        <FallbackBlock active={active} t={t} />
      ) : (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          {pending.slice(0, INITIAL_LIMIT).map((p) => (
            <NeedsRow
              key={p.suggestion_id}
              p={p}
              fromLabel={t("home.pending.fromProject", {
                project: p.project_title,
              })}
              jumpLabel={t("home.pending.jumpToTurn")}
            />
          ))}
          {pending.length > INITIAL_LIMIT ? (
            <Link
              href="/inbox"
              style={{
                marginTop: 4,
                textAlign: "right",
                fontSize: 12,
                fontFamily: "var(--wg-font-mono)",
                color: "var(--wg-accent)",
                textDecoration: "none",
              }}
            >
              {t("home.pending.viewAll", {
                count: pending.length - INITIAL_LIMIT,
              })}{" "}
              →
            </Link>
          ) : null}
        </div>
      )}
    </Card>
  );
}

function NeedsRow({
  p,
  fromLabel,
  jumpLabel,
}: {
  p: PendingSignal;
  fromLabel: string;
  jumpLabel: string;
}) {
  const tone = kindToTone(p.kind);
  const icon = kindToIcon(p.kind);
  return (
    <Link
      href={p.jump_href}
      title={jumpLabel}
      style={{
        display: "grid",
        gridTemplateColumns: "42px minmax(0, 1fr) auto",
        alignItems: "center",
        gap: 12,
        padding: 12,
        background: "var(--wg-surface)",
        border: "1px solid var(--wg-line)",
        borderRadius: 14,
        textDecoration: "none",
        color: "inherit",
      }}
    >
      <span
        aria-hidden
        style={{
          width: 42,
          height: 42,
          borderRadius: 12,
          display: "grid",
          placeItems: "center",
          background:
            tone === "accent"
              ? "var(--wg-accent-soft)"
              : tone === "amber"
                ? "var(--wg-amber-soft)"
                : tone === "danger"
                  ? "rgba(220, 38, 38, 0.10)"
                  : "var(--wg-surface-sunk)",
          color:
            tone === "accent"
              ? "var(--wg-accent)"
              : tone === "amber"
                ? "var(--wg-amber)"
                : tone === "danger"
                  ? "var(--wg-danger)"
                  : "var(--wg-ink-soft)",
          fontWeight: 700,
          fontSize: 16,
        }}
      >
        {icon}
      </span>
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: 14,
            color: "var(--wg-ink)",
            fontWeight: 500,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {p.summary}
        </div>
        <div
          style={{
            marginTop: 3,
            fontSize: 11,
            color: "var(--wg-ink-faint)",
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {fromLabel} · {relativeTime(p.created_at)}
        </div>
      </div>
      <Tag tone={tone}>{p.kind}</Tag>
    </Link>
  );
}

function FallbackBlock({
  active,
  t,
}: {
  active: ActiveContext;
  t: Awaited<ReturnType<typeof getTranslations>>;
}) {
  if (active.kind === "task") {
    return (
      <Link
        href={`/projects/${active.project_id}`}
        style={{
          display: "block",
          padding: 14,
          border: "1px solid var(--wg-line)",
          borderRadius: 14,
          background: "var(--wg-surface)",
          textDecoration: "none",
          color: "inherit",
        }}
      >
        <Text
          variant="caption"
          muted
          style={{
            letterSpacing: "0.1em",
            textTransform: "uppercase",
          }}
        >
          {t("home.active.title")}
        </Text>
        <div
          style={{
            marginTop: 6,
            fontSize: 14,
            fontWeight: 500,
            color: "var(--wg-ink)",
          }}
        >
          {active.task_title}
        </div>
        <Text
          variant="caption"
          muted
          style={{
            marginTop: 2,
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {active.project_title} · {active.status}
        </Text>
      </Link>
    );
  }
  if (active.kind === "last_decision") {
    return (
      <EmptyState>
        {t("home.active.lastDecisionFallback", {
          project: active.project_title,
          summary: active.summary,
          time: active.created_at ? relativeTime(active.created_at) : "—",
        })}
      </EmptyState>
    );
  }
  return (
    <EmptyState>
      {active.last_crystallization_at
        ? t("home.active.caughtUpLastCrystallization", {
            time: relativeTime(active.last_crystallization_at),
          })
        : t("home.active.caughtUpNoHistory")}
    </EmptyState>
  );
}
