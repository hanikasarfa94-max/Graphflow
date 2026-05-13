// /nodes/[id] — global node detail surface (Phase E.1 URL shell).
//
// Migration source: replaces the deleted
// `/projects/[id]/nodes/[nid]` audit route. Per
// `BUILD-v062.md` §"Phase E — Audit URL migration", node deep-links
// are now global (no project prefix) — the loader walks the graph
// state to find the originating scope at render time.
//
// Phase E.1 ships the URL shell only so rewritten links from Part B
// don't 404. The full rendering (lineage timeline, decision context,
// scope crumb) lands in Phase E.2.
//
// API surface (Phase E.2):
//   GET /api/nodes/:id

import { Card, PageHeader, Text } from "@/components/ui";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function NodeDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/nodes/${id}`);

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Node"
        title="Node detail"
        subtitle={`Graph node · ${id}`}
      />

      <Card title="Coming in Phase E.2">
        <Text variant="body" muted>
          The graph node detail surface (lineage timeline, decision
          context, citation back-references) lands in Phase E.2. This
          URL replaces the deleted{" "}
          <code>/projects/[id]/nodes/[nid]</code> audit route.
        </Text>
      </Card>
    </main>
  );
}
