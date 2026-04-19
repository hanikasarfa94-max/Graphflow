// /projects/[id]/kb/[itemId] — Phase Q.6 KB detail.
//
// Server component. 404 on the item endpoint = item doesn't exist or
// backend hasn't shipped detail routes yet; either way, we render a
// graceful message and keep the "back to KB" link working.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { KbItemDetail } from "@/components/kb/KbItemDetail";
import { ApiError, type KbItemDetail as KbItemDetailT } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function KbItemPage({
  params,
}: {
  params: Promise<{ id: string; itemId: string }>;
}) {
  const { id, itemId } = await params;
  await requireUser(`/projects/${id}/kb/${itemId}`);
  const t = await getTranslations();

  let item: KbItemDetailT | null = null;
  let errorMessage: string | null = null;
  let notFound = false;
  try {
    item = await serverFetch<KbItemDetailT>(
      `/api/projects/${id}/kb/${itemId}`,
    );
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound = true;
    } else {
      errorMessage = err instanceof Error ? err.message : "failed";
    }
  }

  if (!item) {
    return (
      <main>
        <div style={{ marginBottom: 16 }}>
          <Link
            href={`/projects/${id}/kb`}
            style={{
              fontSize: 12,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              textDecoration: "none",
            }}
          >
            {t("kb.item.back")}
          </Link>
        </div>
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
          {notFound ? t("kb.empty") : (errorMessage ?? t("kb.notAvailable"))}
        </div>
      </main>
    );
  }

  return (
    <main>
      <KbItemDetail projectId={id} item={item} />
    </main>
  );
}
