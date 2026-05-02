"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { PendingSignal } from "@/lib/api";

import { RelTime } from "@/components/stream/RelTime";
import { Button, EmptyState, Text } from "@/components/ui";

import { SectionHeader } from "./SectionHeader";

const INITIAL_LIMIT = 10;

// Client component because of the "show more" toggle. Could be server
// with a hidden details/summary; client keeps it one mental model.
export function PendingSection({ pending }: { pending: PendingSignal[] }) {
  const t = useTranslations();
  const [showAll, setShowAll] = useState(false);

  if (pending.length === 0) {
    return (
      <section style={{ marginBottom: 40 }} aria-labelledby="home-pending">
        <SectionHeader title={t("home.pending.title")} />
        <EmptyState>{t("home.pending.empty")}</EmptyState>
      </section>
    );
  }

  const visible = showAll ? pending : pending.slice(0, INITIAL_LIMIT);
  const hiddenCount = pending.length - visible.length;

  return (
    <section style={{ marginBottom: 40 }} aria-labelledby="home-pending">
      <SectionHeader title={t("home.pending.title")} />
      <ul
        style={{
          listStyle: "none",
          padding: 0,
          margin: 0,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {visible.map((p) => (
          <li key={p.suggestion_id}>
            <PendingRow
              p={p}
              jumpLabel={t("home.pending.jumpToTurn")}
              fromLabel={t("home.pending.fromProject", {
                project: p.project_title,
              })}
            />
          </li>
        ))}
      </ul>
      {hiddenCount > 0 && !showAll ? (
        <Button
          variant="link"
          size="sm"
          onClick={() => setShowAll(true)}
          style={{ marginTop: 12 }}
        >
          {t("home.pending.showMore", { count: hiddenCount })}
        </Button>
      ) : null}
    </section>
  );
}

function PendingRow({
  p,
  jumpLabel,
  fromLabel,
}: {
  p: PendingSignal;
  jumpLabel: string;
  fromLabel: string;
}) {
  // Suggestion kind → small colored badge, so the eye can tell a blocker
  // from a tag at a glance. All colors come from the accent/amber/sunk
  // token family — house signal-color rule.
  const badge = badgeStyle(p.kind);
  return (
    <Link
      href={p.jump_href}
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr auto",
        alignItems: "center",
        gap: 12,
        padding: "12px 14px",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        textDecoration: "none",
        color: "var(--wg-ink)",
        background: "var(--wg-surface-raised)",
      }}
    >
      <span
        style={{
          fontSize: 10,
          fontFamily: "var(--wg-font-mono)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "2px 6px",
          borderRadius: 4,
          background: badge.bg,
          color: badge.fg,
          border: `1px solid ${badge.border}`,
          whiteSpace: "nowrap",
        }}
      >
        {p.kind}
      </span>
      <div style={{ minWidth: 0 }}>
        <Text
          as="div"
          variant="body"
          style={{
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {p.summary}
        </Text>
        <Text
          as="div"
          variant="caption"
          muted
          style={{ marginTop: 2, color: "var(--wg-ink-faint)" }}
        >
          {fromLabel} · <RelTime iso={p.created_at} />
        </Text>
      </div>
      <Text
        variant="caption"
        style={{
          color: "var(--wg-accent)",
          whiteSpace: "nowrap",
        }}
      >
        {jumpLabel}
      </Text>
    </Link>
  );
}

function badgeStyle(kind: PendingSignal["kind"]): {
  bg: string;
  fg: string;
  border: string;
} {
  switch (kind) {
    case "decision":
      return {
        bg: "var(--wg-accent-soft)",
        fg: "var(--wg-accent)",
        border: "var(--wg-accent)",
      };
    case "blocker":
      return {
        bg: "var(--wg-amber-soft)",
        fg: "var(--wg-amber)",
        border: "var(--wg-amber)",
      };
    case "tag":
      return {
        bg: "var(--wg-surface-sunk)",
        fg: "var(--wg-ink-soft)",
        border: "var(--wg-line)",
      };
    default:
      return {
        bg: "var(--wg-surface-sunk)",
        fg: "var(--wg-ink-faint)",
        border: "var(--wg-line)",
      };
  }
}
