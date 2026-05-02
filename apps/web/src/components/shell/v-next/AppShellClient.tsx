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

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useRouter } from "next/navigation";

import type { User } from "@/lib/api";

import {
  ShellContext,
  type ShellCtx,
} from "../AppShellClient";
import { RoutedInboundDrawer } from "../RoutedInboundDrawer";
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
  | "graphView"
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
  initialInboxCount,
  workspaces,
  children,
}: AppShellVNextClientProps) {
  const router = useRouter();
  const [activeView, setActiveView] = useState<ActiveView>("agentView");
  // Default to NO active stream so routed pages (homepage HomeHero,
  // /projects/[id], etc.) render through AgentFlow's routedSlot. Users
  // pick a stream by clicking the agentPrimary / project / room / DM
  // card in ImNav. Earlier auto-selection of the global agent on mount
  // hijacked the homepage and showed an empty timeline instead of
  // HomeHero — bad UX for first-time users.
  const [activeStreamId, setActiveStreamId] = useState<string | null>(null);
  // Workbench is open by default per prototype — the right column is a
  // primary affordance, not a hidden tray. Users toggle off via the ▦
  // button in the Rail.
  const [toolsOpen, setToolsOpen] = useState(true);
  // ImNav narrow mode — labels collapse, icon column at 76px. Discovers
  // the same `leftNarrow` state the splitter-drag handler sets when the
  // user drags ImNav < 120px wide; the toggle just adds a one-click
  // affordance so users don't need to discover the drag.
  const [leftNarrow, setLeftNarrow] = useState(false);
  const [immersive, setImmersive] = useState(false);
  const [cellPillOn, setCellPillOn] = useState(false);

  // Routed-inbox drawer state. Same pattern as legacy AppShellClient —
  // co-owned here so Topbar's Notifications button + signal-card "open"
  // affordances both flow through the shared Context. Without this v-next
  // shows count=0 always and the Notifications click no-ops.
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [inboxCount, setInboxCount] = useState(initialInboxCount);
  const openInbox = useCallback(() => setDrawerOpen(true), []);
  const closeInbox = useCallback(() => setDrawerOpen(false), []);
  const shellCtx = useMemo<ShellCtx>(
    () => ({ inboxCount, setInboxCount, openInbox, closeInbox }),
    [inboxCount, openInbox, closeInbox],
  );

  const moduleMode = activeView !== "agentView";

  // Splitter resize — port of legacy-standalone-v6.html lines 263-271.
  // ImNav width clamps to [76, 340]; Workbench width clamps to [330, 760].
  // We write to CSS variables on the .app element so the existing grid
  // template picks them up without re-rendering the layout.
  const appRef = useRef<HTMLDivElement>(null);
  const resizingRef = useRef<"left" | "tools" | null>(null);

  useEffect(() => {
    function onMove(e: MouseEvent) {
      const which = resizingRef.current;
      if (!which || !appRef.current) return;
      if (which === "left") {
        // ImNav width = mouseX - rail (50px). Clamp [76, 340].
        const w = Math.max(76, Math.min(340, e.clientX - 50));
        appRef.current.style.setProperty("--im", `${w}px`);
        // Mirror the prototype's leftNarrow toggle so labels collapse
        // when the column gets too narrow to read them.
        setLeftNarrow(w < 120);
      } else {
        // Tools width = viewport - mouseX. Clamp [330, 760].
        const w = Math.max(330, Math.min(760, window.innerWidth - e.clientX));
        appRef.current.style.setProperty("--tools", `${w}px`);
      }
    }
    function onUp() {
      if (!resizingRef.current) return;
      resizingRef.current = null;
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  function beginResize(which: "left" | "tools") {
    resizingRef.current = which;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
  }

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

  // Active project derived from the focused stream (when any). Powers
  // the GraphView's fetch + the ModuleView's project-scoped detail
  // pages. Falls back to null when on global agent / DM / no stream;
  // GraphView then renders an empty-state placeholder.
  const activeProjectId: string | null = useMemo(() => {
    if (!activeStreamId) return null;
    const pa = projectAgents.find((p) => p.stream_id === activeStreamId);
    if (pa) return pa.project_id;
    const g = groups.find((x) => x.stream_id === activeStreamId);
    if (g) return g.project_id;
    return null;
  }, [activeStreamId, projectAgents, groups]);

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
    <ShellContext.Provider value={shellCtx}>
      <div
        ref={appRef}
        className={[
          styles.app,
          moduleMode ? styles.moduleMode : "",
          toolsOpen ? "" : styles.toolsClosed,
          immersive ? styles.immersive : "",
          leftNarrow ? styles.leftNarrow : "",
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
          activeProjectId={activeProjectId}
        />
      </div>

      <div className={styles.layout}>
        {!immersive && (
          <Rail
            activeView={activeView}
            onChange={(next) => {
              // Audit view defers to the detail/* pages which already
              // ship the canonical AuditTabBar (graph/plan/tasks/risks/
              // decisions). When the user has an active project, route
              // there so the full subview tab set is reachable; only
              // fall back to the in-shell placeholder when there's no
              // project context to anchor on.
              if (next === "auditView" && activeProjectId) {
                router.push(`/projects/${activeProjectId}/detail/graph`);
                return;
              }
              setActiveView(next);
            }}
            onToggleTools={() => setToolsOpen((v) => !v)}
            user={user}
          />
        )}

        {!moduleMode && !immersive && (
          <ImNav
            generalAgent={generalAgent}
            projectAgents={projectAgents}
            groups={groups}
            dms={dms}
            workspaces={workspaces}
            activeStreamId={activeStreamId}
            activeProjectId={activeProjectId}
            currentUserId={user.id}
            narrow={leftNarrow}
            onToggleNarrow={() => {
              setLeftNarrow((v) => {
                const next = !v;
                // Snap the CSS variable in lockstep so the splitter
                // drag and the toggle agree on width.
                if (appRef.current) {
                  appRef.current.style.setProperty(
                    "--im",
                    next ? "76px" : "254px",
                  );
                }
                return next;
              });
            }}
            onSelectStream={(id) => {
              setActiveStreamId(id);
              setActiveView("agentView");
            }}
          />
        )}

        {!moduleMode && !immersive && (
          <div
            className={styles.splitter}
            data-testid="vnext-splitter-left"
            role="separator"
            aria-orientation="vertical"
            onMouseDown={() => beginResize("left")}
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
            <ModuleView
              view={activeView}
              activeProjectId={activeProjectId}
            />
          )}
        </main>

        {!immersive && toolsOpen && (
          <div
            className={styles.splitter}
            data-testid="vnext-splitter-tools"
            role="separator"
            aria-orientation="vertical"
            onMouseDown={() => beginResize("tools")}
          />
        )}

        {!immersive && toolsOpen && (
          <Workbench
            onClose={() => setToolsOpen(false)}
            streamKind={activeStreamKind}
            activeProjectId={activeProjectId}
          />
        )}
      </div>

      <RoutedInboundDrawer
        open={drawerOpen}
        onClose={closeInbox}
        onCountChange={setInboxCount}
      />
    </div>
    </ShellContext.Provider>
  );
}
