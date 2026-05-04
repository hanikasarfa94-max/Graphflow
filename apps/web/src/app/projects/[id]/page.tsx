// /projects/[id] — Phase Q primary surface.
//
// Renders the user's personal project stream (their conversation with
// their sub-agent). Navigation to team room, status, KB, renders etc.
// happens from the global left sidebar now — no per-project top tabs.
//
// The team stream lives at `/projects/[id]/team`; nothing else about
// the project layout / audit navigation changes.

import { getTranslations } from "next-intl/server";

import { OnboardingOverlay } from "@/components/onboarding/OnboardingOverlay";
import { PersonalStream } from "@/components/stream/PersonalStream";
import { StreamCompactToolbar } from "@/components/stream/StreamCompactToolbar";
import { StreamContextPanel } from "@/components/stream/StreamContextPanel";
import type { StreamMember } from "@/components/stream/types";
import type { OnboardingWalkthroughResponse, ProjectState } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ProjectPersonalPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const user = await requireUser(`/projects/${id}`);
  const t = await getTranslations();

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

  // Phase 1.B — ambient Day-1 walkthrough. The server fetches state +
  // script; if the overlay should open (neither completed nor
  // dismissed), we render it above the stream. Swallowing errors keeps
  // the main page loading even if the onboarding endpoint is down.
  let onboarding: OnboardingWalkthroughResponse | null = null;
  try {
    onboarding = await serverFetch<OnboardingWalkthroughResponse>(
      `/api/projects/${id}/onboarding/walkthrough`,
    );
  } catch {
    onboarding = null;
  }
  const shouldShowOverlay =
    onboarding !== null &&
    !onboarding.state.walkthrough_completed_at &&
    !onboarding.state.dismissed;

  return (
    <>
      {shouldShowOverlay && onboarding ? (
        <OnboardingOverlay
          projectId={id}
          walkthrough={onboarding.walkthrough}
          initialState={onboarding.state}
        />
      ) : null}
      <StreamCompactToolbar
        title={t("personal.title")}
        // Project title was here as "Edge · {title}" — but it's already
        // shown in the Topbar breadcrumb AND the ProjectBar row above
        // this toolbar, so the third copy adds visual noise before the
        // actual stream. Show meta only on the empty-state path where
        // there's no project context.
        meta={state?.project?.title ? null : t("personal.subtitle")}
        actions={
          // Scope pills moved to the global ProjectBar (one canonical
          // place to toggle scope per memory workgraph_next_design_20260428).
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <StreamContextPanel streamKey={`project:${id}:personal`} />
          </div>
        }
      />
      <PersonalStream
        projectId={id}
        currentUserId={user.id}
        members={members}
        projectTitle={state?.project?.title}
        streamKey={`project:${id}:personal`}
      />
    </>
  );
}
