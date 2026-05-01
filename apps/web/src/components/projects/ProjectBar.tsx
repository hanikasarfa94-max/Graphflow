"use client";

// ProjectBar — global project chrome, port of workgraph-ts-prototype's
// `App.tsx::ProjectBar` (lines 60-71).
//
// Persists across every /projects/[id]/... subroute. Carries:
//   * Project name crumb (server-resolved title from layout.tsx).
//   * Workbench-crumb derived from the current pathname so the user
//     always sees where they are inside the project.
//   * ScopeTierPills — the global scope-control widget. Per memory
//     workgraph_next_design_20260428: "ProjectBar pills are scope
//     control." One canonical place to toggle scope; all surfaces
//     read from the shared key (project:{id}).

import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";

import { ScopeTierPills } from "@/components/stream/ScopeTierPills";

interface Props {
  projectId: string;
  projectTitle: string | null;
}

export function ProjectBar({ projectId, projectTitle }: Props) {
  const t = useTranslations("projects.bar");
  const pathname = usePathname();
  const crumb = derivePathCrumb(pathname, projectId, t);

  return (
    <div
      data-testid="project-bar"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 14,
        padding: "8px 18px",
        borderBottom: "1px solid var(--wg-line)",
        background: "var(--wg-bg-soft, #fafafa)",
        fontSize: 12,
        fontFamily: "var(--wg-font-mono)",
        flexWrap: "wrap",
        minHeight: 40,
      }}
    >
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <span
          aria-hidden
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: "var(--wg-accent)",
          }}
        />
        <span style={{ color: "var(--wg-ink-soft)" }}>
          {t("projectLabel")}
        </span>
        <strong
          style={{
            color: "var(--wg-ink)",
            fontFamily: "var(--wg-font-sans, inherit)",
          }}
        >
          {projectTitle ?? t("untitledProject")}
        </strong>
      </span>

      <span style={{ color: "var(--wg-line)" }} aria-hidden>
        ·
      </span>

      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <span style={{ color: "var(--wg-ink-soft)" }}>
          {t("surfaceLabel")}
        </span>
        <span style={{ color: "var(--wg-ink)" }}>{crumb}</span>
      </span>

      <div style={{ flex: 1 }} />

      <ScopeTierPills projectKey={`project:${projectId}`} />
    </div>
  );
}

// derivePathCrumb — keeps the bar self-contained: no extra context
// passing, just URL → human-readable surface name. Mirrors the
// prototype's "当前工作台：个人 Agent 工作台" copy. Falls back to
// the i18n `unknown` label so the bar never blanks out on a new route.
function derivePathCrumb(
  pathname: string | null,
  projectId: string,
  t: ReturnType<typeof useTranslations>,
): string {
  if (!pathname) return t("surface.unknown");
  const base = `/projects/${projectId}`;
  if (pathname === base || pathname === `${base}/`) {
    return t("surface.personal");
  }
  if (pathname.startsWith(`${base}/rooms/`)) {
    return t("surface.room");
  }
  if (pathname.startsWith(`${base}/team`)) {
    return t("surface.team");
  }
  if (pathname.startsWith(`${base}/kb`)) {
    return t("surface.kb");
  }
  if (pathname.startsWith(`${base}/status`)) {
    return t("surface.status");
  }
  if (pathname.startsWith(`${base}/detail`)) {
    return t("surface.detail");
  }
  if (pathname.startsWith(`${base}/renders`)) {
    return t("surface.renders");
  }
  if (pathname.startsWith(`${base}/skills`)) {
    return t("surface.skills");
  }
  if (pathname.startsWith(`${base}/meetings`)) {
    return t("surface.meetings");
  }
  if (pathname.startsWith(`${base}/settings`)) {
    return t("surface.settings");
  }
  if (pathname.startsWith(`${base}/nodes`)) {
    return t("surface.node");
  }
  return t("surface.unknown");
}
