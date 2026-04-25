import { Suspense } from "react";

import { ActiveSection } from "@/components/home/ActiveSection";
import { ApprovalsSection } from "@/components/home/ApprovalsSection";
import { loadHomeData } from "@/components/home/data";
import { DMsSection } from "@/components/home/DMsSection";
import { HomeHeader } from "@/components/home/HomeHeader";
import { PendingSection } from "@/components/home/PendingSection";
import { ProjectsSection } from "@/components/home/ProjectsSection";
import { PublicSplit } from "@/components/public/PublicSplit";
import { optionalUser } from "@/lib/auth";
// Migration note: the home `<main>` intentionally keeps one inline style
// — it's a one-shot layout container (max-width + page padding) and
// wrapping it in a primitive would add a file for ~3 props. Every
// descendant section now uses the `Card` / `Heading` / `Text` / `Button`
// primitives; see components/home/*.

import { LoginForm } from "./login/LoginForm";

// `/` has two modes:
//   - Logged out: public split (morphing-graph demo + inline login).
//   - Logged in:  personal home (Phase F of the chat-centered surface).
//
// Logged-in sections (vertically):
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
  const user = await optionalUser();

  if (!user) {
    return (
      <PublicSplit>
        <Suspense fallback={null}>
          <LoginForm />
        </Suspense>
      </PublicSplit>
    );
  }

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

      {data.is_admin_anywhere ? (
        <ApprovalsSection projects={data.projects} />
      ) : null}

      <ActiveSection active={data.active} />

      <ProjectsSection projects={data.projects} />

      <DMsSection dms={data.dms} />
    </main>
  );
}
