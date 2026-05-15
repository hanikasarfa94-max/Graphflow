// /my-ai — primary landing for v0.6.2.
//
// Server component. Fetches landing data + active scope, hands them
// to MyAILandingClient which owns the landing-vs-active visibility
// state. The composer behavior is unchanged — POST /api/my-ai/messages
// still runs inside MyAIComposer.
//
// API surface (read-only on this page):
//   GET /api/user/active-scope
//   GET /api/my-ai/landing?scope_id=...
//   GET /api/projects                    (fallback when active-scope is null)

import { MyAILandingClient } from "@/features/my-ai/MyAILandingClient";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

type GroundedItem = {
  id: string;
  kind: string;
  title: string;
  scope_id: string | null;
  object_url: string | null;
};

type ShareableDraft = {
  id: string;
  title: string;
  target_scope_id: string | null;
  target_user_id: string | null;
};

type MyAILandingResponse = {
  grounded_items: GroundedItem[];
  ready_to_share: ShareableDraft[];
  scope_id: string | null;
};

type ActiveScope = {
  scope_id: string | null;
  scope_mode: "current_focus" | "all_accessible" | "no_focus";
};

type ProjectSummary = { id: string; title: string; role: string };

async function loadLanding(): Promise<MyAILandingResponse> {
  // Tolerant: a transient API failure on the landing should not
  // crash the surface — render the empty state instead.
  try {
    return await serverFetch<MyAILandingResponse>("/api/my-ai/landing");
  } catch {
    return { grounded_items: [], ready_to_share: [], scope_id: null };
  }
}

async function loadActiveScope(): Promise<ActiveScope> {
  try {
    return await serverFetch<ActiveScope>("/api/user/active-scope");
  } catch {
    return { scope_id: null, scope_mode: "no_focus" };
  }
}

async function loadFirstProjectId(): Promise<string | null> {
  // Fallback when /api/user/active-scope returns scope_id=null.
  // The composer needs SOME scope to post to. We skip the
  // auto-generated "Welcome to graphflow" tutorial.
  try {
    const projects = await serverFetch<
      ProjectSummary[] | { projects: ProjectSummary[] }
    >("/api/projects");
    const list = Array.isArray(projects)
      ? projects
      : (projects as { projects: ProjectSummary[] }).projects || [];
    const nonTutorial = list.find(
      (p) => !/welcome to graphflow/i.test(p.title || ""),
    );
    return nonTutorial?.id || list[0]?.id || null;
  } catch {
    return null;
  }
}

export default async function MyAILandingPage() {
  const user = await requireUser("/my-ai");
  const [data, active] = await Promise.all([loadLanding(), loadActiveScope()]);
  let scopeId: string | null =
    active.scope_mode === "current_focus" && active.scope_id
      ? active.scope_id
      : null;
  if (!scopeId) {
    scopeId = await loadFirstProjectId();
  }

  return (
    <MyAILandingClient
      displayName={user.display_name || user.username}
      scopeId={scopeId}
      groundedItems={data.grounded_items}
      readyToShare={data.ready_to_share}
    />
  );
}
