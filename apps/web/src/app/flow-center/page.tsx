// /flow-center — Flow Center, the doctrine-load-bearing surface.
//
// Phase RW-2.1 wiring (2026-05-13): server-side fetches the active
// scope + flow packets for that scope and passes them as props to
// <FlowCenter />. No client mocks remain on the read path.
//
// Active scope comes from GET /api/user/active-scope (Phase B.1 live
// endpoint, JSON-blob on UserRow.profile). When no scope is selected
// (no_focus / all_accessible / empty), FlowCenter renders an empty
// state with a "pick a scope" hint. Cross-scope aggregation is a
// follow-up — the read endpoint is scope-bound today.
//
// API surface:
//   GET /api/user/active-scope          ← live (RW-2.1 read uses)
//   GET /api/flow-requests?scope_id=…   ← live (RW-2.1)
//   POST /api/flow-requests/draft       ← Phase B.3 stub (mutation, RW-3)
//   POST /api/flow-requests/:id/respond ← Phase B.3 stub (mutation, RW-3)

import { FlowCenter } from "@/features/flow-center/FlowCenter";
import type { FlowListResponse } from "@/features/flow-center/types";
import { requireUser, serverFetch } from "@/lib/auth";
import type { ActiveScope } from "@/lib/api";

export const dynamic = "force-dynamic";

async function loadActiveScope(): Promise<ActiveScope> {
  try {
    return await serverFetch<ActiveScope>("/api/user/active-scope");
  } catch {
    return { scope_id: null, scope_mode: "no_focus", updated_at: null };
  }
}

async function loadFlows(scope_id: string): Promise<FlowListResponse> {
  try {
    return await serverFetch<FlowListResponse>(
      `/api/flow-requests?scope_id=${encodeURIComponent(scope_id)}`,
    );
  } catch {
    return { packets: [], participants: {} };
  }
}

export default async function FlowCenterPage() {
  const user = await requireUser("/flow-center");
  const active = await loadActiveScope();
  // Only fetch packets when there's a concrete scope to bind to —
  // /api/flow-requests requires scope_id.
  const activeScopeId =
    active.scope_mode === "current_focus" && active.scope_id
      ? active.scope_id
      : null;
  const data = activeScopeId
    ? await loadFlows(activeScopeId)
    : { packets: [], participants: {} };
  return (
    <FlowCenter
      data={data}
      activeScopeId={activeScopeId}
      userId={user.id}
    />
  );
}
