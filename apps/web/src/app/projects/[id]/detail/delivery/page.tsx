import type { Delivery, ProjectState } from "@/lib/api";
import { serverFetch } from "@/lib/auth";

import { DeliveryPane } from "./DeliveryPane";

export const dynamic = "force-dynamic";

export default async function DeliveryTab({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  const history = await serverFetch<{ deliveries: Delivery[] }>(
    `/api/projects/${id}/delivery/history`,
  );

  return (
    <DeliveryPane
      projectId={id}
      initialLatest={state.delivery}
      initialHistory={history.deliveries ?? []}
      initialTasks={state.plan.tasks}
    />
  );
}
