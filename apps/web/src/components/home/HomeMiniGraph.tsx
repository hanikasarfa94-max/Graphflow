// HomeMiniGraph — Batch F.1 home row 2, right card.
//
// Mini visualisation of the user's most-active project. Up to 5 nodes
// laid out on a fixed 4×3 grid with curved CSS-rotated edges between
// them, styled to match the html2 redesign's `.graph-mini`. This is
// purely decorative — the real interactive graph lives at /detail/graph.
//
// Server component. Falls back to a friendly empty state when the user
// has no projects (or none have a graph snapshot yet).

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Card, EmptyState, Tag } from "@/components/ui";

import type { HomeMiniGraphNode, HomeTopProjectSnapshot } from "./data";

// Hand-tuned slot positions for up to 5 nodes — left-to-right reading
// order matches the goal → deliverable → decision → task → risk
// priority used by the loader. The pixel positions sit inside a 360×220
// canvas with comfortable padding so the labels don't overflow.
const SLOTS: Array<{ left: number; top: number }> = [
  { left: 12, top: 30 },
  { left: 195, top: 14 },
  { left: 80, top: 110 },
  { left: 230, top: 100 },
  { left: 30, top: 165 },
];

function kindToColor(kind: HomeMiniGraphNode["kind"]): string {
  switch (kind) {
    case "goal":
      return "var(--wg-accent)";
    case "deliverable":
      return "var(--wg-ok)";
    case "decision":
      return "var(--wg-accent)";
    case "task":
      return "var(--wg-ink-soft)";
    case "risk":
      return "var(--wg-danger)";
  }
}

export async function HomeMiniGraph({
  snapshot,
}: {
  snapshot: HomeTopProjectSnapshot | null;
}) {
  const t = await getTranslations("home.miniGraph");

  if (!snapshot || snapshot.nodes.length === 0) {
    return (
      <Card title={t("title")}>
        <EmptyState>{t("empty")}</EmptyState>
      </Card>
    );
  }

  const slotByNodeId = new Map<string, { left: number; top: number }>();
  snapshot.nodes.forEach((n, i) => {
    if (i < SLOTS.length) slotByNodeId.set(n.id, SLOTS[i]);
  });

  const linkHref = `/projects/${snapshot.project_id}/detail/graph`;

  return (
    <Card
      title={t("title")}
      subtitle={snapshot.project_title}
    >
      <div
        style={{
          height: 230,
          borderRadius: 14,
          border: "1px dashed var(--wg-line)",
          background:
            "linear-gradient(90deg, rgba(37,99,235,0.05) 1px, transparent 1px),\
             linear-gradient(0deg, rgba(37,99,235,0.05) 1px, transparent 1px),\
             #f8fbff",
          backgroundSize: "26px 26px",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {snapshot.edges.map((e, i) => {
          const a = slotByNodeId.get(e.from);
          const b = slotByNodeId.get(e.to);
          if (!a || !b) return null;
          // Approx node centre: slot + 50px right, 14px down (half a
          // typical node card). Good enough for a decorative line.
          const ax = a.left + 50;
          const ay = a.top + 16;
          const bx = b.left + 50;
          const by = b.top + 16;
          const dx = bx - ax;
          const dy = by - ay;
          const length = Math.sqrt(dx * dx + dy * dy);
          const angle = (Math.atan2(dy, dx) * 180) / Math.PI;
          return (
            <span
              key={i}
              aria-hidden
              style={{
                position: "absolute",
                left: ax,
                top: ay,
                width: length,
                height: 2,
                background: "rgba(37,99,235,0.4)",
                transform: `rotate(${angle}deg)`,
                transformOrigin: "left center",
              }}
            />
          );
        })}
        {snapshot.nodes.slice(0, SLOTS.length).map((n, i) => (
          <div
            key={n.id}
            style={{
              position: "absolute",
              left: SLOTS[i].left,
              top: SLOTS[i].top,
              padding: "8px 10px",
              minWidth: 100,
              maxWidth: 130,
              background: "var(--wg-surface)",
              border: "1px solid var(--wg-line)",
              borderLeft: `3px solid ${kindToColor(n.kind)}`,
              borderRadius: 12,
              boxShadow: "0 6px 14px rgba(30,64,175,0.06)",
            }}
          >
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: "var(--wg-ink)",
                lineHeight: 1.2,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={n.title}
            >
              {n.title}
            </div>
            <div
              style={{
                marginTop: 2,
                fontSize: 10,
                color: "var(--wg-ink-faint)",
                fontFamily: "var(--wg-font-mono)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              {n.kind}
            </div>
          </div>
        ))}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          marginTop: 10,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          <Tag tone="accent">{t("legend.decision")}</Tag>
          <Tag tone="ok">{t("legend.deliverable")}</Tag>
          <Tag tone="danger">{t("legend.risk")}</Tag>
          <Tag tone="neutral">{t("legend.task")}</Tag>
        </div>
        <Link
          href={linkHref}
          style={{
            fontSize: 12,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-accent)",
            textDecoration: "none",
          }}
        >
          {t("openGraph")} →
        </Link>
      </div>
    </Card>
  );
}
