"use client";

// DocumentDetail — read-only viewer for /docs/[id].
//
// Phase RW-8 (2026-05-13): the mock useDocument() hook is gone, the
// inline view/edit toggle is gone, and DocumentEditor.tsx is
// deleted. The brief is explicit: no document mutation behavior in
// this slice, no publish exposed from the FE.

import { useTranslations } from "next-intl";

import { Card, PageHeader, Tag, Text } from "@/components/ui";
import { formatIso } from "@/lib/time";

import { DocumentRightRail } from "./DocumentRightRail";
import { ProjectBriefBadge } from "./ProjectBriefBadge";
import type { DocumentDetail as DocumentDetailType } from "./types";

export function DocumentDetail({ doc }: { doc: DocumentDetailType }) {
  const t = useTranslations("shellV062.docs.detail");

  return (
    <main
      style={{
        maxWidth: 1280,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker={t("kicker")}
        title={doc.title}
        subtitle={doc.is_project_brief ? t("subtitleBrief") : t("subtitleDoc")}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) 320px",
          gap: 20,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <article
            style={{ display: "flex", flexDirection: "column", gap: 16 }}
          >
            <div
              style={{
                display: "flex",
                gap: 6,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              {doc.is_project_brief ? <ProjectBriefBadge /> : null}
              {doc.scope_id ? (
                <Tag tone="neutral">{doc.scope_id.slice(0, 8)}</Tag>
              ) : null}
              <Tag tone={doc.scope === "personal" ? "neutral" : "accent"}>
                {doc.scope}
              </Tag>
              <Tag
                tone={
                  doc.status === "draft"
                    ? "amber"
                    : doc.status === "archived"
                      ? "neutral"
                      : "ok"
                }
              >
                {doc.status}
              </Tag>
              {doc.owner_user_id ? (
                <Text variant="caption" muted>
                  {t("ownerLabel")} user:{doc.owner_user_id.slice(0, 8)}
                </Text>
              ) : null}
              {doc.updated_at ? (
                <Text variant="caption" muted>
                  {t("editedLabel")} {formatIso(doc.updated_at)}
                </Text>
              ) : null}
            </div>

            <Card>
              {doc.content_md ? (
                <pre
                  style={{
                    whiteSpace: "pre-wrap",
                    fontFamily: "var(--wg-font-sans)",
                    fontSize: "var(--wg-fs-body)",
                    lineHeight: "var(--wg-lh-normal)",
                    color: "var(--wg-ink)",
                    margin: 0,
                  }}
                >
                  {doc.content_md}
                </pre>
              ) : (
                <Text variant="caption" muted>
                  {t("noBody")}
                </Text>
              )}
            </Card>

            {doc.attachment ? (
              <Card title={t("attachmentTitle")}>
                <a
                  href={doc.attachment.download_url}
                  style={{
                    color: "var(--wg-accent)",
                    textDecoration: "none",
                  }}
                >
                  {doc.attachment.filename} →
                </a>
                {doc.attachment.mime ? (
                  <Text variant="caption" muted>
                    {" "}· {doc.attachment.mime}
                  </Text>
                ) : null}
              </Card>
            ) : null}

            <Card variant="sunk">
              <Text variant="caption" muted>
                {t("notWired")}
              </Text>
            </Card>

            <Text
              as="p"
              variant="caption"
              muted
              style={{ marginTop: 8, textAlign: "center" }}
            >
              {t("doctrine")}
            </Text>
          </article>
        </div>

        <DocumentRightRail doc={doc} />
      </div>
    </main>
  );
}
