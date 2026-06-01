// /kb-items/[id] — KB item read-only proof page.
//
// Phase RW-6 (2026-05-13): the Phase E.1 placeholder is replaced
// with a real read-only body backed by the live
// GET /api/kb-items/:id endpoint that was already shipped.
//
// Renders the truthful fields the BE actually exposes today —
// title, scope, status (draft/published/archived/...), owner,
// content body, attachment + download link if present, and
// timestamps. No mutation. No fabricated lineage.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Card, EmptyState, PageHeader, Tag, Text } from "@/components/ui";
import { ApiError, type KbNote, type KbNoteAttachment } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

// C1-C dedup: GET /api/kb-items/{id} is generated-backed as KbNote; this page's
// local KbItemDetail/KbAttachment duplicated that exact shape. Alias onto the
// canonical types (content_md/source are non-null in the wire truth; the page
// already reads them null-tolerantly, so the narrowing is safe).
type KbAttachment = KbNoteAttachment;
type KbItemDetail = KbNote;

async function loadKbItem(
  id: string,
): Promise<
  | { kind: "ok"; data: KbItemDetail }
  | { kind: "forbidden" }
  | { kind: "not_found" }
  | { kind: "error" }
> {
  try {
    const data = await serverFetch<KbItemDetail>(
      `/api/kb-items/${encodeURIComponent(id)}`,
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

const STATUS_TONE: Record<string, "neutral" | "accent" | "ok" | "amber"> = {
  draft: "amber",
  published: "ok",
  archived: "neutral",
  "pending-review": "amber",
  rejected: "neutral",
};

export default async function KbItemDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/kb-items/${id}`);
  const t = await getTranslations("shellV062.kbItems.detail");
  const result = await loadKbItem(id);

  if (result.kind === "forbidden") {
    return <Shell><EmptyState>{t("forbidden")}</EmptyState></Shell>;
  }
  if (result.kind === "not_found") {
    return <Shell><EmptyState>{t("notFound", { id })}</EmptyState></Shell>;
  }
  if (result.kind === "error") {
    return <Shell><EmptyState>{t("loadError")}</EmptyState></Shell>;
  }

  const item = result.data;
  const statusTone = STATUS_TONE[item.status] || "neutral";

  return (
    <Shell>
      <PageHeader
        kicker="KB item"
        title={item.title}
        subtitle={t("subtitle")}
        right={
          <div style={{ display: "flex", gap: 8 }}>
            <Tag tone="neutral">{item.scope}</Tag>
            <Tag tone={statusTone}>{item.status}</Tag>
          </div>
        }
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)",
          gap: 16,
        }}
      >
        <Card title={t("bodyTitle")}>
          {item.content_md ? (
            <Text as="p" variant="body" style={{ whiteSpace: "pre-wrap" }}>
              {item.content_md}
            </Text>
          ) : (
            <EmptyState>{t("noBody")}</EmptyState>
          )}
        </Card>

        <Card title={t("metaTitle")}>
          <Meta label={t("meta.id")} value={item.id} />
          {item.project_id ? (
            <Meta
              label={t("meta.scope")}
              value={
                <Link
                  href={`/scopes/${encodeURIComponent(item.project_id)}`}
                  style={{ color: "var(--wg-accent)" }}
                >
                  {item.project_id.slice(0, 8)} →
                </Link>
              }
            />
          ) : (
            <Meta label={t("meta.scope")} value="—" />
          )}
          <Meta
            label={t("meta.owner")}
            value={
              item.owner_user_id
                ? `user:${item.owner_user_id.slice(0, 8)}`
                : "—"
            }
          />
          <Meta label={t("meta.source")} value={item.source || "—"} />
          <Meta label={t("meta.created")} value={item.created_at || "—"} />
          <Meta label={t("meta.updated")} value={item.updated_at || "—"} />
          {item.attachment ? (
            <Meta
              label={t("meta.attachment")}
              value={
                <a
                  href={item.attachment.download_url}
                  style={{ color: "var(--wg-accent)" }}
                >
                  {item.attachment.filename} →
                </a>
              }
            />
          ) : null}
        </Card>
      </div>

      <Card variant="sunk" style={{ marginTop: 16 }}>
        <Text variant="caption" muted>
          {t("notWired")}
        </Text>
      </Card>
    </Shell>
  );
}

function Meta({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 8,
        marginBottom: 6,
        alignItems: "baseline",
      }}
    >
      <Text
        variant="caption"
        muted
        style={{
          minWidth: 90,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        {label}
      </Text>
      <Text variant="body" as="span">
        {value}
      </Text>
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      {children}
    </main>
  );
}
