"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { relativeTime } from "@/components/stream/types";

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
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            style={{
              background: "var(--wg-accent)",
              color: "#fff",
              border: "none",
              borderRadius: "var(--wg-radius)",
              padding: "6px 12px",
              fontSize: 12,
              fontWeight: 600,
              fontFamily: "var(--wg-font-sans)",
              cursor: "pointer",
            }}
          >
            {t("home.projects.newButton")}
          </button>
        }
      />

      {projects.length === 0 ? (
        <div
          style={{
            padding: 16,
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            color: "var(--wg-ink-faint)",
            fontSize: 13,
          }}
        >
          {t("home.projects.empty")}
        </div>
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
                  <div
                    style={{
                      fontWeight: 600,
                      fontSize: 14,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {p.title}
                  </div>
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--wg-ink-faint)",
                      fontFamily: "var(--wg-font-mono)",
                      marginTop: 2,
                    }}
                  >
                    {p.role}
                    {p.last_activity_at
                      ? ` · ${relativeTime(p.last_activity_at)}`
                      : ""}
                  </div>
                </div>
                {p.unread_count > 0 ? (
                  <span
                    style={{
                      background: "var(--wg-accent)",
                      color: "#fff",
                      fontSize: 11,
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
