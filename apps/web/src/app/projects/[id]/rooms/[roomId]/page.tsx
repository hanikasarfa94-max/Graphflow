// /projects/[id]/rooms/[roomId] — room-stream surface.
//
// Server component: fetches the rooms list (single round trip — gives
// us the target room's metadata AND the roomNameById map for the
// DecisionCard explainer at the same time), then mounts RoomShell.

import { notFound } from "next/navigation";

import { RoomShell } from "@/components/rooms/RoomShell";
import type { RoomSummary } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function RoomPage({
  params,
}: {
  params: Promise<{ id: string; roomId: string }>;
}) {
  const { id, roomId } = await params;
  const user = await requireUser(`/projects/${id}/rooms/${roomId}`);

  let rooms: RoomSummary[] = [];
  try {
    const resp = await serverFetch<{ rooms: RoomSummary[] }>(
      `/api/projects/${id}/rooms`,
    );
    rooms = resp.rooms;
  } catch {
    // 403 (non-member of project) or 5xx — render not-found rather
    // than expose internals.
    notFound();
  }

  const room = rooms.find((r) => r.id === roomId);
  if (!room) {
    notFound();
  }

  // Map keyed by stream id for DecisionCard's vote-scope explainer.
  // Built once here to avoid an N+1 fetch per card.
  const roomNameById: Record<string, { name: string; memberCount: number }> = {};
  for (const r of rooms) {
    if (r.name) {
      roomNameById[r.id] = {
        name: r.name,
        memberCount: r.members?.length ?? 0,
      };
    }
  }

  return (
    <RoomShell
      projectId={id}
      currentUserId={user.id}
      room={room}
      roomNameById={roomNameById}
    />
  );
}
