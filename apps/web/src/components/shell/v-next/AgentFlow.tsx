"use client";

// v-next AgentFlow — main column when activeView === 'agentView'.
//
// Phase 3 wiring per docs/shell-v-next.txt §4b + §11:
//   * flowHead pills [资料][记忆][技能] are now functional links to the
//     active project's detail pages (E-4 — server-side endpoint isn't
//     needed because project_id is already on the active stream). On
//     project-less streams (通用 Agent / DM) they render disabled with
//     a tooltip explaining the gap.
//   * analysisCard (E-5) renders above the timeline when the stream
//     has a project_id. Fetches /api/vnext/streams/{id}/related and
//     surfaces top tasks + risks counts. Hidden when empty so it
//     doesn't compete with the conversation when there's nothing to
//     show.
//   * Composer wires E-8 project-inference suggestion + auto-dispatch
//     persistence + thinking-mode persistence.
//
// Immersive toggle stays here; lifts to parent so AppShellClient can
// hide rail/imnav/workbench.

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { fetchVNextRelated, type User, type VNextRelated } from "@/lib/api";

import { AgentComposer } from "./AgentComposer";
import { AgentTimeline } from "./AgentTimeline";
import type {
  ShellPersonalAgent,
  ShellGroupItem,
  ShellDMItem,
} from "./types";

import styles from "./AgentFlow.module.css";

interface Props {
  user: User;
  activeStreamId: string | null;
  generalAgent: ShellPersonalAgent | null;
  projectAgents: ShellPersonalAgent[];
  groups: ShellGroupItem[];
  dms: ShellDMItem[];
  immersive: boolean;
  onToggleImmersive: () => void;
  onSwitchStream?: (streamId: string) => void;
  children: React.ReactNode;
}

export function AgentFlow({
  user,
  activeStreamId,
  generalAgent,
  projectAgents,
  groups,
  dms,
  immersive,
  onToggleImmersive,
  onSwitchStream,
  children,
}: Props) {
  const t = useTranslations("shellVNext");

  const active = resolveActive(
    activeStreamId,
    generalAgent,
    projectAgents,
    groups,
    dms,
  );

  if (!active || !activeStreamId) {
    // No stream selected client-side — render the routed page so
    // existing surfaces (HomeHero, /projects/[id], etc.) still work
    // while we transition.
    return <div className={styles.routedSlot}>{children}</div>;
  }

  const projectId = active.projectId ?? null;
  const isGeneralAgent =
    generalAgent !== null && activeStreamId === generalAgent.stream_id;

  return (
    <section className={styles.flow} data-testid="vnext-agent-flow">
      <header className={styles.flowHead}>
        <div className={styles.face} aria-hidden>
          {active.face}
        </div>
        <div className={styles.flowTitle}>
          <h2>{active.title}</h2>
          {active.subtitle && <small>{active.subtitle}</small>}
        </div>
        <div className={styles.flowActions}>
          <span className={styles.tag} data-tag-kind={active.tag}>
            {t(`tag.${active.tag}`)}
          </span>
          <FlowPill
            href={projectId ? `/projects/${projectId}/knowledge` : null}
            label={t("flowPill.info")}
            tip={
              projectId ? t("flowPill.infoTipProject") : t("flowPill.infoTip")
            }
            testid="vnext-flow-pill-info"
          />
          <FlowPill
            href={projectId ? `/projects/${projectId}/perf` : null}
            label={t("flowPill.memory")}
            tip={
              projectId
                ? t("flowPill.memoryTipProject")
                : t("flowPill.memoryTip")
            }
            testid="vnext-flow-pill-memory"
          />
          <FlowPill
            href={projectId ? `/projects/${projectId}/skills` : null}
            label={t("flowPill.skills")}
            tip={
              projectId
                ? t("flowPill.skillsTipProject")
                : t("flowPill.skillsTip")
            }
            testid="vnext-flow-pill-skills"
          />
          <button
            type="button"
            className={styles.iconBtn}
            onClick={onToggleImmersive}
            aria-pressed={immersive}
            aria-label={t("immersiveToggle")}
            title={t("immersiveToggle")}
            data-testid="vnext-flow-immersive"
          >
            ⛶
          </button>
        </div>
      </header>

      <AnalysisCard streamId={activeStreamId} hasProject={projectId !== null} />

      <AgentTimeline streamId={activeStreamId} user={user} />

      <AgentComposer
        streamId={activeStreamId}
        isGeneralAgent={isGeneralAgent}
        projectAgents={projectAgents
          .filter(
            (p): p is ShellPersonalAgent & { project_id: string } =>
              p.project_id !== null,
          )
          .map((p) => ({
            project_id: p.project_id,
            title: p.anchor_name,
            stream_id: p.stream_id,
          }))}
        onSuggestionAccept={onSwitchStream}
      />
    </section>
  );
}

function FlowPill({
  href,
  label,
  tip,
  testid,
}: {
  href: string | null;
  label: string;
  tip: string;
  testid: string;
}) {
  if (!href) {
    return (
      <button
        type="button"
        className={`${styles.pill} ${styles.pillDisabled}`}
        title={tip}
        disabled
        data-testid={testid}
      >
        {label}
      </button>
    );
  }
  return (
    <a
      className={styles.pill}
      href={href}
      title={tip}
      data-testid={testid}
    >
      {label}
    </a>
  );
}

function AnalysisCard({
  streamId,
  hasProject,
}: {
  streamId: string;
  hasProject: boolean;
}) {
  const t = useTranslations("shellVNext");
  const [data, setData] = useState<VNextRelated | null>(null);

  useEffect(() => {
    if (!hasProject) {
      setData(null);
      return;
    }
    let cancelled = false;
    fetchVNextRelated(streamId)
      .then((res) => {
        if (cancelled) return;
        setData(res);
      })
      .catch(() => {
        if (cancelled) return;
        // Hide the card on fetch error — better than a fake state.
        setData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [streamId, hasProject]);

  if (!hasProject || !data) return null;
  const total =
    data.tasks.length + data.decisions.length + data.risks.length;
  if (total === 0) return null;

  const topTasks = data.tasks.slice(0, 3);
  return (
    <aside
      className={styles.analysisCard}
      data-testid="vnext-analysis-card"
    >
      <div className={styles.analysisHeader}>
        <strong>{t("analysis.title")}</strong>
        <span>
          {t("analysis.summary", {
            tasks: data.tasks.length,
            decisions: data.decisions.length,
            risks: data.risks.length,
          })}
        </span>
      </div>
      {topTasks.length > 0 && (
        <ul className={styles.analysisList}>
          {topTasks.map((task) => (
            <li key={task.id}>
              <span className={styles.taskTitle}>{task.title}</span>
              <span className={styles.taskMeta}>
                {task.assignee_role
                  ? `${task.assignee_role} · ${task.status}`
                  : task.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

interface ActiveStream {
  title: string;
  subtitle?: string;
  face: string;
  tag: "agent" | "group" | "dm";
  projectId?: string | null;
}

function resolveActive(
  streamId: string | null,
  generalAgent: ShellPersonalAgent | null,
  projectAgents: ShellPersonalAgent[],
  groups: ShellGroupItem[],
  dms: ShellDMItem[],
): ActiveStream | null {
  if (!streamId) return null;

  if (generalAgent && generalAgent.stream_id === streamId) {
    return {
      title: "通用 Agent",
      subtitle: "整合全平台信息，跨项目咨询。",
      face: "🤖",
      tag: "agent",
      projectId: null,
    };
  }

  const pa = projectAgents.find((p) => p.stream_id === streamId);
  if (pa) {
    return {
      title: `${pa.anchor_name} 的 Agent`,
      subtitle: "项目作用域的 Agent · 此项目的会话与决策。",
      face: "🤖",
      tag: "agent",
      projectId: pa.project_id,
    };
  }

  const g = groups.find((x) => x.stream_id === streamId);
  if (g) {
    return {
      title: g.display_name ?? "未命名群组",
      subtitle: `${g.member_count} 位成员 · ${
        g.kind === "project" ? "项目主群" : "子房间"
      }`,
      face: "#",
      tag: "group",
      projectId: g.project_id,
    };
  }

  const d = dms.find((x) => x.stream_id === streamId);
  if (d) {
    return {
      title: d.other_display_name,
      subtitle: "单聊",
      face: d.other_display_name.charAt(0).toUpperCase(),
      tag: "dm",
      projectId: null,
    };
  }

  return null;
}
