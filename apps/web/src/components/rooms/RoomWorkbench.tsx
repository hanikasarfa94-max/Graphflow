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

import { useRoomKnowledge } from "@/hooks/useRoomKnowledge";
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
]);

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
            style={chipStyle}
            onClick={() => addPanel("requests", t("chipRequests"))}
          >
            ＋{t("chipRequests")}
          </button>
          <button
            style={chipStyle}
            onClick={() => addPanel("knowledge", t("chipKnowledge"))}
          >
            ＋{t("chipKnowledge")}
          </button>
          {(
            [
              ["tasks", t("chipTasks")],
              ["skills", t("chipSkills")],
              ["workflow", t("chipWorkflow")],
            ] as Array<[PanelKind, string]>
          ).map(([kind, title]) => (
            <button
              key={kind}
              style={chipDisabledStyle}
              title={t("comingSoon")}
              onClick={() => addPanel(kind, title)}
            >
              ＋{title}
            </button>
          ))}
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
  // Inert panels — empty-state for vocabulary establishment.
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

  if (knowledge.loading && knowledge.items.length === 0) {
    return (
      <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
        {t("knowledgeLoading")}
      </p>
    );
  }
  if (knowledge.error) {
    return (
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
  }
  if (knowledge.items.length === 0) {
    return (
      <p style={{ fontSize: 12, color: "var(--wg-ink-soft)", margin: 0 }}>
        {t("knowledgeEmpty")}
      </p>
    );
  }
  return (
    <>
      {knowledge.items.map((item) => {
        const status = item.status ?? "";
        const meta = `${item.source_kind}${
          status ? ` · ${status}` : ""
        }`;
        // KB items don't render inline in the room timeline today
        // (they're cell-scoped, not room-scoped) so the PanelItem
        // wraps a link to the canonical KB detail page rather than
        // a scrollToEntity. Click → drop into /kb/<id>.
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
      })}
    </>
  );
}
