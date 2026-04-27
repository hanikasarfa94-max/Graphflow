// /projects — Batch F.2 rebuild per html2 spec.
//
// Three cards, top-to-bottom:
//   1. Intake — natural-language textarea + "Intake →" submit
//      (NewProjectForm, wrapped in a Card).
//   2. Portfolio overview — 4-metric strip (projects / needing
//      attention / single-point risks / unique members).
//   3. Project list — each row shows mono chips
//      (role · {tasks} tasks · {deliverables} deliverables · {risks} risks)
//      and an "Open" CTA that lands directly on /status.
//
// Server component. Per-project /state fetch in parallel so the chips
// + portfolio aggregates come from real numbers; tolerant — a single
// project failing doesn't break the page.

import Link from "next/link";
import { getTranslations } from "next-intl/server";

import {
  Card,
  EmptyState,
  Metric,
  PageHeader,
  Tag,
  Text,
} from "@/components/ui";
import type { ProjectState, ProjectSummary } from "@/lib/api";
import { requireUser, serverFetch } from "@/lib/auth";

import { NewProjectForm } from "./NewProjectForm";

export const dynamic = "force-dynamic";

type ProjectStat = {
  summary: ProjectSummary;
  state: ProjectState | null;
};

async function fetchAll(projects: ProjectSummary[]): Promise<ProjectStat[]> {
  return Promise.all(
    projects.map(async (p) => {
      try {
        const state = await serverFetch<ProjectState>(
          `/api/projects/${p.id}/state`,
        );
        return { summary: p, state };
      } catch {
        return { summary: p, state: null };
      }
    }),
  );
}

export default async function ProjectsPage() {
  await requireUser("/projects");
  const t = await getTranslations();
  const projects = await serverFetch<ProjectSummary[]>("/api/projects").catch(
    () => [] as ProjectSummary[],
  );
  const stats = await fetchAll(projects);

  // Portfolio aggregates — computed from the per-project state we
  // already fetched, so the strip stays in sync with the chips below.
  const projectCount = projects.length;
  const needingAttention = stats.filter(
    (s) =>
      (s.state?.graph?.risks ?? []).some((r) => r.status === "open") ||
      (s.state?.decisions ?? []).length === 0,
  ).length;
  // Single-point risk = a project where every gate-class is held by
  // exactly one user. We don't have gate-keeper-map in /state; the
  // honest proxy here is "owner is the only owner-role member".
  const singlePointRisks = stats.filter((s) => {
    const owners = (s.state?.members ?? []).filter((m) => m.role === "owner");
    return owners.length === 1 && (s.state?.members?.length ?? 0) > 1;
  }).length;
  const uniqueMembers = new Set<string>();
  for (const s of stats) {
    for (const m of s.state?.members ?? []) uniqueMembers.add(m.user_id);
  }

  return (
    <main style={{ maxWidth: 1180, margin: "0 auto", padding: "32px 28px 80px" }}>
      <PageHeader
        title={t("projects.heading")}
        subtitle={t("projects.subtitle")}
      />

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
          gap: 18,
          marginBottom: 18,
        }}
      >
        <Card
          title={t("projects.intake.title")}
          subtitle={t("projects.intake.subtitle")}
        >
          <NewProjectForm />
        </Card>
        <Card
          title={t("projects.portfolio.title")}
          subtitle={t("projects.portfolio.subtitle")}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(2, 1fr)",
              gap: 10,
            }}
          >
            <Metric value={projectCount} label={t("projects.portfolio.projects")} />
            <Metric
              value={needingAttention}
              label={t("projects.portfolio.attention")}
              tone={needingAttention > 0 ? "amber" : "neutral"}
            />
            <Metric
              value={singlePointRisks}
              label={t("projects.portfolio.singlePoint")}
              tone={singlePointRisks > 0 ? "danger" : "neutral"}
            />
            <Metric value={uniqueMembers.size} label={t("projects.portfolio.members")} />
          </div>
        </Card>
      </section>

      <Card
        title={t("projects.listHeading")}
        subtitle={t("projects.listSubtitle")}
      >
        {stats.length === 0 ? (
          <EmptyState>{t("projects.empty")}</EmptyState>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {stats.map((s) => (
              <ProjectRow key={s.summary.id} stat={s} t={t} />
            ))}
          </div>
        )}
      </Card>
    </main>
  );
}

function ProjectRow({
  stat,
  t,
}: {
  stat: ProjectStat;
  t: Awaited<ReturnType<typeof getTranslations>>;
}) {
  const { summary, state } = stat;
  const taskCount = state?.plan?.tasks?.length ?? 0;
  const deliverableCount = state?.graph?.deliverables?.length ?? 0;
  const riskCount = (state?.graph?.risks ?? []).filter(
    (r) => r.status === "open",
  ).length;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) auto",
        alignItems: "center",
        gap: 12,
        padding: 14,
        background: "var(--wg-surface)",
        border: "1px solid var(--wg-line)",
        borderRadius: 14,
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: 15,
            fontWeight: 600,
            color: "var(--wg-ink)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {summary.title}
        </div>
        <div
          style={{
            marginTop: 6,
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            fontSize: 11,
            fontFamily: "var(--wg-font-mono)",
            color: "var(--wg-ink-soft)",
          }}
        >
          <Tag tone="neutral">{summary.role}</Tag>
          <Tag tone={taskCount > 0 ? "accent" : "neutral"}>
            {t("projects.row.tasks", { count: taskCount })}
          </Tag>
          <Tag tone="neutral">
            {t("projects.row.deliverables", { count: deliverableCount })}
          </Tag>
          <Tag tone={riskCount > 0 ? "danger" : "neutral"}>
            {t("projects.row.risks", { count: riskCount })}
          </Tag>
        </div>
      </div>
      <Link
        href={`/projects/${summary.id}/status`}
        style={{
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
          flexShrink: 0,
        }}
      >
        {t("projects.row.open")}
      </Link>
    </div>
  );
}
