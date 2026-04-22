// /projects/[id]/meetings — Phase 2.B meeting transcript list + upload.
//
// Server component. Fetches the list server-side, renders the upload
// form (client) above it, and links each row to the detail page. Empty
// state uses <EmptyState> so "no meetings uploaded yet" matches the
// rest of the app.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { UploadForm } from "@/components/meetings/UploadForm";
import { Card, EmptyState, Heading, Text } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

interface MeetingListItem {
  id: string;
  project_id: string;
  uploader_user_id: string | null;
  title: string;
  uploaded_at: string | null;
  metabolism_status: "pending" | "done" | "failed" | string;
  transcript_length: number;
}

interface MeetingListResponse {
  ok: boolean;
  items: MeetingListItem[];
  count: number;
}

export default async function MeetingsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}/meetings`);
  const t = await getTranslations("meeting");

  let items: MeetingListItem[] = [];
  let errorMessage: string | null = null;
  try {
    const res = await serverFetch<MeetingListResponse>(
      `/api/projects/${id}/meetings`,
    );
    items = res.items ?? [];
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      items = [];
    } else if (err instanceof ApiError && err.status === 403) {
      errorMessage = t("forbidden");
    } else {
      errorMessage = err instanceof Error ? err.message : "failed";
    }
  }

  return (
    <main style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <header
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}
      >
        <Heading level={2}>{t("title")}</Heading>
        <Text variant="body" muted>
          {t("subtitle")}
        </Text>
      </header>

      {errorMessage ? (
        <Card accent="terracotta">
          <Text variant="caption">{errorMessage}</Text>
        </Card>
      ) : (
        <>
          <Card title={t("uploadHeading")}>
            <UploadForm projectId={id} />
          </Card>

          <Card title={t("listHeading")} subtitle={String(items.length)}>
            {items.length === 0 ? (
              <EmptyState>{t("listEmpty")}</EmptyState>
            ) : (
              <ul
                style={{
                  listStyle: "none",
                  margin: 0,
                  padding: 0,
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                {items.map((item) => (
                  <li key={item.id}>
                    <Link
                      href={`/projects/${id}/meetings/${item.id}`}
                      style={{
                        display: "flex",
                        alignItems: "baseline",
                        justifyContent: "space-between",
                        gap: 12,
                        padding: "10px 12px",
                        border: "1px solid var(--wg-line)",
                        borderRadius: "var(--wg-radius)",
                        textDecoration: "none",
                        color: "var(--wg-ink)",
                        background: "var(--wg-surface-raised)",
                      }}
                    >
                      <span
                        style={{
                          display: "flex",
                          flexDirection: "column",
                          gap: 2,
                          minWidth: 0,
                        }}
                      >
                        <Text variant="body">
                          {item.title || t("untitled")}
                        </Text>
                        <Text variant="caption" muted>
                          {item.uploaded_at
                            ? new Date(item.uploaded_at).toLocaleString()
                            : ""}{" "}
                          · {item.transcript_length} {t("chars")}
                        </Text>
                      </span>
                      <StatusPill status={item.metabolism_status} t={t} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </main>
  );
}

function StatusPill({
  status,
  t,
}: {
  status: string;
  t: Awaited<ReturnType<typeof getTranslations<"meeting">>>;
}) {
  const color =
    status === "done"
      ? "var(--wg-ok)"
      : status === "failed"
        ? "var(--wg-accent)"
        : "var(--wg-ink-soft)";
  const label =
    status === "done"
      ? t("statusDone")
      : status === "failed"
        ? t("statusFailed")
        : t("statusPending");
  return (
    <span
      style={{
        padding: "2px 8px",
        fontSize: 11,
        fontFamily: "var(--wg-font-mono)",
        border: `1px solid ${color}`,
        color,
        borderRadius: 10,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}
