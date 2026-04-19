import type { ProjectState } from "@/lib/api";
import { serverFetch } from "@/lib/auth";

import { PlanTable } from "./PlanTable";

export const dynamic = "force-dynamic";

export default async function PlanTab({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);

  if (state.plan.tasks.length === 0) {
    return (
      <div
        style={{
          padding: 32,
          textAlign: "center",
          color: "var(--wg-ink-soft)",
          border: "1px dashed var(--wg-line)",
          borderRadius: "var(--wg-radius)",
        }}
      >
        No plan yet. The planning agent runs after clarifications are answered.
      </div>
    );
  }

  return <PlanTable state={state} />;
}
