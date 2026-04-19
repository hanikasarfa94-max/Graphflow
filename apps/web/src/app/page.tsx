import { ActiveSection } from "@/components/home/ActiveSection";
import { ApprovalsSection } from "@/components/home/ApprovalsSection";
import { loadHomeData } from "@/components/home/data";
import { DMsSection } from "@/components/home/DMsSection";
import { HomeHeader } from "@/components/home/HomeHeader";
import { PendingSection } from "@/components/home/PendingSection";
import { ProjectsSection } from "@/components/home/ProjectsSection";
import { requireUser } from "@/lib/auth";

// `/` — personal home. Phase F of the chat-centered surface.
//
// Unauthenticated users are redirected to /login by requireUser. Logged-in
// users see (vertically):
//   1. Header strip (welcome + language + sign-out)
//   2. Needs-your-response — pending signals across all project streams
//   3. Gated approvals — placeholder for admin-tier users (v2 routing)
//   4. Active task context — the "quiet period" UX (north-star §"Quiet
//      period — corrected framing"): home is never empty.
//   5. Your projects — with unread badges + "+ new project" modal
//   6. Messages — 1:1 DM streams
//
// Data is composed server-side from the existing backend primitives. See
// components/home/data.ts for the aggregation contract.
export const dynamic = "force-dynamic";

export default async function Home() {
  const user = await requireUser("/");
  const data = await loadHomeData(user);

  return (
    <main
      style={{
        maxWidth: 860,
        margin: "0 auto",
        padding: "56px 24px 80px",
      }}
    >
      <HomeHeader displayName={user.display_name} />

      <PendingSection pending={data.pending} />

      {data.is_admin_anywhere ? <ApprovalsSection /> : null}

      <ActiveSection active={data.active} />

      <ProjectsSection projects={data.projects} />

      <DMsSection dms={data.dms} />
    </main>
  );
}
