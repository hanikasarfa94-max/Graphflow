// /projects/[id]/detail/decisions — audit list of crystallized decisions.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { ProjectState } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function DecisionsPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}/detail/decisions`);
  const t = await getTranslations();
  let state: ProjectState | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch {
    state = null;
  }
  const decisions = state?.decisions ?? [];
  return (
    <div>
      <h2
        style={{
          fontSize: 16,
          fontWeight: 600,
          margin: "0 0 12px",
          color: "var(--wg-ink)",
        }}
      >
        {t("detail.decisions.title")} · {decisions.length}
      </h2>
      {decisions.length === 0 ? (
        <div
          style={{
            padding: 16,
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            color: "var(--wg-ink-faint)",
            fontSize: 13,
          }}
        >
          {t("detail.decisions.empty")}
        </div>
      ) : (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: 0,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          {decisions.map((d) => (
            <li
              key={d.id}
              style={{
                border: "1px solid var(--wg-line)",
                borderRadius: "var(--wg-radius)",
                background: "#fff",
                padding: "14px 16px",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                  gap: 12,
                }}
              >
                <div
                  style={{
                    fontSize: 11,
                    fontFamily: "var(--wg-font-mono)",
                    color: "var(--wg-accent)",
                    textTransform: "uppercase",
                  }}
                >
                  ⚡ {d.apply_outcome}
                </div>
                <div
                  style={{
                    fontSize: 11,
                    fontFamily: "var(--wg-font-mono)",
                    color: "var(--wg-ink-faint)",
                  }}
                >
                  {d.created_at
                    ? new Date(d.created_at).toLocaleString()
                    : "—"}
                </div>
              </div>
              <div
                style={{
                  fontSize: 14,
                  color: "var(--wg-ink)",
                  margin: "6px 0 6px",
                  whiteSpace: "pre-wrap",
                }}
              >
                {d.rationale || d.custom_text || "—"}
              </div>
              <Link
                href={`/projects/${id}/nodes/${d.id}`}
                style={{
                  fontSize: 11,
                  fontFamily: "var(--wg-font-mono)",
                  color: "var(--wg-accent)",
                  textDecoration: "none",
                }}
              >
                {t("detail.decisions.viewLineage")} →
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
