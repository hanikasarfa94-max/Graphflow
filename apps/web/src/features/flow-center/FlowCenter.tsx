"use client";

// FlowCenter — the doctrine-load-bearing surface for v0.6.2.
//
// Phase RW-2.1 wiring (2026-05-13): real packets via
// GET /api/flow-requests?scope_id=…. The page-level server component
// (app/flow-center/page.tsx) does the fetch + active-scope lookup,
// then passes packets/participants/activeScopeId/userId here.
//
// The 4-tile metric strip computes its counts from the packet list —
// no separate summary endpoint required for the read path. Counts are
// derived, not mocked.

import { Card, EmptyState, Metric, PageHeader, Text } from "@/components/ui";
import { useTranslations } from "next-intl";

import { FlowTable } from "./FlowTable";
import type { FlowListResponse } from "./types";

interface FlowCenterMetrics {
  needsMe: number;
  waiting: number;
  awaitingMembrane: number;
  completed: number;
}

function computeMetrics(
  packets: FlowListResponse["packets"],
  userId: string,
): FlowCenterMetrics {
  let needsMe = 0;
  let waiting = 0;
  let awaitingMembrane = 0;
  let completed = 0;
  for (const p of packets) {
    if (p.status === "completed") {
      completed += 1;
      continue;
    }
    if (p.stage === "awaiting_membrane") {
      awaitingMembrane += 1;
    }
    if (p.current_target_user_ids.includes(userId)) {
      needsMe += 1;
    } else if (p.source_user_id === userId) {
      waiting += 1;
    }
  }
  return { needsMe, waiting, awaitingMembrane, completed };
}

export function FlowCenter({
  data,
  activeScopeId,
  userId,
}: {
  data: FlowListResponse;
  activeScopeId: string | null;
  userId: string;
}) {
  const t = useTranslations("shellV062.flowCenter.page");
  const metrics = computeMetrics(data.packets, userId);

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker={t("kicker")}
        title={t("title")}
        subtitle={t("subtitle")}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 12,
          marginBottom: 20,
        }}
      >
        <Metric value={metrics.needsMe} label={t("metrics.needsMe")} tone="accent" />
        <Metric value={metrics.waiting} label={t("metrics.waiting")} />
        <Metric
          value={metrics.awaitingMembrane}
          label={t("metrics.awaitingMembrane")}
          tone="amber"
        />
        <Metric value={metrics.completed} label={t("metrics.completed")} />
      </div>

      {activeScopeId === null ? (
        // No scope selected — the read endpoint is scope-bound. Tell
        // the user how to get content; do NOT fall back to mock rows.
        <Card>
          <EmptyState>
            {t("needScope")}
          </EmptyState>
        </Card>
      ) : (
        <Card title={t("tableTitle")} flush>
          <FlowTable data={data} userId={userId} />
        </Card>
      )}

      <Text
        as="p"
        variant="caption"
        muted
        style={{ marginTop: 16, textAlign: "center" }}
      >
        {t("footer")}
      </Text>
    </main>
  );
}
