// /kb-items/[id] — global KB item detail (Phase E.1 URL shell).
//
// Migration source: replaces the deleted
// `/projects/[id]/kb/[kid]` audit route. KB items are global per
// v0.6.2 IA — addressable directly without a project prefix.
//
// Phase E.1 ships the URL shell only so rewritten links from Part B
// don't 404. The full <KbItemDetail /> render (already implemented
// for the legacy route) gets re-mounted here in Phase E.2 with
// scope_id read from the item row instead of the URL.
//
// API surface (Phase E.2):
//   GET /api/kb-items/:id

import { Card, PageHeader, Text } from "@/components/ui";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function KbItemDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/kb-items/${id}`);

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="KB item"
        title="Knowledge entry"
        subtitle={`KB item · ${id}`}
      />

      <Card title="Coming in Phase E.2">
        <Text variant="body" muted>
          The KB entry detail surface (body, citations, license, edit
          history) lands in Phase E.2. This URL replaces the deleted{" "}
          <code>/projects/[id]/kb/[kid]</code> route. The existing{" "}
          <code>KbItemDetail</code> client component will be re-mounted
          here once the loader resolves <code>scope_id</code> from the
          item row.
        </Text>
      </Card>
    </main>
  );
}
