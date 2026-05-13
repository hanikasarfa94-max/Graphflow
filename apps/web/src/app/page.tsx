// `/` — root route after the v0.6.2 pivot.
//
// Two modes:
//   * Logged out: public split (morphing-graph demo + inline login).
//   * Logged in:  redirect to /my-ai per the v0.6.2 IA. The landing
//                 surface is the user's private AI conversation; the
//                 cross-project home dashboard is gone (its work moved
//                 into /my-ai's grounded greeting + /conversations'
//                 recent + /flow-center's needs-me bucket).
//
// INVARIANT_TESTS.md §"Project not routable as page" applies one step
// up — every /projects/* route 404s. This file controls only /.

import { Suspense } from "react";
import { redirect } from "next/navigation";

import { PublicSplit } from "@/components/public/PublicSplit";
import { optionalUser } from "@/lib/auth";

import { LoginForm } from "./login/LoginForm";

export const dynamic = "force-dynamic";

export default async function Root() {
  const user = await optionalUser();

  if (user) {
    redirect("/my-ai");
  }

  return (
    <PublicSplit>
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </PublicSplit>
  );
}
