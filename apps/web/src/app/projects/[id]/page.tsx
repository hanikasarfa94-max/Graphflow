// /projects/[id] — Phase Q primary surface.
//
// Renders the user's personal project stream (their conversation with
// their sub-agent). Navigation to team room, status, KB, renders etc.
// happens from the global left sidebar now — no per-project top tabs.
//
// The team stream lives at `/projects/[id]/team`; nothing else about
// the project layout / audit navigation changes.

import { PersonalStream } from "@/components/stream/PersonalStream";
import type { StreamMember } from "@/components/stream/types";
import type { ProjectState } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ProjectPersonalPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const user = await requireUser(`/projects/${id}`);

  let state: ProjectState | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch {
    state = null;
  }

  const members: StreamMember[] = (state?.members ?? []).map((m) => ({
    user_id: m.user_id,
    username: m.username,
    display_name: m.display_name,
    role_in_stream: m.role,
  }));

  return (
    <PersonalStream
      projectId={id}
      currentUserId={user.id}
      members={members}
    />
  );
}
