"use client";

// DocumentRightRail — read-only spine for /docs/[id].
//
// Phase RW-8 (2026-05-13): the Phase D mock (`useDocumentRightRail`
// + `useAiAssistance`) is gone. The rail now renders only the
// Context section from real document fields. Related Work,
// Evidence, AI Assistance, and Primary Action are all honest empty
// — no backend producer wires those today, and the brief is
// explicit: do not wire publish, do not wire AI assistance.

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Card, EmptyState, Text } from "@/components/ui";
import { formatIso } from "@/lib/time";

import type { Document } from "./types";

export function DocumentRightRail({ doc }: { doc: Document }) {
  const t = useTranslations("shellV062.docs.rightRail");

  return (
    <aside
      aria-label="Document right rail"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 16,
        width: "100%",
      }}
    >
      <Section label={t("context")}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {doc.scope_id ? (
            <Text variant="body">
              {t("scopeLabel")}:{" "}
              <Link
                href={`/scopes/${encodeURIComponent(doc.scope_id)}`}
                style={{ color: "var(--wg-accent)", textDecoration: "none" }}
              >
                {doc.scope_id.slice(0, 8)} →
              </Link>
            </Text>
          ) : (
            <Text variant="caption" muted>
              {t("noScope")}
            </Text>
          )}
          {doc.owner_user_id ? (
            <Text variant="caption" muted>
              {t("ownerLabel")}: user:{doc.owner_user_id.slice(0, 8)}
            </Text>
          ) : null}
          {doc.updated_at ? (
            <Text variant="caption" muted>
              {t("lastEditedLabel")}: {formatIso(doc.updated_at)}
            </Text>
          ) : null}
          {doc.source ? (
            <Text variant="caption" muted>
              {t("sourceLabel")}: {doc.source}
            </Text>
          ) : null}
        </div>
      </Section>

      <Section label={t("relatedWork")}>
        <EmptyState>{t("notWiredRelated")}</EmptyState>
      </Section>

      <Section label={t("evidence")}>
        <EmptyState>{t("notWiredEvidence")}</EmptyState>
      </Section>

      <Section label={t("aiAssistance")}>
        <Card variant="sunk">
          <Text variant="caption" muted>
            {t("notWiredAi")}
          </Text>
        </Card>
      </Section>

      <Section label={t("primaryAction")}>
        <Card variant="sunk">
          <Text variant="caption" muted>
            {t("notWiredPublish")}
          </Text>
        </Card>
      </Section>
    </aside>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Text
        variant="caption"
        muted
        style={{ textTransform: "uppercase", letterSpacing: "0.08em" }}
      >
        {label}
      </Text>
      {children}
    </section>
  );
}
