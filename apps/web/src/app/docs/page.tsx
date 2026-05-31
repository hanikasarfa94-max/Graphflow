// /docs — Documents / KB index.
//
// Phase RW-8 (2026-05-13): server-side fetch against the live
// GET /api/documents endpoint. Active scope sourced from
// /api/user/active-scope. If the user has no concrete scope, an
// honest empty state renders — the BE requires scope_id today.

import { getTranslations } from "next-intl/server";

import { Card, EmptyState, PageHeader } from "@/components/ui";
import { Documents } from "@/features/documents/Documents";
import type { DocumentListResponse } from "@/features/documents/types";
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

async function loadDocuments(
  scope_id: string,
): Promise<DocumentListResponse> {
  try {
    return await serverFetch<DocumentListResponse>(
      `/api/documents?scope_id=${encodeURIComponent(scope_id)}&type=all`,
    );
  } catch {
    return { documents: [], scope_id, type: "all" };
  }
}

export default async function DocsIndexPage() {
  await requireUser("/docs");
  const active = await loadActiveScope();
  const scopeId =
    active.scope_mode === "current_focus" && active.scope_id
      ? active.scope_id
      : null;

  if (!scopeId) {
    const t = await getTranslations("shellV062.docs.page");
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
          title={t("title")}
          subtitle={t("subtitle")}
        />
        <Card>
          <EmptyState>{t("needScope")}</EmptyState>
        </Card>
      </main>
    );
  }

  const data = await loadDocuments(scopeId);
  return <Documents docs={data.documents} scopeId={scopeId} />;
}
