import type { ProjectState } from "@/lib/api";
import { serverFetch } from "@/lib/auth";

import { ConflictsPane } from "./ConflictsPane";

export const dynamic = "force-dynamic";

export default async function ConflictsTab({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);

  return (
    <ConflictsPane
      projectId={id}
      initialConflicts={state.conflicts ?? []}
      initialSummary={
        state.conflict_summary ?? {
          open: 0,
          critical: 0,
          high: 0,
          medium: 0,
          low: 0,
        }
      }
      initialDecisions={state.decisions ?? []}
      initialMembers={state.members ?? []}
    />
  );
}
