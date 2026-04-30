// /projects/[id]/renders — Batch F.5 index page.
//
// Two cards per html2 spec:
//   * Project postmortem — last-generated stamp + View / Regenerate
//   * Handoff docs — list of teammates with a per-row "Generate" button
//     that takes them to /renders/handoff:{user_id}
//
// Server component. Postmortem fetch is best-effort — a missing render
// (404) just means "not generated yet"; we still render the View link
// so the existing /renders/[slug] page can show its own empty state.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import {
  Card,
  EmptyState,
  PageHeader,
  Tag,
  Text,
} from "@/components/ui";
import {
  ApiError,
  type PostmortemRender,
  type ProjectState,
} from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function RendersIndexPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const user = await requireUser(`/projects/${id}/renders`);
  const t = await getTranslations("renders.index");

  let state: ProjectState | null = null;
  try {
    state = await serverFetch<ProjectState>(`/api/projects/${id}/state`);
  } catch {
    state = null;
  }

  let postmortem: PostmortemRender | null = null;
  let postmortemMissing = false;
  try {
    postmortem = await serverFetch<PostmortemRender>(
      `/api/projects/${id}/renders/postmortem`,
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      postmortemMissing = true;
    } else {
      postmortem = null;
    }
  }

  const teammates = (state?.members ?? []).filter(
    (m) => m.user_id !== user.id,
  );

  return (
    <main style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 28px 80px" }}>
      <PageHeader title={t("title")} subtitle={t("subtitle")} />

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: 18,
        }}
      >
        <Card title={t("postmortem.title")} subtitle={t("postmortem.subtitle")}>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 12,
            }}
          >
            <div
              style={{
                fontSize: 14,
                fontWeight: 600,
                color: "var(--wg-ink)",
              }}
            >
              {state?.project?.title
                ? t("postmortem.heading", { project: state.project.title })
                : t("postmortem.headingNoProject")}
            </div>
            {postmortem ? (
              <Text
                variant="caption"
                muted
                style={{ fontFamily: "var(--wg-font-mono)" }}
              >
                {t("postmortem.generatedAt", {
                  time: new Date(postmortem.generated_at).toLocaleString(),
                })}
                {postmortem.outcome !== "ok"
                  ? ` · ${postmortem.outcome}`
                  : ""}
              </Text>
            ) : postmortemMissing ? (
              <Tag tone="amber">{t("postmortem.notGenerated")}</Tag>
            ) : (
              <Tag tone="neutral">{t("postmortem.unavailable")}</Tag>
            )}
            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <Link
                href={`/projects/${id}/renders/postmortem`}
                style={primaryBtn}
              >
                {postmortem ? t("postmortem.view") : t("postmortem.generate")}
              </Link>
            </div>
          </div>
        </Card>

        <Card title={t("handoff.title")} subtitle={t("handoff.subtitle")}>
          {teammates.length === 0 ? (
            <EmptyState>{t("handoff.empty")}</EmptyState>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {teammates.map((m) => (
                <div
                  key={m.user_id}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "minmax(0, 1fr) auto",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 12px",
                    background: "var(--wg-surface)",
                    border: "1px solid var(--wg-line)",
                    borderRadius: 12,
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 14,
                        fontWeight: 500,
                        color: "var(--wg-ink)",
                      }}
                    >
                      {m.display_name ?? m.username}
                    </div>
                    <div
                      style={{
                        marginTop: 2,
                        fontSize: 11,
                        color: "var(--wg-ink-faint)",
                        fontFamily: "var(--wg-font-mono)",
                      }}
                    >
                      {m.role}
                      {m.license_tier && m.license_tier !== "full"
                        ? ` · ${m.license_tier}`
                        : ""}
                    </div>
                  </div>
                  <Link
                    href={`/projects/${id}/renders/handoff%3A${m.user_id}`}
                    style={ghostBtn}
                  >
                    {t("handoff.generate")}
                  </Link>
                </div>
              ))}
            </div>
          )}
        </Card>
      </section>
    </main>
  );
}

const primaryBtn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  height: 34,
  padding: "0 14px",
  borderRadius: 12,
  background: "var(--wg-accent)",
  color: "#fff",
  textDecoration: "none",
  fontSize: 12,
  fontWeight: 700,
};

const ghostBtn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  height: 30,
  padding: "0 12px",
  borderRadius: 10,
  background: "var(--wg-surface)",
  border: "1px solid var(--wg-line)",
  color: "var(--wg-ink)",
  textDecoration: "none",
  fontSize: 12,
  fontWeight: 600,
};
