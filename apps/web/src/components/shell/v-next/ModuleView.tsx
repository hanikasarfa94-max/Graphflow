"use client";

// v-next ModuleView — Rail detail-page renderer per spec §4d.
//
// Each detail page (项目 / 任务 / 知识 / 组织 / 审计) fetches real data
// from existing endpoints. v1 picks the user's most-recently-active
// project as the anchor for taskView / knowledgeView / orgView since
// those views are project-scoped and the v-next shell does not yet
// surface a project picker inside ModuleView. The audit feed has no
// dedicated endpoint yet — that one keeps a static placeholder until
// the audit-stream slice ships.

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import {
  api,
  fetchMyProjects,
  fetchPersonalTasks,
  fetchProjectMembers,
  listKbNotes,
  type KbNote,
  type PersonalTask,
  type ProjectMember,
  type ProjectState,
  type ProjectSummary,
} from "@/lib/api";

import { GraphCanvas } from "@/app/projects/[id]/detail/graph/GraphCanvas";

import type { ActiveView } from "./AppShellClient";

import styles from "./ModuleView.module.css";

interface CardRow {
  title: string;
  meta: string;
  href?: string;
}

interface ModuleCardData {
  title: string;
  body?: string;
  rows?: CardRow[];
  emptyHint?: string;
}

interface ModuleViewSpec {
  title: string;
  subtitle: string;
  action?: string;
  cards: ModuleCardData[];
  twoColumn?: boolean;
  loading?: boolean;
  error?: string | null;
}

interface Props {
  view: ActiveView;
  // Project derived from the active stream — null when on global
  // agent / DM / no stream. GraphView uses it to fetch the right
  // project state; other views ignore it for now (they pick the
  // most-recently-active project themselves).
  activeProjectId?: string | null;
}

export function ModuleView({ view, activeProjectId = null }: Props) {
  if (view === "agentView") return null;
  switch (view) {
    case "graphView":
      return <GraphView activeProjectId={activeProjectId} />;
    case "projectView":
      return <ProjectsView />;
    case "taskView":
      return <TasksView />;
    case "knowledgeView":
      return <KnowledgeView />;
    case "orgView":
      return <OrgView />;
    case "auditView":
      return <AuditView />;
  }
}

// ---- Shared shell ----

function ModuleShell({
  view,
  spec,
}: {
  view: ActiveView;
  spec: ModuleViewSpec;
}) {
  return (
    <section className={styles.module} data-testid={`vnext-module-${view}`}>
      <div className={styles.moduleHeader}>
        <div>
          <h2>{spec.title}</h2>
          <p>{spec.subtitle}</p>
        </div>
        {spec.action && (
          <button type="button" className={styles.actionBtn}>
            {spec.action}
          </button>
        )}
      </div>
      {spec.error && (
        <p className={styles.errorHint} data-testid="vnext-module-error">
          {spec.error}
        </p>
      )}
      <div
        className={`${styles.moduleGrid} ${spec.twoColumn ? styles.gridTwo : ""}`}
      >
        {spec.cards.map((card) => (
          <div key={card.title} className={styles.moduleCard}>
            <h3>{card.title}</h3>
            {card.body && <p>{card.body}</p>}
            {card.rows && card.rows.length > 0
              ? card.rows.map((row, idx) =>
                  row.href ? (
                    <a
                      key={`${row.title}-${idx}`}
                      href={row.href}
                      className={styles.moduleRow}
                    >
                      <strong>{row.title}</strong>
                      <span>{row.meta}</span>
                    </a>
                  ) : (
                    <div
                      key={`${row.title}-${idx}`}
                      className={styles.moduleRow}
                    >
                      <strong>{row.title}</strong>
                      <span>{row.meta}</span>
                    </div>
                  ),
                )
              : card.rows
                ? card.emptyHint && (
                    <p className={styles.emptyHint}>{card.emptyHint}</p>
                  )
                : null}
          </div>
        ))}
      </div>
    </section>
  );
}

// Picks the user's primary project (most-recently-updated) so the views
// scoped to a single project have a default anchor without forcing the
// user to pick first.
function pickAnchorProject(projects: ProjectSummary[]): ProjectSummary | null {
  if (projects.length === 0) return null;
  // ProjectSummary.updated_at may be null on freshly-seeded rows; sort
  // null-last so projects with activity float up.
  const sorted = [...projects].sort((a, b) => {
    if (!a.updated_at) return 1;
    if (!b.updated_at) return -1;
    return b.updated_at.localeCompare(a.updated_at);
  });
  return sorted[0];
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return "";
  }
}

// ---- Per-view fetchers ----

function ProjectsView() {
  const t = useTranslations("shellVNext");
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchMyProjects()
      .then((p) => {
        if (cancelled) return;
        setProjects(p);
      })
      .catch(() => {
        if (cancelled) return;
        setError(t("module.loadError"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const spec: ModuleViewSpec = useMemo(() => {
    if (projects === null && !error) {
      return {
        title: t("module.projects.title"),
        subtitle: t("module.projects.subtitle"),
        cards: [
          {
            title: t("module.loading"),
            body: t("module.loadingHint"),
          },
        ],
      };
    }
    const ps = projects ?? [];
    return {
      title: t("module.projects.title"),
      subtitle: t("module.projects.subtitle"),
      action: t("module.projects.action"),
      error,
      cards: [
        {
          title: t("module.projects.activeCard"),
          rows: ps.slice(0, 8).map((p) => ({
            title: p.title,
            meta: p.role + (p.updated_at ? ` · ${fmtDate(p.updated_at)}` : ""),
            href: `/projects/${p.id}`,
          })),
          emptyHint: t("module.projects.empty"),
        },
        {
          title: t("module.projects.summaryCard"),
          body: t("module.projects.summaryBody", { count: ps.length }),
        },
      ],
    };
  }, [projects, error, t]);

  return <ModuleShell view="projectView" spec={spec} />;
}

function TasksView() {
  const t = useTranslations("shellVNext");
  const [anchor, setAnchor] = useState<ProjectSummary | null>(null);
  const [tasks, setTasks] = useState<PersonalTask[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchMyProjects()
      .then((ps) => {
        if (cancelled) return;
        const a = pickAnchorProject(ps);
        setAnchor(a);
        if (a === null) {
          setTasks([]);
          return;
        }
        return fetchPersonalTasks(a.id);
      })
      .then((res) => {
        if (cancelled || !res) return;
        setTasks(res.tasks);
      })
      .catch(() => {
        if (cancelled) return;
        setError(t("module.loadError"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const spec: ModuleViewSpec = useMemo(() => {
    if (tasks === null && !error) {
      return {
        title: t("module.tasks.title"),
        subtitle: t("module.tasks.subtitle"),
        cards: [
          {
            title: t("module.loading"),
            body: t("module.loadingHint"),
          },
        ],
      };
    }
    const list = tasks ?? [];
    const personal = list.filter((row) => row.scope === "personal");
    const planTasks = list.filter((row) => row.scope === "plan");
    return {
      title: t("module.tasks.title"),
      subtitle: anchor
        ? t("module.tasks.subtitleWithAnchor", { project: anchor.title })
        : t("module.tasks.subtitle"),
      action: t("module.tasks.action"),
      error,
      cards: [
        {
          title: t("module.tasks.personalCard"),
          rows: personal.slice(0, 10).map((row) => ({
            title: row.title,
            meta: row.status,
          })),
          emptyHint: t("module.tasks.personalEmpty"),
        },
        {
          title: t("module.tasks.planCard"),
          rows: planTasks.slice(0, 10).map((row) => ({
            title: row.title,
            meta:
              (row.assignee_role ? `${row.assignee_role} · ` : "") +
              row.status,
          })),
          emptyHint: t("module.tasks.planEmpty"),
        },
      ],
    };
  }, [anchor, tasks, error, t]);

  return <ModuleShell view="taskView" spec={spec} />;
}

function KnowledgeView() {
  const t = useTranslations("shellVNext");
  const [anchor, setAnchor] = useState<ProjectSummary | null>(null);
  const [items, setItems] = useState<KbNote[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchMyProjects()
      .then((ps) => {
        if (cancelled) return;
        const a = pickAnchorProject(ps);
        setAnchor(a);
        if (a === null) {
          setItems([]);
          return;
        }
        return listKbNotes(a.id);
      })
      .then((res) => {
        if (cancelled || !res) return;
        setItems(res.items);
      })
      .catch(() => {
        if (cancelled) return;
        setError(t("module.loadError"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const spec: ModuleViewSpec = useMemo(() => {
    if (items === null && !error) {
      return {
        title: t("module.knowledge.title"),
        subtitle: t("module.knowledge.subtitle"),
        twoColumn: true,
        cards: [
          {
            title: t("module.loading"),
            body: t("module.loadingHint"),
          },
        ],
      };
    }
    const list = items ?? [];
    const personal = list.filter((row) => row.scope === "personal");
    const group = list.filter((row) => row.scope === "group");
    return {
      title: t("module.knowledge.title"),
      subtitle: anchor
        ? t("module.knowledge.subtitleWithAnchor", { project: anchor.title })
        : t("module.knowledge.subtitle"),
      action: t("module.knowledge.action"),
      twoColumn: true,
      error,
      cards: [
        {
          title: t("module.knowledge.groupCard"),
          rows: group.slice(0, 8).map((row) => ({
            title: row.title,
            meta: `${row.status} · ${fmtDate(row.updated_at)}`,
          })),
          emptyHint: t("module.knowledge.groupEmpty"),
        },
        {
          title: t("module.knowledge.personalCard"),
          rows: personal.slice(0, 8).map((row) => ({
            title: row.title,
            meta: `${row.status} · ${fmtDate(row.updated_at)}`,
          })),
          emptyHint: t("module.knowledge.personalEmpty"),
        },
      ],
    };
  }, [anchor, items, error, t]);

  return <ModuleShell view="knowledgeView" spec={spec} />;
}

function OrgView() {
  const t = useTranslations("shellVNext");
  const [anchor, setAnchor] = useState<ProjectSummary | null>(null);
  const [members, setMembers] = useState<ProjectMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchMyProjects()
      .then((ps) => {
        if (cancelled) return;
        const a = pickAnchorProject(ps);
        setAnchor(a);
        if (a === null) {
          setMembers([]);
          return;
        }
        return fetchProjectMembers(a.id);
      })
      .then((res) => {
        if (cancelled || !res) return;
        setMembers(res);
      })
      .catch(() => {
        if (cancelled) return;
        setError(t("module.loadError"));
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const spec: ModuleViewSpec = useMemo(() => {
    if (members === null && !error) {
      return {
        title: t("module.org.title"),
        subtitle: t("module.org.subtitle"),
        cards: [
          {
            title: t("module.loading"),
            body: t("module.loadingHint"),
          },
        ],
      };
    }
    const list = members ?? [];
    return {
      title: t("module.org.title"),
      subtitle: anchor
        ? t("module.org.subtitleWithAnchor", { project: anchor.title })
        : t("module.org.subtitle"),
      action: t("module.org.action"),
      error,
      cards: [
        {
          title: t("module.org.membersCard"),
          rows: list.map((m) => ({
            title: m.display_name ?? m.username ?? m.user_id.slice(0, 8),
            meta:
              (m.role ?? "member") +
              (m.skill_tags && m.skill_tags.length > 0
                ? ` · ${m.skill_tags.join(", ")}`
                : ""),
          })),
          emptyHint: t("module.org.membersEmpty"),
        },
        {
          title: t("module.org.summaryCard"),
          body: t("module.org.summaryBody", { count: list.length }),
        },
      ],
    };
  }, [anchor, members, error, t]);

  return <ModuleShell view="orgView" spec={spec} />;
}

// Project knowledge graph — the v-Next surface for the product's core
// concept (north-star §"the graph is what the product actually is").
// Reuses the same GraphCanvas that powers /projects/[id]/detail/graph
// so the v-next shell renders the canonical view, not a re-implementation.
//
// Project resolution:
//   * If a project agent / room is the active stream → use its project_id
//   * Else fall back to the user's most-recently-active project so the
//     ⊛ Rail click never lands on an empty state when the user has any
//     project at all.
function GraphView({ activeProjectId }: { activeProjectId: string | null }) {
  const t = useTranslations("shellVNext");
  const [projectId, setProjectId] = useState<string | null>(activeProjectId);
  const [state, setState] = useState<ProjectState | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Resolve a fallback project when no active stream context.
  useEffect(() => {
    if (activeProjectId) {
      setProjectId(activeProjectId);
      return;
    }
    let cancelled = false;
    fetchMyProjects()
      .then((ps) => {
        if (cancelled) return;
        const anchor = pickAnchorProject(ps);
        setProjectId(anchor?.id ?? null);
      })
      .catch(() => {
        // Non-fatal — empty state covers it.
      });
    return () => {
      cancelled = true;
    };
  }, [activeProjectId]);

  // Fetch the project state whenever the resolved id changes.
  useEffect(() => {
    if (!projectId) {
      setState(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setState(null);
    setError(null);
    api<ProjectState>(`/api/projects/${projectId}/state`)
      .then((s) => {
        if (cancelled) return;
        setState(s);
      })
      .catch(() => {
        if (cancelled) return;
        setError(t("module.loadError"));
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, t]);

  if (!projectId) {
    return (
      <ModuleShell
        view="graphView"
        spec={{
          title: t("module.graph.title"),
          subtitle: t("module.graph.subtitle"),
          cards: [
            {
              title: t("module.graph.noProjectCard"),
              body: t("module.graph.noProjectBody"),
            },
          ],
        }}
      />
    );
  }

  if (error) {
    return (
      <ModuleShell
        view="graphView"
        spec={{
          title: t("module.graph.title"),
          subtitle: t("module.graph.subtitle"),
          error,
          cards: [],
        }}
      />
    );
  }

  if (!state) {
    return (
      <ModuleShell
        view="graphView"
        spec={{
          title: t("module.graph.title"),
          subtitle: t("module.graph.subtitle"),
          cards: [
            {
              title: t("module.loading"),
              body: t("module.loadingHint"),
            },
          ],
        }}
      />
    );
  }

  // Full canvas mount — header + bottomless GraphCanvas. The Canvas
  // owns its own toolbar, legend, and intent strip, so the wrapper
  // only contributes the page chrome.
  return (
    <section
      className={styles.module}
      data-testid="vnext-module-graphView"
      style={{ display: "flex", flexDirection: "column", padding: 0 }}
    >
      <div className={styles.moduleHeader} style={{ padding: "18px 22px 8px" }}>
        <div>
          <h2>{t("module.graph.title")}</h2>
          <p>
            {t("module.graph.subtitleAnchored", {
              project: state.project.title,
            })}
          </p>
        </div>
      </div>
      <div style={{ flex: "1 1 auto", minHeight: 0 }}>
        <GraphCanvas projectId={projectId} state={state} />
      </div>
    </section>
  );
}

function AuditView() {
  // No audit-feed endpoint in v1. Render a placeholder card noting the
  // pending wiring; spec §11 doesn't enumerate this slice yet.
  const t = useTranslations("shellVNext");
  const spec: ModuleViewSpec = {
    title: t("module.audit.title"),
    subtitle: t("module.audit.subtitle"),
    action: t("module.audit.action"),
    cards: [
      {
        title: t("module.audit.pendingCard"),
        body: t("module.audit.pendingBody"),
      },
    ],
  };
  return <ModuleShell view="auditView" spec={spec} />;
}
