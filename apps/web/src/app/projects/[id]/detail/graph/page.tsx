import type { ProjectState } from "@/lib/api";
import { serverFetch } from "@/lib/auth";

import { GraphCanvas } from "./GraphCanvas";

export const dynamic = "force-dynamic";

export default async function GraphTab({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  return (
    <div
      style={{
        height: 620,
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "#fff",
        overflow: "hidden",
      }}
    >
      <GraphCanvas state={state} />
    </div>
  );
}
