// /decisions/[id] — global decision detail (Phase E.1 URL shell).
//
// Migration source: replaces the deleted
// `/projects/[id]/detail/decisions/[did]` audit route. Per
// `BUILD-v062.md` §"Phase E — Audit URL migration", a decision is
// addressable globally — scope is resolved server-side from the
// decision row itself.
//
// Phase E.1 ships the URL shell only so rewritten links from Part B
// don't 404. The full rendering (proposal body, tally, dissents,
// upstream/downstream lineage) lands in Phase E.2.
//
// API surface (Phase E.2):
//   GET /api/decisions/:id

import { Card, PageHeader, Text } from "@/components/ui";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function DecisionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/decisions/${id}`);

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Decision"
        title="Decision detail"
        subtitle={`Decision · ${id}`}
      />

      <Card title="Coming in Phase E.2">
        <Text variant="body" muted>
          The decision detail surface (proposal body, tally, dissents,
          lineage) lands in Phase E.2. This URL replaces the deleted{" "}
          <code>/projects/[id]/detail/decisions/[did]</code> audit
          route.
        </Text>
      </Card>
    </main>
  );
}
