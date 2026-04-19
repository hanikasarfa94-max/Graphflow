// /projects/[id]/team — Phase N team room sub-route.
//
// The Phase E team stream (previously the project default) moved here.
// Renderer is unchanged (`StreamView`); only the route changed. Personal
// stream is now the default at `/projects/[id]`.

// /projects/[id]/team — team room sub-route.
//
// Phase Q removed the in-page PersonalTabs; navigation now lives in the
// global AppSidebar. This page just renders the team-room stream.

import { StreamView } from "@/components/stream/StreamView";
import type { StreamMember } from "@/components/stream/types";
import type { ProjectState, StreamSummary } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ProjectTeamPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const user = await requireUser(`/projects/${id}/team`);

  let state: ProjectState | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch {
    state = null;
  }

  let streamId: string | undefined;
  try {
    const streams = await serverFetch<{ streams: StreamSummary[] }>(
      `/api/streams`,
    );
    const match = streams.streams.find(
      (s) => s.type === "project" && s.project_id === id,
    );
    streamId = match?.id;
  } catch {
    // best-effort
  }

  const members: StreamMember[] = (state?.members ?? []).map((m) => ({
    user_id: m.user_id,
    username: m.username,
    display_name: m.display_name,
    role_in_stream: m.role,
  }));

  return (
    <StreamView
      projectId={id}
      currentUserId={user.id}
      members={members}
      streamId={streamId}
    />
  );
}
