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
  let state: ProjectState | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch {
    state = null;
  }
  if (!state) {
    return (
      <div
        style={{
          padding: 24,
          border: "1px dashed var(--wg-line)",
          borderRadius: "var(--wg-radius)",
          color: "var(--wg-ink-faint)",
          fontSize: 13,
          textAlign: "center",
        }}
      >
        graph unavailable — not a project member or state fetch failed
      </div>
    );
  }
  return (
    <div
      style={{
        height: "calc(100vh - 120px)",
        minHeight: 520,
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "#fff",
        overflow: "hidden",
      }}
    >
      <GraphCanvas projectId={id} state={state} />
    </div>
  );
}
