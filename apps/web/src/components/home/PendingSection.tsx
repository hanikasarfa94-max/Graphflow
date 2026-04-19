"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import type { PendingSignal } from "@/lib/api";

import { relativeTime } from "@/components/stream/types";

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
        <div
          style={{
            padding: 16,
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            color: "var(--wg-ink-faint)",
            fontSize: 13,
          }}
        >
          {t("home.pending.empty")}
        </div>
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
            <PendingRow p={p} jumpLabel={t("home.pending.jumpToTurn")} fromLabel={t("home.pending.fromProject", { project: p.project_title })} />
          </li>
        ))}
      </ul>
      {hiddenCount > 0 && !showAll ? (
        <button
          type="button"
          onClick={() => setShowAll(true)}
          style={{
            marginTop: 12,
            background: "transparent",
            border: "none",
            color: "var(--wg-accent)",
            cursor: "pointer",
            fontSize: 13,
            fontFamily: "var(--wg-font-mono)",
          }}
        >
          {t("home.pending.showMore", { count: hiddenCount })}
        </button>
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
  // from a tag at a glance.
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
        <div
          style={{
            fontSize: 14,
            lineHeight: 1.4,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {p.summary}
        </div>
        <div
          style={{
            fontSize: 11,
            color: "var(--wg-ink-faint)",
            fontFamily: "var(--wg-font-mono)",
            marginTop: 2,
          }}
        >
          {fromLabel} · {relativeTime(p.created_at)}
        </div>
      </div>
      <span
        style={{
          color: "var(--wg-accent)",
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          whiteSpace: "nowrap",
        }}
      >
        {jumpLabel}
      </span>
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
