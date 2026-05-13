"use client";

// Documents — page body for /docs. PageHeader + type filter strip +
// DocumentIndex.
//
// Phase RW-8 (2026-05-13): receives all docs from the server page
// (one fetch with type=all) and applies the type filter client-side.
// The BE's type filter only honors 'brief' today; the FE filter is
// honest about what the BE actually distinguishes.

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Card, PageHeader, Text } from "@/components/ui";

import { DocumentIndex } from "./DocumentIndex";
import type { Document, DocumentTypeFilter } from "./types";

const FILTERS: DocumentTypeFilter[] = ["all", "brief"];

export function Documents({
  docs,
  scopeId,
}: {
  docs: Document[];
  scopeId: string | null;
}) {
  const t = useTranslations("shellV062.docs.page");
  const [filter, setFilter] = useState<DocumentTypeFilter>("all");

  const visible = useMemo(() => {
    if (filter === "brief") return docs.filter((d) => d.is_project_brief);
    return docs;
  }, [docs, filter]);

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

      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 20,
          flexWrap: "wrap",
        }}
      >
        {FILTERS.map((f) => (
          <Button
            key={f}
            size="sm"
            variant={filter === f ? "primary" : "ghost"}
            onClick={() => setFilter(f)}
          >
            {t(`filters.${f}` as const)}
          </Button>
        ))}
        <div
          style={{
            marginLeft: "auto",
            display: "flex",
            alignItems: "center",
          }}
        >
          <Text variant="caption" muted>
            {scopeId
              ? t("scopeLabel", { scope: scopeId.slice(0, 8) })
              : t("noScope")}
          </Text>
        </div>
      </div>

      <Card title={t("listTitle")} flush>
        <div style={{ padding: 16 }}>
          <DocumentIndex docs={visible} />
        </div>
      </Card>

      <Text
        as="p"
        variant="caption"
        muted
        style={{ marginTop: 16, textAlign: "center" }}
      >
        {t("doctrine")}
      </Text>
    </main>
  );
}
