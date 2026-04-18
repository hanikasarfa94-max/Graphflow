import type { Delivery, ProjectState } from "@/lib/api";
import { serverFetch } from "@/lib/auth";

import { ConsoleShell } from "./ConsoleShell";

export const dynamic = "force-dynamic";

export default async function ConsolePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  const [state, history] = await Promise.all([
    serverFetch<ProjectState>(`/api/projects/${id}/state`),
    serverFetch<{ deliveries: Delivery[] }>(
      `/api/projects/${id}/delivery/history`,
    ).catch(() => ({ deliveries: [] as Delivery[] })),
  ]);

  return (
    <ConsoleShell
      projectId={id}
      initialState={state}
      initialDeliveryHistory={history.deliveries ?? []}
    />
  );
}
