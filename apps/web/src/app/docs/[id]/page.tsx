// /docs/[id] — Document reader (read-only).
//
// Phase RW-8 (2026-05-13): server-side fetch against the live
// GET /api/documents/:id endpoint added in this slice. The Phase D
// useDocument mock + inline edit-mode toggle are gone. Publish is
// also absent from the FE per the brief.

import { getTranslations } from "next-intl/server";

import { Card, EmptyState, PageHeader } from "@/components/ui";
import { DocumentDetail } from "@/features/documents/DocumentDetail";
import type { DocumentDetailResponse } from "@/features/documents/types";
import { ApiError } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

async function loadDocument(id: string): Promise<
  | { kind: "ok"; data: DocumentDetailResponse }
  | { kind: "forbidden" }
  | { kind: "not_found" }
  | { kind: "error" }
> {
  try {
    const data = await serverFetch<DocumentDetailResponse>(
      `/api/documents/${encodeURIComponent(id)}`,
    );
    return { kind: "ok", data };
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.status === 403) return { kind: "forbidden" };
      if (err.status === 404) return { kind: "not_found" };
    }
    return { kind: "error" };
  }
}

export default async function DocumentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/docs/${id}`);
  const t = await getTranslations("shellV062.docs.detail");
  const result = await loadDocument(id);

  if (result.kind !== "ok") {
    return (
      <main
        style={{
          maxWidth: 1180,
          margin: "0 auto",
          padding: "32px 28px 80px",
        }}
      >
        <PageHeader
          kicker={t("kicker")}
          title={t("titleFallback")}
          subtitle={t("subtitleDoc")}
        />
        <Card>
          <EmptyState>
            {result.kind === "forbidden"
              ? t("forbidden")
              : result.kind === "not_found"
                ? t("notFound", { id })
                : t("loadError")}
          </EmptyState>
        </Card>
      </main>
    );
  }

  return <DocumentDetail doc={result.data.document} />;
}
