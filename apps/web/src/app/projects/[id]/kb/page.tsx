// /projects/[id]/kb — Phase Q.6 browseable KB.
//
// This page ships alongside Phase Q-A's backend endpoints. If the list
// endpoint returns 404 (Q-A still in flight), we render a "coming soon"
// empty-state rather than crashing. Any other transport failure falls
// through to the same empty state with the raw error surfaced at the
// top for debugging. Successful responses pass items to <KbList>, which
// owns the search/filter interactivity from the client.

import { getLocale, getTranslations } from "next-intl/server";

import { KbList } from "@/components/kb/KbList";
import { ApiError, type KbItem } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function KbPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}/kb`);
  const t = await getTranslations();
  const locale = await getLocale();

  let items: KbItem[] = [];
  let backendMissing = false;
  let errorMessage: string | null = null;
  try {
    const res = await serverFetch<{ items: KbItem[] }>(
      `/api/projects/${id}/kb?limit=100`,
    );
    // Wiki pages are ingested twice (EN + ZH) with lang:en / lang:zh tags
    // so the same page shows in the viewer's language only. Non-wiki items
    // (membrane ingests, pasted docs) pass through untouched.
    const localeTag = `lang:${locale}`;
    items = (res.items ?? []).filter((item) => {
      if (item.source_kind !== "wiki") return true;
      return (item.tags ?? []).includes(localeTag);
    });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      backendMissing = true;
    } else {
      errorMessage = err instanceof Error ? err.message : "failed";
    }
  }

  return (
    <main>
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 20,
          flexWrap: "wrap",
        }}
      >
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
          {t("kb.title")}
        </h1>
      </header>

      {backendMissing ? (
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
          {t("kb.notAvailable")}
        </div>
      ) : (
        <>
          {errorMessage ? (
            <div
              role="alert"
              style={{
                padding: 12,
                marginBottom: 12,
                color: "var(--wg-accent)",
                fontFamily: "var(--wg-font-mono)",
                fontSize: 13,
                border: "1px solid var(--wg-accent)",
                borderRadius: "var(--wg-radius)",
              }}
            >
              {errorMessage}
            </div>
          ) : null}
          <KbList projectId={id} initialItems={items} />
        </>
      )}
    </main>
  );
}
