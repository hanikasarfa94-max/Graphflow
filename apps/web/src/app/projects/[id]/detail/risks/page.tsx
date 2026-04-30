// /projects/[id]/detail/risks — audit list of graph risks.

import { getTranslations } from "next-intl/server";

import type { ProjectState } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

const severityColor: Record<string, string> = {
  critical: "#2563eb",
  high: "#2563eb",
  medium: "#c68a00",
  low: "#5a5a5a",
};

const cell = {
  padding: "10px 12px",
  fontSize: 13,
  borderBottom: "1px solid var(--wg-line)",
};

export default async function RisksPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  await requireUser(`/projects/${id}/detail/risks`);
  const t = await getTranslations();
  let state: ProjectState | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch {
    state = null;
  }
  const risks = state?.graph.risks ?? [];
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
        {t("detail.risks.title")} · {risks.length}
      </h2>
      {risks.length === 0 ? (
        <div
          style={{
            padding: 16,
            border: "1px dashed var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            color: "var(--wg-ink-faint)",
            fontSize: 13,
          }}
        >
          {t("detail.risks.empty")}
        </div>
      ) : (
        <div
          style={{
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius)",
            background: "#fff",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "24px 1fr 100px 110px",
              background: "var(--wg-surface)",
              fontSize: 11,
              fontFamily: "var(--wg-font-mono)",
              color: "var(--wg-ink-soft)",
              textTransform: "uppercase",
            }}
          >
            <div style={{ ...cell, padding: "8px 8px" }}></div>
            <div style={{ ...cell, padding: "8px 12px" }}>
              {t("detail.risks.col.title")}
            </div>
            <div style={{ ...cell, padding: "8px 12px" }}>
              {t("detail.risks.col.severity")}
            </div>
            <div style={{ ...cell, padding: "8px 12px" }}>
              {t("detail.risks.col.status")}
            </div>
          </div>
          {risks.map((r) => (
            <div
              key={r.id}
              style={{
                display: "grid",
                gridTemplateColumns: "24px 1fr 100px 110px",
              }}
            >
              <div style={{ ...cell, padding: "10px 8px" }}>
                <span
                  aria-hidden
                  style={{
                    display: "inline-block",
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: severityColor[r.severity] ?? "#c0c0c0",
                  }}
                />
              </div>
              <div style={cell}>{r.title}</div>
              <div style={cell}>{r.severity}</div>
              <div style={cell}>{r.status ?? "open"}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
