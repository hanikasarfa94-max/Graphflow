"use client";

// v-next AppShellClient — 4-column grid wrapper.
//
// Layout per docs/shell-v-next.txt §1 + workgraph-ts-prototype/
// legacy-standalone-v6.html:
//
//   .app    grid-template-rows:    var(--top) var(--bar) 1fr
//   .layout grid-template-columns: var(--rail) var(--im) 6px 1fr 6px var(--tools)
//
// State modes per §6 — moduleMode (Rail icon active, hides ImNav),
// toolsClosed (Workbench hidden), immersive (everything except top+main
// hidden). leftNarrow not yet wired in v1; comes with the splitter
// resize affordance in a follow-up.

import { useMemo, useState, type ReactNode } from "react";

import type { User } from "@/lib/api";

import { Topbar } from "../Topbar";

import { AgentFlow } from "./AgentFlow";
import { ImNav } from "./ImNav";
import { ModuleView } from "./ModuleView";
import { ProjectBarVNext } from "./ProjectBarVNext";
import { Rail } from "./Rail";
import { Workbench } from "./Workbench";
import type {
  ShellPersonalAgent,
  ShellGroupItem,
  ShellDMItem,
  ShellWorkspace,
} from "./types";

import styles from "./AppShellClient.module.css";

export interface AppShellVNextClientProps {
  user: User;
  generalAgent: ShellPersonalAgent | null;
  projectAgents: ShellPersonalAgent[];
  groups: ShellGroupItem[];
  dms: ShellDMItem[];
  initialInboxCount: number;
  workspaces: ShellWorkspace[];
  children: ReactNode;
}

export type ActiveView =
  | "agentView"
  | "projectView"
  | "taskView"
  | "knowledgeView"
  | "orgView"
  | "auditView";

export function AppShellVNextClient({
  user,
  generalAgent,
  projectAgents,
  groups,
  dms,
  children,
}: AppShellVNextClientProps) {
  const [activeView, setActiveView] = useState<ActiveView>("agentView");
  const [activeStreamId, setActiveStreamId] = useState<string | null>(
    generalAgent?.stream_id ?? null,
  );
  const [toolsOpen, setToolsOpen] = useState(false);
  const [immersive, setImmersive] = useState(false);
  const [cellPillOn, setCellPillOn] = useState(false);

  const moduleMode = activeView !== "agentView";

  // Derive ProjectBar context from the active stream — the v-next
  // shell uses stream-as-primary-nav, so the project crumb tracks
  // whichever stream the user has focused (per spec §5: read-only
  // crumb showing which Cell scope WOULD apply if the user toggles
  // the Cell pill on).
  const { projectTitle, surfaceLabel } = useMemo(() => {
    if (!activeStreamId) {
      return { projectTitle: null, surfaceLabel: null };
    }
    if (generalAgent && generalAgent.stream_id === activeStreamId) {
      return { projectTitle: null, surfaceLabel: null };
    }
    const pa = projectAgents.find((p) => p.stream_id === activeStreamId);
    if (pa) {
      return {
        projectTitle: pa.anchor_name,
        surfaceLabel: "项目 Agent",
      };
    }
    const g = groups.find((x) => x.stream_id === activeStreamId);
    if (g) {
      return {
        projectTitle: g.display_name ?? null,
        surfaceLabel: g.kind === "project" ? "项目主群" : "子房间",
      };
    }
    const d = dms.find((x) => x.stream_id === activeStreamId);
    if (d) {
      return {
        projectTitle: null,
        surfaceLabel: "单聊",
      };
    }
    return { projectTitle: null, surfaceLabel: null };
  }, [activeStreamId, generalAgent, projectAgents, groups, dms]);

  // Stream-kind for E-9 workbench-layout lookup. Personal streams
  // (global + per-project agents) share one composition; rooms / DMs
  // get their own.
  const activeStreamKind: "personal" | "room" | "dm" = useMemo(() => {
    if (!activeStreamId) return "personal";
    if (generalAgent && generalAgent.stream_id === activeStreamId) {
      return "personal";
    }
    if (projectAgents.some((p) => p.stream_id === activeStreamId)) {
      return "personal";
    }
    if (groups.some((g) => g.stream_id === activeStreamId)) {
      return "room";
    }
    if (dms.some((d) => d.stream_id === activeStreamId)) {
      return "dm";
    }
    return "personal";
  }, [activeStreamId, generalAgent, projectAgents, groups, dms]);

  return (
    <div
      className={[
        styles.app,
        moduleMode ? styles.moduleMode : "",
        toolsOpen ? "" : styles.toolsClosed,
        immersive ? styles.immersive : "",
      ].join(" ")}
      data-testid="vnext-app-shell"
    >
      <div className={styles.top}>
        <Topbar />
      </div>

      <div className={styles.bar}>
        <ProjectBarVNext
          projectTitle={projectTitle}
          surfaceLabel={surfaceLabel}
          cellPillOn={cellPillOn}
          onToggleCellPill={() => setCellPillOn((v) => !v)}
        />
      </div>

      <div className={styles.layout}>
        {!immersive && (
          <Rail
            activeView={activeView}
            onChange={setActiveView}
            onToggleTools={() => setToolsOpen((v) => !v)}
          />
        )}

        {!moduleMode && !immersive && (
          <ImNav
            generalAgent={generalAgent}
            projectAgents={projectAgents}
            groups={groups}
            dms={dms}
            activeStreamId={activeStreamId}
            onSelectStream={(id) => {
              setActiveStreamId(id);
              setActiveView("agentView");
            }}
          />
        )}

        <main className={styles.main}>
          {activeView === "agentView" ? (
            <AgentFlow
              user={user}
              activeStreamId={activeStreamId}
              generalAgent={generalAgent}
              projectAgents={projectAgents}
              groups={groups}
              dms={dms}
              immersive={immersive}
              onToggleImmersive={() => setImmersive((v) => !v)}
              onSwitchStream={(id) => {
                setActiveStreamId(id);
                setActiveView("agentView");
              }}
            >
              {children}
            </AgentFlow>
          ) : (
            <ModuleView view={activeView} />
          )}
        </main>

        {!immersive && toolsOpen && (
          <Workbench
            onClose={() => setToolsOpen(false)}
            streamKind={activeStreamKind}
          />
        )}
      </div>
    </div>
  );
}
