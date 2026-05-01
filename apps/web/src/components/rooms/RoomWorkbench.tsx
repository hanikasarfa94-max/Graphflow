"use client";

// RoomWorkbench — port of the prototype's right-side `工具栏` (App.tsx
// `Workbench` lines 349-434). Configurable area for projection panels:
//   * Three layout modes: grid / vertical / focus.
//   * Additive chip shelf — `+协同请求` (Requests) / `+任务中心` /
//     `+知识记忆` / `+技能图谱` / `+工作流`.
//   * Per-panel focus + close + drag-rearrange (in-memory only).
//
// This slice ships the shell + Requests panel functional. Other chips
// add inert panels with "coming soon" empty state, establishing the
// projection vocabulary without faking content.

import { useCallback, useMemo, useState, type CSSProperties } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { useProjectMembers } from "@/hooks/useProjectMembers";
import { useRoomKnowledge } from "@/hooks/useRoomKnowledge";
import { useRoomTasks } from "@/hooks/useRoomTasks";
import type { UseRoomTimelineResult } from "@/hooks/useRoomTimeline";

import { PanelItem } from "./PanelItem";
import {
  WorkbenchPanel,
  type PanelDef,
  type PanelKind,
} from "./WorkbenchPanel";

type Mode = "grid" | "vertical" | "focus";

interface Props {
  projectId: string;
  timeline: UseRoomTimelineResult;
  // Caller controls the open/close state of the workbench (the
  // RoomShell owns it so the rail toggle and the layout dance live
  // in one place, like the prototype's setToolsOpen).
  open: boolean;
  onClose: () => void;
}

function makePanelId(kind: PanelKind): string {
  return `${kind}-${Date.now().toString(36)}`;
}

const headStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "10px 12px",
  borderBottom: "1px solid var(--wg-line)",
  background: "#fff",
};

const modeBtnStyle = (active: boolean): CSSProperties => ({
  padding: "4px 8px",
  fontSize: 12,
  border: "1px solid var(--wg-line)",
  borderRadius: 3,
  background: active ? "var(--wg-accent)" : "#fff",
  color: active ? "#fff" : "var(--wg-ink-soft)",
  cursor: "pointer",
});

const chipStyle: CSSProperties = {
  padding: "4px 10px",
  fontSize: 12,
  border: "1px dashed var(--wg-line)",
  borderRadius: 12,
  background: "#fff",
  color: "var(--wg-ink-soft)",
  cursor: "pointer",
};

const chipDisabledStyle: CSSProperties = {
  ...chipStyle,
  cursor: "not-allowed",
  opacity: 0.6,
};

const FUNCTIONAL_KINDS: ReadonlySet<PanelKind> = new Set([
  "requests",
  "knowledge",
  "tasks",
  "skills",
  "workflow",
]);

const tasksScopePillStyle = (active: boolean): CSSProperties => ({
  padding: "2px 10px",
  fontSize: 11,
  fontFamily: "var(--wg-font-mono)",
  border: `1px solid ${active ? "var(--wg-accent)" : "var(--wg-line)"}`,
  borderRadius: 999,
  background: active ? "var(--wg-accent-soft)" : "#fff",
  color: active ? "var(--wg-accent)" : "var(--wg-ink-soft)",
  cursor: "pointer",
});

export function RoomWorkbench({ projectId, timeline, open, onClose }: Props) {
  const t = useTranslations("stream.workbench");

  const initialPanels: PanelDef[] = useMemo(
    () => [
      {
        id: makePanelId("requests"),
        kind: "requests",
        title: t("chipRequests"),
        focus: true,
      },
    ],
    // initial only — chip clicks add more; mode change doesn't mutate.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  const [panels, setPanels] = useState<PanelDef[]>(initialPanels);
  const [mode, setMode] = useState<Mode>("grid");
  const [draggingId, setDraggingId] = useState<string | null>(null);

  const focusPanel = useCallback((id: string) => {
    setPanels((prev) =>
      prev.map((p) => ({ ...p, focus: p.id === id })),
    );
  }, []);

  const closePanel = useCallback((id: string) => {
    setPanels((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const movePanel = useCallback(
    (targetId: string) => {
      if (!draggingId || draggingId === targetId) return;
      setPanels((prev) => {
        const next = [...prev];
        const from = next.findIndex((p) => p.id === draggingId);
        const to = next.findIndex((p) => p.id === targetId);
        if (from < 0 || to < 0) return prev;
        const [item] = next.splice(from, 1);
        next.splice(to, 0, item);
        return next;
      });
    },
    [draggingId],
  );

  const addPanel = useCallback(
    (kind: PanelKind, title: string) => {
      setPanels((prev) => {
        const existing = prev.find((p) => p.kind === kind);
        if (existing) {
          return prev.map((p) => ({ ...p, focus: p.id === existing.id }));
        }
        return [
          { id: makePanelId(kind), kind, title, focus: true },
          ...prev.map((p) => ({ ...p, focus: false })),
        ];
      });
    },
    [],
  );

  if (!open) return null;

  const gridStyle: CSSProperties = {
    display: "grid",
    gridTemplateColumns:
      mode === "vertical" ? "1fr" : "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 10,
    padding: 10,
    overflow: "auto",
    flex: 1,
  };

  return (
    <aside
      className="tools"
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        background: "var(--wg-bg-soft, #f8f9fa)",
        borderLeft: "1px solid var(--wg-line)",
      }}
    >
      <div className="toolsHead" style={headStyle}>
        <strong style={{ fontSize: 13 }}>{t("title")}</strong>
        <small
          style={{ color: "var(--wg-ink-soft)", fontSize: 11 }}
        >
          {t("subtitle")}
        </small>
        <span
          className="pill"
          style={{
            padding: "1px 7px",
            fontSize: 10,
            borderRadius: 10,
            background: "#e3f0ff",
            color: "#0049a8",
          }}
        >
          {t("private")}
        </span>
        <div style={{ flex: 1 }} />
        <div className="modeGroup" style={{ display: "flex", gap: 2 }}>
          {(["grid", "vertical", "focus"] as Mode[]).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              style={modeBtnStyle(mode === m)}
              aria-pressed={mode === m}
            >
              {t(`mode.${m}`)}
            </button>
          ))}
        </div>
        <button
          className="closeBtn"
          onClick={onClose}
          aria-label={t("close")}
          style={{
            background: "transparent",
            border: "none",
            cursor: "pointer",
            fontSize: 18,
            color: "var(--wg-ink-soft)",
            padding: "0 4px",
          }}
        >
          ×
        </button>
      </div>
      <div className="toolsBody" style={{ display: "flex", flexDirection: "column", flex: 1 }}>
        <div
          className="toolShelf"
          style={{
            display: "flex",
            gap: 6,
            padding: "8px 10px",
            borderBottom: "1px solid var(--wg-line)",
            flexWrap: "wrap",
          }}
        >
          <button
            data-testid="workbench-chip-requests"
            style={chipStyle}
            onClick={() => addPanel("requests", t("chipRequests"))}
          >
            ＋{t("chipRequests")}
          </button>
          <button
            data-testid="workbench-chip-knowledge"
            style={chipStyle}
            onClick={() => addPanel("knowledge", t("chipKnowledge"))}
          >
            ＋{t("chipKnowledge")}
          </button>
          <button
            data-testid="workbench-chip-tasks"
            style={chipStyle}
            onClick={() => addPanel("tasks", t("chipTasks"))}
          >
            ＋{t("chipTasks")}
          </button>
          <button
            data-testid="workbench-chip-skills"
            style={chipStyle}
            onClick={() => addPanel("skills", t("chipSkills"))}
          >
            ＋{t("chipSkills")}
          </button>
          <button
            data-testid="workbench-chip-workflow"
            style={chipStyle}
            onClick={() => addPanel("workflow", t("chipWorkflow"))}
          >
            ＋{t("chipWorkflow")}
          </button>
        </div>
        <div className={"panelGrid"} style={gridStyle}>
          {panels.map((panel) => (
            <WorkbenchPanel
              key={panel.id}
              panel={panel}
              hidden={mode === "focus" && !panel.focus}
              onFocus={() => focusPanel(panel.id)}
              onClose={() => closePanel(panel.id)}
              onDragStart={() => setDraggingId(panel.id)}
              onDragEnd={() => setDraggingId(null)}
              onDrop={() => movePanel(panel.id)}
            >
              {renderPanelBody(panel.kind, projectId, timeline, t)}
            </WorkbenchPanel>
          ))}
        </div>
      </div>
    </aside>
  );
}

// renderPanelBody — single dispatch from PanelKind to projection
// renderer. Functional kinds derive from the timeline state; the
// rest show empty-state copy so the chip vocabulary lands now and
// the renderers slot in incrementally.
function renderPanelBody(
  kind: PanelKind,
  projectId: string,
  timeline: UseRoomTimelineResult,
  t: ReturnType<typeof useTranslations>,
): React.ReactNode {
  if (kind === "requests") {
    return <RequestsPanelBody timeline={timeline} t={t} />;
  }
  if (kind === "knowledge") {
    return <KnowledgePanelBody projectId={projectId} t={t} />;
  }
  if (kind === "tasks") {
    return <TasksPanelBody projectId={projectId} t={t} />;
  }
  if (kind === "skills") {
    return <SkillsPanelBody projectId={projectId} t={t} />;
  }
  if (kind === "workflow") {
    return <WorkflowPanelBody t={t} />;
  }
  // Inert fallback — every functional kind already returns above.
  return (
    <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
      {t("comingSoonBody")}
    </p>
  );
}

function RequestsPanelBody({
  timeline,
  t,
}: {
  timeline: UseRoomTimelineResult;
  t: ReturnType<typeof useTranslations>;
}) {
  const { pendingSuggestions, accept, dismiss } = timeline;

  if (pendingSuggestions.length === 0) {
    return (
      <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
        {t("requestsEmpty")}
      </p>
    );
  }

  return (
    <>
      {pendingSuggestions.map((s) => {
        if (s.kind !== "im_suggestion") return null;
        const proposal = s.proposal as Record<string, unknown> | null;
        const summary =
          (proposal && typeof proposal.summary === "string"
            ? (proposal.summary as string)
            : null) ??
          s.reasoning ??
          t("untitledSuggestion");
        const meta = `${s.kind_suggestion} · ${
          typeof s.confidence === "number"
            ? Math.round(s.confidence * 100) + "%"
            : "?"
        }`;
        return (
          <PanelItem
            key={s.id}
            title={summary}
            meta={meta}
            entityRef={{ kind: "im_suggestion", id: s.id }}
            actions={
              <>
                <button
                  type="button"
                  data-testid="workbench-suggestion-accept"
                  onClick={() => void accept(s.id)}
                  style={{
                    padding: "3px 10px",
                    fontSize: 12,
                    border: "1px solid var(--wg-accent)",
                    borderRadius: 3,
                    background: "var(--wg-accent)",
                    color: "#fff",
                    cursor: "pointer",
                  }}
                >
                  {t("accept")}
                </button>
                <button
                  type="button"
                  data-testid="workbench-suggestion-dismiss"
                  onClick={() => void dismiss(s.id)}
                  style={{
                    padding: "3px 10px",
                    fontSize: 12,
                    border: "1px solid var(--wg-line)",
                    borderRadius: 3,
                    background: "#fff",
                    color: "var(--wg-ink-soft)",
                    cursor: "pointer",
                  }}
                >
                  {t("dismiss")}
                </button>
              </>
            }
          />
        );
      })}
    </>
  );
}

// KnowledgePanelBody — projects the project's KB items into the
// workbench. Cell-scoped, not room-scoped (per the projection
// thesis: cell is the memory boundary). Each PanelItem links to
// the existing /projects/{id}/kb/{itemId} detail page so the user
// can drop into the canonical KB surface.
function KnowledgePanelBody({
  projectId,
  t,
}: {
  projectId: string;
  t: ReturnType<typeof useTranslations>;
}) {
  const knowledge = useRoomKnowledge({ projectId });
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return knowledge.items;
    return knowledge.items.filter((item) => {
      const haystack = [
        item.summary ?? "",
        item.source_kind ?? "",
        // Title isn't always set (ingests use summary) — include both
        // anyway so the search feels comprehensive.
        (item as { title?: string | null }).title ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [knowledge.items, query]);

  // Search input is always visible — port of prototype App.tsx:490.
  // Sits above whichever state (loading / error / empty / list) renders.
  const search = (
    <input
      type="text"
      data-testid="knowledge-search"
      value={query}
      onChange={(e) => setQuery(e.target.value)}
      placeholder={t("knowledgeSearchPlaceholder")}
      style={{
        width: "100%",
        padding: "5px 8px",
        marginBottom: 8,
        fontSize: 12,
        border: "1px solid var(--wg-line)",
        borderRadius: 3,
        fontFamily: "var(--wg-font-sans)",
      }}
    />
  );

  let body: React.ReactNode;
  if (knowledge.loading && knowledge.items.length === 0) {
    body = (
      <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
        {t("knowledgeLoading")}
      </p>
    );
  } else if (knowledge.error) {
    body = (
      <p
        style={{
          fontSize: 12,
          color: "var(--wg-warn, #b94a48)",
          margin: 0,
        }}
      >
        {knowledge.error}
      </p>
    );
  } else if (knowledge.items.length === 0) {
    body = (
      <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
        {t("knowledgeEmpty")}
      </p>
    );
  } else if (filtered.length === 0) {
    // Topical-search empty state distinct from "no items at all" so
    // the user knows the search excluded matches rather than the cell
    // being empty.
    body = (
      <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
        {t("knowledgeSearchEmpty")}
      </p>
    );
  } else {
    body = filtered.map((item) => {
      const status = item.status ?? "";
      const meta = `${item.source_kind}${status ? ` · ${status}` : ""}`;
      return (
        <Link
          key={item.id}
          href={`/projects/${projectId}/kb/${item.id}`}
          style={{ textDecoration: "none" }}
        >
          <PanelItem
            title={item.summary || t("knowledgeUntitled")}
            meta={meta}
          />
        </Link>
      );
    });
  }

  return (
    <>
      {search}
      {body}
    </>
  );
}

// TasksPanelBody — projects the viewer's personal-scope tasks for
// this project. Personal tasks are owner-only by design (matches
// the KB tree's personal-items rule), so this panel acts as a
// private draft surface inside the workbench. The +New affordance
// rides POST /api/projects/{id}/tasks — same route the membrane's
// promote-to-plan flow consumes from.
function TasksPanelBody({
  projectId,
  t,
}: {
  projectId: string;
  t: ReturnType<typeof useTranslations>;
}) {
  const tasksState = useRoomTasks({ projectId });
  const [drafting, setDrafting] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  // Prototype-port: 我的 / 团队 scope toggle (App.tsx:480). 我的 is
  // functional today (personal-scope tasks via fetchPersonalTasks).
  // 团队 is inert pending a list-plan-tasks endpoint — clicking it
  // surfaces a "coming soon" hint inline instead of swapping the list,
  // matching the "vocabulary first" rule we use across workbench chips
  // and the composer plus-menu.
  const [scope, setScope] = useState<"mine" | "team">("mine");

  const submit = useCallback(async () => {
    const title = draftTitle.trim();
    if (!title) return;
    const created = await tasksState.create({ title });
    if (created) {
      setDraftTitle("");
      setDrafting(false);
    }
  }, [draftTitle, tasksState]);

  const teamComingSoon = scope === "team";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", gap: 4 }}>
        <button
          type="button"
          data-testid="tasks-scope-mine"
          onClick={() => setScope("mine")}
          aria-pressed={scope === "mine"}
          style={tasksScopePillStyle(scope === "mine")}
        >
          {t("tasksScopeMine")}
        </button>
        <button
          type="button"
          data-testid="tasks-scope-team"
          onClick={() => setScope("team")}
          aria-pressed={scope === "team"}
          title={t("tasksScopeTeamComingSoon")}
          style={tasksScopePillStyle(scope === "team")}
        >
          {t("tasksScopeTeam")}
        </button>
      </div>
      {teamComingSoon ? (
        <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
          {t("tasksScopeTeamComingSoon")}
        </p>
      ) : null}
      {!teamComingSoon && (
      <>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        {!drafting ? (
          <button
            type="button"
            data-testid="workbench-tasks-new"
            onClick={() => setDrafting(true)}
            style={{
              padding: "3px 10px",
              fontSize: 12,
              border: "1px solid var(--wg-line)",
              borderRadius: 3,
              background: "#fff",
              color: "var(--wg-ink-soft)",
              cursor: "pointer",
            }}
          >
            ＋{t("tasksNew")}
          </button>
        ) : (
          <div style={{ display: "flex", gap: 6, width: "100%" }}>
            <input
              type="text"
              data-testid="workbench-tasks-input"
              value={draftTitle}
              autoFocus
              onChange={(e) => setDraftTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submit();
                if (e.key === "Escape") {
                  setDrafting(false);
                  setDraftTitle("");
                }
              }}
              placeholder={t("tasksDraftPlaceholder")}
              style={{
                flex: 1,
                padding: "4px 8px",
                fontSize: 12,
                border: "1px solid var(--wg-line)",
                borderRadius: 3,
              }}
            />
            <button
              type="button"
              data-testid="workbench-tasks-submit"
              onClick={() => void submit()}
              disabled={!draftTitle.trim() || tasksState.creating}
              style={{
                padding: "3px 10px",
                fontSize: 12,
                border: "1px solid var(--wg-accent)",
                borderRadius: 3,
                background: "var(--wg-accent)",
                color: "#fff",
                cursor: "pointer",
                opacity: !draftTitle.trim() || tasksState.creating ? 0.5 : 1,
              }}
            >
              {t("tasksDraftSubmit")}
            </button>
            <button
              type="button"
              onClick={() => {
                setDrafting(false);
                setDraftTitle("");
              }}
              style={{
                padding: "3px 8px",
                fontSize: 12,
                border: "1px solid var(--wg-line)",
                borderRadius: 3,
                background: "#fff",
                color: "var(--wg-ink-soft)",
                cursor: "pointer",
              }}
              aria-label={t("tasksDraftCancel")}
            >
              ×
            </button>
          </div>
        )}
      </div>
      {tasksState.loading && tasksState.tasks.length === 0 ? (
        <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
          {t("tasksLoading")}
        </p>
      ) : tasksState.error ? (
        <p
          style={{
            fontSize: 12,
            color: "var(--wg-warn, #b94a48)",
            margin: 0,
          }}
        >
          {tasksState.error}
        </p>
      ) : tasksState.tasks.length === 0 ? (
        <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
          {t("tasksEmpty")}
        </p>
      ) : (
        <>
          {tasksState.tasks.map((task) => {
            const meta = `${task.status}${
              task.assignee_role && task.assignee_role !== "unknown"
                ? ` · ${task.assignee_role}`
                : ""
            }`;
            // Personal tasks have no inline timeline projection today
            // (no manual_task candidate kind on the membrane yet), so
            // the PanelItem is a passive row. When the membrane learns
            // manual_task, source_message_id will let it scrollToEntity
            // back to the originating message instead.
            return (
              <PanelItem
                key={task.id}
                title={task.title || t("tasksUntitled")}
                meta={meta}
              />
            );
          })}
        </>
      )}
      </>
      )}
    </div>
  );
}

// SkillsPanelBody — port of prototype App.tsx:496. Lists project
// members with their declared skill_tags as the meta line. The
// prototype's `.graphBox` (an empty visual placeholder for a future
// network rendering) ports as a small SVG so the panel doesn't open
// to a wall of text — a low-fidelity placeholder is more honest than
// a large empty div.
function SkillsPanelBody({
  projectId,
  t,
}: {
  projectId: string;
  t: ReturnType<typeof useTranslations>;
}) {
  const { members, loading, error } = useProjectMembers({ projectId });

  let body: React.ReactNode;
  if (loading && members.length === 0) {
    body = (
      <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
        {t("skillsLoading")}
      </p>
    );
  } else if (error) {
    body = (
      <p
        style={{
          fontSize: 12,
          color: "var(--wg-warn, #b94a48)",
          margin: 0,
        }}
      >
        {error}
      </p>
    );
  } else if (members.length === 0) {
    body = (
      <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
        {t("skillsEmpty")}
      </p>
    );
  } else {
    body = members.map((m) => {
      const tags = m.skill_tags ?? [];
      const meta = `${m.role}${
        tags.length > 0 ? ` · ${tags.join(", ")}` : ""
      }`;
      const title = m.display_name || m.username || m.user_id;
      return <PanelItem key={m.user_id} title={title} meta={meta} />;
    });
  }

  return (
    <>
      <SkillsGraphPlaceholder t={t} />
      {body}
    </>
  );
}

function SkillsGraphPlaceholder({
  t,
}: {
  t: ReturnType<typeof useTranslations>;
}) {
  return (
    <div
      role="img"
      aria-label={t("skillsGraphAlt")}
      style={{
        position: "relative",
        height: 80,
        marginBottom: 8,
        background: "var(--wg-bg-soft, #f7f8fa)",
        border: "1px dashed var(--wg-line)",
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      <svg
        viewBox="0 0 240 80"
        preserveAspectRatio="xMidYMid meet"
        style={{ width: "100%", height: "100%" }}
      >
        {/* Three nodes + two edges — minimal "skill atlas" hint. */}
        <line x1="50" y1="40" x2="120" y2="40" stroke="var(--wg-line)" strokeWidth="1" />
        <line x1="120" y1="40" x2="190" y2="40" stroke="var(--wg-line)" strokeWidth="1" />
        <circle cx="50" cy="40" r="10" fill="var(--wg-accent)" opacity="0.55" />
        <circle cx="120" cy="40" r="14" fill="var(--wg-accent)" opacity="0.85" />
        <circle cx="190" cy="40" r="10" fill="var(--wg-accent)" opacity="0.55" />
      </svg>
      <span
        style={{
          position: "absolute",
          bottom: 4,
          right: 6,
          fontSize: 10,
          color: "var(--wg-ink-soft)",
          fontFamily: "var(--wg-font-mono)",
          opacity: 0.7,
        }}
      >
        {t("skillsGraphHint")}
      </span>
    </div>
  );
}

// WorkflowPanelBody — port of prototype App.tsx:514. Hardcoded 4-stage
// DAG (需求收集 → 方案设计 → 评审确认 → 开发实现) with one stage
// marked active. Dynamic stage selection (driven by real project
// state) lands when the workflow data model exists; today this is
// vocabulary establishment matching the prototype rather than a
// data-driven view.
function WorkflowPanelBody({
  t,
}: {
  t: ReturnType<typeof useTranslations>;
}) {
  type StageStatus = "done" | "active" | "pending";
  const stages: { key: string; status: StageStatus }[] = [
    { key: "requirements", status: "done" },
    { key: "design", status: "active" },
    { key: "review", status: "pending" },
    { key: "build", status: "pending" },
  ];

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        flexWrap: "wrap",
      }}
    >
      {stages.map((stage, idx) => (
        <span
          key={stage.key}
          style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
        >
          <div style={workflowNodeStyle(stage.status)}>
            <strong style={{ fontSize: 12, color: "var(--wg-ink)" }}>
              {t(`workflowStage.${stage.key}.label`)}
            </strong>
            <small
              style={{
                fontSize: 10,
                color: "var(--wg-ink-soft)",
                fontFamily: "var(--wg-font-mono)",
              }}
            >
              {t(`workflowStatus.${stage.status}`)}
            </small>
          </div>
          {idx < stages.length - 1 && (
            <span
              aria-hidden
              style={{
                color: "var(--wg-ink-soft)",
                fontSize: 14,
              }}
            >
              →
            </span>
          )}
        </span>
      ))}
    </div>
  );
}

function workflowNodeStyle(
  status: "done" | "active" | "pending",
): CSSProperties {
  const palette = {
    done: { bg: "var(--wg-accent-soft)", border: "var(--wg-accent)" },
    active: { bg: "#fff8e6", border: "var(--wg-warn, #d99500)" },
    pending: { bg: "#fff", border: "var(--wg-line)" },
  }[status];
  return {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-start",
    gap: 2,
    padding: "6px 10px",
    minWidth: 90,
    background: palette.bg,
    border: `1px solid ${palette.border}`,
    borderRadius: 4,
  };
}
