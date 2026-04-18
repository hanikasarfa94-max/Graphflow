import { serverFetch } from "@/lib/auth";

import { HealthPanel, type HealthSummary } from "./HealthPanel";

export const dynamic = "force-dynamic";

export default async function HealthPage() {
  const initial = await serverFetch<HealthSummary>(
    "/api/observability/health?window_minutes=60",
  );
  return <HealthPanel initial={initial} />;
}
