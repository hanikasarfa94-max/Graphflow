import type { ProjectState } from "@/lib/api";
import { serverFetch } from "@/lib/auth";

import { ClarifyPanel } from "./ClarifyPanel";

export const dynamic = "force-dynamic";

export default async function ClarifyTab({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  return <ClarifyPanel projectId={id} initial={state.clarifications} />;
}
