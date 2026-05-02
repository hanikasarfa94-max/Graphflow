"use client";

// v-next AgentFlow — main column when activeView === 'agentView'.
//
// Phase 2 upgrade per docs/shell-v-next.txt §4b:
//   * flowHead with face + title + sub + tag + 3 pills (资料/记忆/技能) + ⛶
//   * messages from AgentTimeline (real /api/streams/{id}/messages)
//   * composer from AgentComposer (with autoAgent toggle + 深度思考 select)
//
// The 3 pills are inert per E-4 (no "stream context info" lookup
// endpoint exists yet; v1 renders the visual without wiring).
// analysisCard is omitted per spec recommendation (better than fake
// data; reintroduce when E-5 lands).
//
// Immersive toggle is owned here; lifts to parent via prop callback so
// the AppShellClient can hide rail/imnav/workbench.

import { useTranslations } from "next-intl";

import type { User } from "@/lib/api";

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
          {/* Inert per spec E-4 — v1 visual without wiring; tooltips
              hint at future destinations. */}
          <button
            type="button"
            className={styles.pill}
            title={t("flowPill.infoTip")}
            data-testid="vnext-flow-pill-info"
          >
            {t("flowPill.info")}
          </button>
          <button
            type="button"
            className={styles.pill}
            title={t("flowPill.memoryTip")}
            data-testid="vnext-flow-pill-memory"
          >
            {t("flowPill.memory")}
          </button>
          <button
            type="button"
            className={styles.pill}
            title={t("flowPill.skillsTip")}
            data-testid="vnext-flow-pill-skills"
          >
            {t("flowPill.skills")}
          </button>
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

      <AgentTimeline streamId={activeStreamId} user={user} />

      <AgentComposer streamId={activeStreamId} />
    </section>
  );
}

interface ActiveStream {
  title: string;
  subtitle?: string;
  face: string;
  tag: "agent" | "group" | "dm";
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
    };
  }

  const pa = projectAgents.find((p) => p.stream_id === streamId);
  if (pa) {
    return {
      title: `${pa.anchor_name} 的 Agent`,
      subtitle: "项目作用域的 Agent · 此项目的会话与决策。",
      face: "🤖",
      tag: "agent",
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
    };
  }

  const d = dms.find((x) => x.stream_id === streamId);
  if (d) {
    return {
      title: d.other_display_name,
      subtitle: "单聊",
      face: d.other_display_name.charAt(0).toUpperCase(),
      tag: "dm",
    };
  }

  return null;
}
