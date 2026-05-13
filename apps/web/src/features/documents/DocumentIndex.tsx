"use client";

// DocumentIndex — grid of DocumentCard with Project Brief pinned at
// the top. Doctrine (DESIGN_LOCK §"Locked IA"): Project Brief is a
// pinned KB document, not a separate page.
//
// Phase RW-8 (2026-05-13): MOCK_DOCUMENTS + useDocuments() are
// gone. The /docs page does a server-side fetch and passes the
// real list in as a prop.

import { useTranslations } from "next-intl";

import { EmptyState, Text } from "@/components/ui";

import { DocumentCard } from "./DocumentCard";
import type { Document } from "./types";

export function DocumentIndex({ docs }: { docs: Document[] }) {
  const t = useTranslations("shellV062.docs.index");

  if (docs.length === 0) {
    return <EmptyState>{t("empty")}</EmptyState>;
  }

  const briefs = docs.filter((d) => d.is_project_brief);
  const rest = docs
    .filter((d) => !d.is_project_brief)
    .sort((a, b) => {
      const at = a.updated_at ?? "";
      const bt = b.updated_at ?? "";
      return at < bt ? 1 : -1;
    });
  const ordered = [...briefs, ...rest];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {briefs.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <Text
            variant="caption"
            muted
            style={{
              textTransform: "uppercase",
              letterSpacing: "0.08em",
            }}
          >
            {t("pinnedLabel")}
          </Text>
        </div>
      ) : null}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 12,
        }}
      >
        {ordered.map((doc) => (
          <DocumentCard key={doc.document_id} doc={doc} />
        ))}
      </div>
    </div>
  );
}
