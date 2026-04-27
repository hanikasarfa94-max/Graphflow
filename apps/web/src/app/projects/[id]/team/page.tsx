// /projects/[id]/team — Phase N team room sub-route.
//
// The Phase E team stream (previously the project default) moved here.
// Renderer is unchanged (`StreamView`); only the route changed. Personal
// stream is now the default at `/projects/[id]`.

// /projects/[id]/team — team room sub-route.
//
// Phase Q removed the in-page PersonalTabs; navigation now lives in the
// global AppSidebar. This page just renders the team-room stream.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { StreamCompactToolbar } from "@/components/stream/StreamCompactToolbar";
import { StreamContextPanel } from "@/components/stream/StreamContextPanel";
import { StreamView } from "@/components/stream/StreamView";
import { TeamRoomRecap } from "@/components/stream/TeamRoomRecap";
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

  // Surface the perf panel link to project admins only. Members still
  // see the team stream without noise. The backend is the source of
  // truth — this is just a nav affordance; a non-admin who hits the
  // route directly gets an inline 403 message, not a crash.
  const viewerMembership = state?.members.find(
    (m) => m.user_id === user.id,
  );
  const isAdmin =
    viewerMembership?.role === "owner" &&
    (viewerMembership.license_tier ?? "full") === "full";

  const t = await getTranslations("teamPerf");
  const tShell = await getTranslations();

  return (
    <>
      <StreamCompactToolbar
        title={tShell("personal.tabs.teamRoom")}
        meta={state?.project?.title}
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <StreamContextPanel streamKey={`project:${id}:team`} />
            {isAdmin ? (
              <Link
                href={`/projects/${id}/team/perf`}
                style={{
                  fontSize: 12,
                  fontFamily: "var(--wg-font-mono)",
                  color: "var(--wg-accent)",
                  textDecoration: "none",
                  padding: "4px 10px",
                  border:
                    "1px solid var(--wg-accent-ring, var(--wg-accent))",
                  borderRadius: 12,
                }}
              >
                {t("linkToPanel")} →
              </Link>
            ) : null}
          </div>
        }
      />
      <StreamView
        projectId={id}
        currentUserId={user.id}
        members={members}
        streamId={streamId}
        streamKey={`project:${id}:team`}
      />
      <TeamRoomRecap state={state} streamKey={`project:${id}:team`} />
    </>
  );
}
