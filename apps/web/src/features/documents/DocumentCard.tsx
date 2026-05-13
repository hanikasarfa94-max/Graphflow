"use client";

// DocumentCard — one row in the DocumentIndex grid.
//
// Phase RW-8 (2026-05-13): renders only the truthful fields the BE
// emits today. The Phase D scaffold rendered an invented
// `scope_label`, a fabricated `kind` chip, an `attachment_hint`
// string, and a synthesized `author.display_name` byline — all
// removed.

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Card, Tag, Text } from "@/components/ui";
import { formatIso } from "@/lib/time";

import { ProjectBriefBadge } from "./ProjectBriefBadge";
import type { Document } from "./types";

export function DocumentCard({ doc }: { doc: Document }) {
  const t = useTranslations("shellV062.docs.card");
  const href = `/docs/${encodeURIComponent(doc.document_id)}`;

  return (
    <Link
      href={href}
      style={{ textDecoration: "none", display: "block" }}
    >
      <Card
        accent={doc.is_project_brief ? "accent" : null}
        style={{
          cursor: "pointer",
          transition: "border-color var(--wg-dur-short) var(--wg-ease-enter)",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
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
            {doc.status === "draft" ? (
              <Tag tone="amber">{t("draft")}</Tag>
            ) : doc.status === "archived" ? (
              <Tag tone="neutral">{t("archived")}</Tag>
            ) : null}
          </div>

          <Text
            as="div"
            variant="body"
            style={{
              fontSize: "var(--wg-fs-h3)",
              fontWeight: 600,
              color: "var(--wg-ink)",
              lineHeight: "var(--wg-lh-tight)",
            }}
          >
            {doc.title}
          </Text>

          {doc.owner_user_id ? (
            <Text variant="caption" muted>
              {t("ownerLabel")} user:{doc.owner_user_id.slice(0, 8)}
              {doc.updated_at ? (
                <>
                  {" · "}
                  {t("editedLabel")} {formatIso(doc.updated_at)}
                </>
              ) : null}
            </Text>
          ) : doc.updated_at ? (
            <Text variant="caption" muted>
              {t("editedLabel")} {formatIso(doc.updated_at)}
            </Text>
          ) : null}
        </div>
      </Card>
    </Link>
  );
}
