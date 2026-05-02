"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { RelTime } from "@/components/stream/RelTime";
import { Button, EmptyState, Text } from "@/components/ui";

import type { HomeProjectCard } from "./data";
import { NewProjectModal } from "./NewProjectModal";
import { SectionHeader } from "./SectionHeader";

export function ProjectsSection({
  projects,
}: {
  projects: HomeProjectCard[];
}) {
  const t = useTranslations();
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <section style={{ marginBottom: 40 }} aria-labelledby="home-projects">
      <SectionHeader
        title={t("home.projects.title")}
        right={
          <Button
            variant="primary"
            size="md"
            onClick={() => setModalOpen(true)}
          >
            {t("home.projects.newButton")}
          </Button>
        }
      />

      {projects.length === 0 ? (
        <EmptyState>{t("home.projects.empty")}</EmptyState>
      ) : (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          {projects.map((p) => (
            <li key={p.id}>
              <Link
                href={`/projects/${p.id}`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr auto",
                  alignItems: "center",
                  padding: "12px 14px",
                  border: "1px solid var(--wg-line)",
                  borderRadius: "var(--wg-radius)",
                  textDecoration: "none",
                  color: "var(--wg-ink)",
                  background: "var(--wg-surface-raised)",
                  gap: 12,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <Text
                    as="div"
                    variant="body"
                    style={{
                      fontWeight: 600,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {p.title}
                  </Text>
                  <Text
                    as="div"
                    variant="caption"
                    style={{
                      color: "var(--wg-ink-faint)",
                      marginTop: 2,
                    }}
                  >
                    {p.role}
                    {p.last_activity_at && (
                      <>
                        {" · "}
                        <RelTime iso={p.last_activity_at} />
                      </>
                    )}
                  </Text>
                </div>
                {p.unread_count > 0 ? (
                  <span
                    style={{
                      background: "var(--wg-accent)",
                      color: "var(--wg-surface-raised)",
                      fontSize: "var(--wg-fs-caption)",
                      fontFamily: "var(--wg-font-mono)",
                      padding: "2px 8px",
                      borderRadius: 999,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {t("home.unread.count", { count: p.unread_count })}
                  </span>
                ) : null}
              </Link>
            </li>
          ))}
        </ul>
      )}

      <NewProjectModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </section>
  );
}
