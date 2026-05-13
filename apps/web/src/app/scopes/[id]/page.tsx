// /scopes/[id] — scope (project) X-ray (Phase E.1 URL shell).
//
// Migration source: replaces the deleted
// `/projects/[id]` landing, `/projects/[id]/status`,
// `/projects/[id]/team`, `/projects/[id]/settings`, and several
// other per-project audit surfaces. The v0.6.2 doctrine is that
// **scope is never a page** — but a read-only X-ray (members,
// recent activity, settings) is allowed as long as it's not the
// primary entry point.
//
// Per `BUILD-v062.md` §"Phase E — Audit URL migration":
//   /projects/[id]           → /scopes/[id]  (this file)
//   /projects/[id]/status    → /scopes/[id]
//   /projects/[id]/team      → /scopes/[id]/members  (Phase E.2)
//   /projects/[id]/settings  → /scopes/[id]/settings (Phase E.2)
//   /projects/[id]/org       → /scopes/[id]?view=org
//   /projects/[id]/skills    → /scopes/[id]?view=skills
//   /projects/[id]/composition → /scopes/[id]?view=composition
//
// Phase E.1 ships the URL shell only so rewritten links from Part B
// don't 404. The full X-ray (members, activity, settings tab) lands
// in Phase E.2.
//
// API surface (Phase E.2):
//   GET /api/scopes/:id
//   GET /api/scopes/:id/members

import { Card, PageHeader, Text } from "@/components/ui";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function ScopeDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/scopes/${id}`);

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Scope"
        title="Scope X-ray"
        subtitle={`Scope · ${id}`}
      />

      <Card title="Coming in Phase E.2">
        <Text variant="body" muted>
          The scope X-ray (members, recent activity, organization
          chart, skills inventory, settings tab) lands in Phase E.2.
          This URL replaces the deleted{" "}
          <code>/projects/[id]/status</code>,{" "}
          <code>/projects/[id]/team</code>,{" "}
          <code>/projects/[id]/settings</code>, and the project
          landing page. Per DESIGN_LOCK invariant #2, the scope is{" "}
          <em>not</em> the primary entry point — this surface stays
          read-only and lives in the audit IA.
        </Text>
      </Card>
    </main>
  );
}
