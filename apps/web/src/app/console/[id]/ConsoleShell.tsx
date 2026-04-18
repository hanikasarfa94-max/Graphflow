"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type {
  Conflict,
  ConflictSummary,
  Decision,
  Delivery,
  EventRow,
  ProjectState,
} from "@/lib/api";
import { deriveStage, type Stage } from "@/lib/stage";

import { CanvasRouter } from "./canvas/CanvasRouter";
import { AgentLogDrawer } from "./AgentLogDrawer";
import { GraphSidebar } from "./GraphSidebar";

type WsFrame = { type: string; payload: Record<string, unknown> };

type SSEEvent = {
  id: string;
  name: string;
  trace_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
};

type ActiveAgent = {
  name: string;
  startedAt: number;
  traceId: string | null;
};

const AGENT_EVENT_PREFIXES: Record<string, string> = {
  "intake.": "Requirement Agent",
  "clarification.": "Clarification Agent",
  "plan.": "Planning Agent",
  "conflicts.": "Conflict Explanation Agent",
  "decision.": "Decision Applier",
  "delivery.": "Delivery Agent",
};

function agentNameFromEvent(name: string): string | null {
  for (const prefix in AGENT_EVENT_PREFIXES) {
    if (name.startsWith(prefix)) return AGENT_EVENT_PREFIXES[prefix];
  }
  return null;
}

export function ConsoleShell({
  projectId,
  initialState,
  initialDeliveryHistory,
}: {
  projectId: string;
  initialState: ProjectState;
  initialDeliveryHistory: Delivery[];
}) {
  const [state, setState] = useState<ProjectState>(initialState);
  const [deliveryHistory, setDeliveryHistory] = useState<Delivery[]>(
    initialDeliveryHistory,
  );
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [wsState, setWsState] = useState<"connecting" | "open" | "closed">(
    "connecting",
  );
  const [activeAgent, setActiveAgent] = useState<ActiveAgent | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const agentTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { stage, hint } = useMemo(
    () => deriveStage(state, state.delivery),
    [state],
  );

  // WS — authoritative updates for conflicts/decisions/delivery.
  useEffect(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(
      `${proto}//${window.location.host}/ws/projects/${projectId}`,
    );
    setWsState("connecting");
    ws.onopen = () => setWsState("open");
    ws.onclose = () => setWsState("closed");
    ws.onerror = () => setWsState("closed");
    ws.onmessage = (ev) => {
      try {
        const frame = JSON.parse(ev.data) as WsFrame;
        applyFrame(frame);
      } catch {
        // ignore malformed frame
      }
    };
    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // SSE — event log tail. Agent-run badge derives from event prefixes.
  useEffect(() => {
    const es = new EventSource(
      `/api/events/stream?project_id=${encodeURIComponent(projectId)}`,
      { withCredentials: true },
    );
    es.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (data.type === "hello") return;
        const evt = data as SSEEvent;
        setEvents((prev) => {
          if (prev.some((e) => e.id === evt.id)) return prev;
          return [...prev, evt].slice(-500);
        });
        const agent = agentNameFromEvent(evt.name);
        if (agent) {
          setActiveAgent({
            name: agent,
            startedAt: Date.now(),
            traceId: evt.trace_id,
          });
          if (agentTimer.current) clearTimeout(agentTimer.current);
          agentTimer.current = setTimeout(() => setActiveAgent(null), 2500);
        }
      } catch {
        // ignore
      }
    };
    return () => es.close();
  }, [projectId]);

  function applyFrame(frame: WsFrame) {
    switch (frame.type) {
      case "conflict": {
        const c = frame.payload as unknown as Conflict;
        setState((prev) => {
          const idx = prev.conflicts.findIndex((x) => x.id === c.id);
          const next = prev.conflicts.slice();
          if (idx === -1) next.push(c);
          else next[idx] = c;
          return { ...prev, conflicts: next };
        });
        break;
      }
      case "conflicts": {
        const p = frame.payload as unknown as {
          conflicts: Conflict[];
          summary: ConflictSummary;
        };
        setState((prev) => ({
          ...prev,
          conflicts: p.conflicts,
          conflict_summary: p.summary,
        }));
        break;
      }
      case "decision": {
        const d = frame.payload as unknown as Decision;
        setState((prev) => {
          const idx = prev.decisions.findIndex((x) => x.id === d.id);
          const next = prev.decisions.slice();
          if (idx === -1) next.unshift(d);
          else next[idx] = d;
          return { ...prev, decisions: next };
        });
        break;
      }
      case "delivery": {
        const d = frame.payload as unknown as Delivery;
        setState((prev) => ({ ...prev, delivery: d }));
        setDeliveryHistory((prev) => {
          const without = prev.filter((x) => x.id !== d.id);
          return [d, ...without];
        });
        break;
      }
    }
  }

  return (
    <main
      data-testid="console-shell"
      data-stage={stage}
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 280px",
        gridTemplateRows: "88px 1fr auto",
        height: "100vh",
        background: "var(--wg-surface)",
      }}
    >
      <ConsoleHeader
        projectTitle={state.project.title}
        stage={stage}
        hint={hint}
        wsState={wsState}
        activeAgent={activeAgent}
        onToggleDrawer={() => setDrawerOpen((v) => !v)}
        drawerOpen={drawerOpen}
      />

      <section
        data-testid="console-canvas"
        style={{
          gridColumn: "1 / 2",
          gridRow: "2 / 3",
          overflow: "auto",
          borderTop: "1px solid var(--wg-line)",
        }}
      >
        <CanvasRouter
          projectId={projectId}
          stage={stage}
          state={state}
          deliveryHistory={deliveryHistory}
          setState={setState}
          setDeliveryHistory={setDeliveryHistory}
        />
      </section>

      <aside
        data-testid="console-graph-sidebar"
        style={{
          gridColumn: "2 / 3",
          gridRow: "1 / 3",
          borderLeft: "1px solid var(--wg-line)",
          overflow: "auto",
          background: "var(--wg-surface-sunk)",
        }}
      >
        <GraphSidebar
          state={state}
          stage={stage}
          activeAgent={activeAgent?.name ?? null}
        />
      </aside>

      <AgentLogDrawer
        open={drawerOpen}
        events={events}
        onClose={() => setDrawerOpen(false)}
      />
    </main>
  );
}

const FLOW_STEPS: { id: Stage; label: string }[] = [
  { id: "intake", label: "Intake" },
  { id: "clarify", label: "Clarify" },
  { id: "plan", label: "Plan" },
  { id: "conflict", label: "Decide" },
  { id: "delivery", label: "Deliver" },
];

function flowStatus(
  current: Stage,
  step: Stage,
): "done" | "active" | "pending" {
  const order: Stage[] = ["intake", "clarify", "plan", "conflict", "delivery"];
  if (current === "done") return "done";
  const ci = order.indexOf(current);
  const si = order.indexOf(step);
  if (si < ci) return "done";
  if (si === ci) return "active";
  return "pending";
}

function ConsoleHeader({
  projectTitle,
  stage,
  hint,
  wsState,
  activeAgent,
  onToggleDrawer,
  drawerOpen,
}: {
  projectTitle: string;
  stage: Stage;
  hint: string;
  wsState: "connecting" | "open" | "closed";
  activeAgent: ActiveAgent | null;
  onToggleDrawer: () => void;
  drawerOpen: boolean;
}) {
  return (
    <header
      style={{
        gridColumn: "1 / 3",
        gridRow: "1 / 2",
        display: "grid",
        gridTemplateRows: "auto auto",
        padding: "12px 20px 10px",
        gap: 10,
        borderBottom: "1px solid var(--wg-line)",
        background: "var(--wg-surface-raised)",
      }}
    >
      {/* Row 1: title + stage pill + hint + ws + toggle */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          minWidth: 0,
        }}
      >
        <span className="wg-dot" aria-hidden style={{ flexShrink: 0 }} />
        <div
          style={{
            fontSize: 14,
            fontWeight: 600,
            letterSpacing: "0.01em",
            flexShrink: 0,
            maxWidth: 320,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={projectTitle}
        >
          {projectTitle}
        </div>
        <div
          data-testid="stage-label"
          style={{
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color:
              stage === "done" ? "var(--wg-ok)" : "var(--wg-accent)",
            padding: "3px 10px",
            border: `1px solid ${
              stage === "done" ? "var(--wg-ok)" : "var(--wg-accent)"
            }`,
            borderRadius: 10,
            background:
              stage === "done"
                ? "rgba(77, 122, 74, 0.08)"
                : "var(--wg-accent-soft)",
            flexShrink: 0,
            fontWeight: 600,
          }}
        >
          {stage}
        </div>
        <div
          style={{
            fontSize: 13,
            color: "var(--wg-ink-soft)",
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {hint}
        </div>
        <button
          data-testid="toggle-agent-log"
          onClick={onToggleDrawer}
          aria-pressed={drawerOpen}
          style={{
            padding: "6px 10px",
            border: "1px solid var(--wg-line)",
            background: drawerOpen ? "var(--wg-surface-sunk)" : "transparent",
            borderRadius: "var(--wg-radius-sm)",
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            cursor: "pointer",
            color: "var(--wg-ink)",
            flexShrink: 0,
          }}
        >
          {drawerOpen ? "Hide log" : "Agent log"}
        </button>
        <span
          aria-label={`ws ${wsState}`}
          title={`websocket ${wsState}`}
          style={{
            width: 8,
            height: 8,
            borderRadius: 4,
            flexShrink: 0,
            background:
              wsState === "open"
                ? "var(--wg-ok)"
                : wsState === "connecting"
                  ? "var(--wg-amber)"
                  : "var(--wg-ink-faint)",
          }}
        />
      </div>

      {/* Row 2: flow strip + active agent */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          minWidth: 0,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontFamily: "var(--wg-font-mono)",
            fontSize: 11,
            flex: 1,
            minWidth: 0,
            overflow: "hidden",
          }}
        >
          {FLOW_STEPS.map((step, i) => {
            const status = flowStatus(stage, step.id);
            const color =
              status === "done"
                ? "var(--wg-ok)"
                : status === "active"
                  ? "var(--wg-accent)"
                  : "var(--wg-ink-faint)";
            return (
              <span
                key={step.id}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  flexShrink: 0,
                }}
              >
                <span
                  aria-hidden
                  className={status === "active" ? "wg-pulse" : undefined}
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 3,
                    background: color,
                    flexShrink: 0,
                  }}
                />
                <span style={{ color }}>{step.label}</span>
                {i < FLOW_STEPS.length - 1 ? (
                  <span
                    style={{
                      color: "var(--wg-line)",
                      margin: "0 2px",
                    }}
                  >
                    →
                  </span>
                ) : null}
              </span>
            );
          })}
        </div>
        {activeAgent ? (
          <div
            data-testid="active-agent-badge"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "4px 10px",
              border: "1px solid var(--wg-accent)",
              borderRadius: 12,
              fontSize: 12,
              background: "var(--wg-accent-soft)",
              color: "var(--wg-accent)",
              fontWeight: 600,
              flexShrink: 0,
            }}
          >
            <span
              className="wg-dot wg-pulse"
              style={{ flexShrink: 0 }}
              aria-hidden
            />
            {activeAgent.name} thinking…
            {activeAgent.traceId ? (
              <span
                style={{
                  fontFamily: "var(--wg-font-mono)",
                  fontWeight: 400,
                  color: "var(--wg-ink-faint)",
                  fontSize: 10,
                }}
              >
                {activeAgent.traceId.slice(0, 8)}
              </span>
            ) : null}
          </div>
        ) : (
          <div
            style={{
              fontFamily: "var(--wg-font-mono)",
              fontSize: 11,
              color: "var(--wg-ink-faint)",
              flexShrink: 0,
            }}
          >
            idle
          </div>
        )}
      </div>
    </header>
  );
}
