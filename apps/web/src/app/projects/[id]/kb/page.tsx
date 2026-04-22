// /projects/[id]/kb — Phase 3.A tree browser.
//
// Server component. Fetches the tree payload + /state (for role/tier)
// and hands both to KbTreeBrowser. When the tree endpoint 404s (the
// pre-3.A flat backend is still active, or a mis-deployed build is in
// the loop) we gracefully fall back to the "coming soon" empty state
// instead of crashing.

import { Heading } from "@/components/ui";
import { KbTreeBrowser } from "@/components/kb/KbTreeBrowser";
import {
  ApiError,
  getKbTree,
  type KbTreeResponse,
  type ProjectState,
} from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";
import { getTranslations } from "next-intl/server";

export const dynamic = "force-dynamic";

type Role = "owner" | "member" | "observer";
type Tier = "full" | "task_scoped" | "observer";

export default async function KbPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const user = await requireUser(`/projects/${id}/kb`);
  const t = await getTranslations();

  let tree: KbTreeResponse | null = null;
  let backendMissing = false;
  let errorMessage: string | null = null;
  try {
    tree = await serverFetch<KbTreeResponse>(
      `/api/projects/${id}/kb/tree`,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      backendMissing = true;
    } else {
      errorMessage = err instanceof Error ? err.message : "failed";
    }
  }

  // Pull /state for the viewer's role + license tier. The tree
  // browser gates "New folder" (full-tier) + reparent/delete (owner)
  // on these values. If /state fails we degrade to member/full — the
  // backend still enforces every write regardless of what the UI
  // thinks.
  let role: Role = "member";
  let tier: Tier = "full";
  try {
    const state = await serverFetch<ProjectState>(
      `/api/projects/${id}/state`,
    );
    tier = (state.viewer_license_tier ?? "full") as Tier;
    const me = state.members.find((m) => m.user_id === user.id);
    if (me) {
      role = (me.role as Role) ?? "member";
    }
  } catch {
    // Non-fatal — the browser will fall back to restricted UX and
    // the backend still enforces writes.
  }

  return (
    <main>
      <header style={{ marginBottom: 16 }}>
        <Heading level={1}>{t("kb.title")}</Heading>
      </header>
      {backendMissing || tree === null ? (
        <div
          style={{
            padding: "24px 16px",
            color: "var(--wg-ink-soft)",
            fontSize: 13,
            textAlign: "center",
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            background: "#fff",
          }}
        >
          {errorMessage ?? t("kb.notAvailable")}
        </div>
      ) : (
        <KbTreeBrowser
          projectId={id}
          initialTree={tree}
          role={role}
          tier={tier}
        />
      )}
    </main>
  );
}
