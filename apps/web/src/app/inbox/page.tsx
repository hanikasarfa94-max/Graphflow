// /inbox — Batch E.5 dedicated routing inbox surface.
//
// The drawer (RoutedInboundDrawer) is fast for triage; this page is
// the "I want to see them all and reply at my pace" view per the
// home_redesign html. Server component pulls both queues in parallel,
// renders pending routed signals + gated approvals as a 2-column
// dashboard, and links back to the project stream where each signal
// can be answered with the full rich-options card.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Card, EmptyState, PageHeader, Tag, Text } from "@/components/ui";
import type {
  GatedInboxItem,
  RoutingInboxResponse,
  RoutingSignal,
} from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function RoutingInboxPage() {
  await requireUser("/inbox");
  const t = await getTranslations("inboxPage");

  // Parallel fetches; one failing doesn't kill the other surface.
  const [routedResp, gatedResp] = await Promise.all([
    serverFetch<RoutingInboxResponse>(
      "/api/routing/inbox?status=pending&limit=100",
    ).catch(() => ({ signals: [] as RoutingSignal[] })),
    serverFetch<{ ok: boolean; items: GatedInboxItem[] }>(
      "/api/inbox/gated?limit=100",
    ).catch(() => ({ ok: false, items: [] as GatedInboxItem[] })),
  ]);

  const signals = routedResp.signals ?? [];
  const gated = gatedResp.items ?? [];
  const total = signals.length + gated.length;

  return (
    <main style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 28px 80px" }}>
      <PageHeader
        kicker={t("kicker")}
        title={t("title")}
        subtitle={t("subtitle")}
        right={
          total > 0 ? (
            <Tag tone="accent" size="md">
              {t("totalPending", { count: total })}
            </Tag>
          ) : null
        }
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)",
          gap: 18,
        }}
      >
        <Card title={t("routedHeading")} subtitle={String(signals.length)}>
          {signals.length === 0 ? (
            <EmptyState>{t("routedEmpty")}</EmptyState>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {signals.map((s) => (
                <RoutedRow key={s.id} signal={s} t={t} />
              ))}
            </div>
          )}
        </Card>
        <Card title={t("gatedHeading")} subtitle={String(gated.length)}>
          {gated.length === 0 ? (
            <EmptyState>{t("gatedEmpty")}</EmptyState>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {gated.map((g) => (
                <GatedRow key={g.proposal.id} item={g} t={t} />
              ))}
            </div>
          )}
        </Card>
      </div>
    </main>
  );
}

function RoutedRow({
  signal,
  t,
}: {
  signal: RoutingSignal;
  t: Awaited<ReturnType<typeof getTranslations>>;
}) {
  // Anchor the user back to the project's team-room scrolled to the
  // routing message — that's where the rich-options card already lives
  // (RoutedInboundCard). We don't re-implement the answer flow here.
  const href = `/projects/${signal.project_id}/team#routing-${signal.id}`;
  return (
    <Link
      href={href}
      style={{
        display: "block",
        padding: 14,
        border: "1px solid var(--wg-line)",
        borderLeft: "3px solid var(--wg-accent)",
        borderRadius: 12,
        background: "var(--wg-surface)",
        textDecoration: "none",
        color: "inherit",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <Tag tone="accent">{t("routedTag")}</Tag>
        <Text variant="caption" muted>
          {signal.created_at
            ? new Date(signal.created_at).toLocaleString()
            : ""}
        </Text>
      </div>
      <div
        style={{
          marginTop: 8,
          fontSize: 14,
          color: "var(--wg-ink)",
          lineHeight: 1.45,
          fontWeight: 500,
        }}
      >
        {signal.framing || t("routedNoFraming")}
      </div>
      {signal.options.length > 0 ? (
        <div
          style={{
            marginTop: 8,
            display: "flex",
            gap: 6,
            flexWrap: "wrap",
            fontSize: 12,
            color: "var(--wg-ink-soft)",
          }}
        >
          {signal.options.slice(0, 3).map((opt, i) => (
            <span
              key={i}
              style={{
                padding: "2px 8px",
                background: "var(--wg-surface-sunk)",
                border: "1px solid var(--wg-line)",
                borderRadius: 999,
                fontFamily: "var(--wg-font-mono)",
                fontSize: 11,
              }}
            >
              {opt.label || `option ${i + 1}`}
            </span>
          ))}
        </div>
      ) : null}
      <div
        style={{
          marginTop: 10,
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-accent)",
        }}
      >
        {t("openInTeamRoom")} →
      </div>
    </Link>
  );
}

function GatedRow({
  item,
  t,
}: {
  item: GatedInboxItem;
  t: Awaited<ReturnType<typeof getTranslations>>;
}) {
  const p = item.proposal;
  const href = `/projects/${p.project_id}/team#proposal-${p.id}`;
  return (
    <Link
      href={href}
      style={{
        display: "block",
        padding: 12,
        border: "1px solid var(--wg-line)",
        borderRadius: 10,
        background: "var(--wg-surface)",
        textDecoration: "none",
        color: "inherit",
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <Tag tone="amber">{t("gatedTag", { cls: p.decision_class })}</Tag>
        <Text variant="caption" muted>
          {item.created_at
            ? new Date(item.created_at).toLocaleDateString()
            : ""}
        </Text>
      </div>
      <div
        style={{
          marginTop: 6,
          fontSize: 13,
          color: "var(--wg-ink)",
          lineHeight: 1.4,
        }}
      >
        {p.proposal_body || p.decision_text || t("gatedNoSummary")}
      </div>
      <div
        style={{
          marginTop: 8,
          fontSize: 12,
          fontFamily: "var(--wg-font-mono)",
          color: "var(--wg-accent)",
        }}
      >
        {t("openInTeamRoom")} →
      </div>
    </Link>
  );
}
