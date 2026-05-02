"use client";

// v-next Workbench — port of prototype App.tsx:349-433.
//
// Right column: tools head ([工具栏][私有][grid/纵向/聚焦][×]) + tools
// body (toolShelf 5 chips + panelGrid). Panel kinds: tasks / knowledge /
// skills / requests / workflow.
//
// Phase 3 (E-9): panel composition is now persisted per stream_kind
// via /api/vnext/prefs. Defaults match the prototype when nothing is
// stored. Add/remove/reorder fires updateVNextPrefs in the background
// so the layout survives reload.
//
// Phase 2 chrome remains:
//   * full layout chrome (head + shelf + grid + modes + drag-reorder + close)
//   * panel renderers as static placeholders matching the prototype's
//     visual shape — real data wiring per panel kind lands as separate
//     follow-up slices (each panel kind has its own backend dependency).
//
// Workflow panel kept inert per 04-28 memo + spec §12 DEVIATE: stages
// are derived from graph on demand, so the static 4-stage DAG is a
// visual placeholder. We render it because the prototype does, with a
// hint that says "stages derived live in production".

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import {
  createPersonalTask,
  fetchPersonalTasks,
  fetchProjectMembers,
  fetchVNextPrefs,
  listKbNotes,
  listRoutedInbox,
  updateVNextPrefs,
  type KbNote,
  type PersonalTask,
  type ProjectMember,
  type RoutingSignal,
  type VNextPanelKind,
  type VNextStreamKind,
} from "@/lib/api";

import styles from "./Workbench.module.css";

type PanelKind = VNextPanelKind;
type PanelMode = "grid" | "vertical" | "focus";

// Fallback when prefs haven't hydrated yet — the prototype's default
// includes the workflow status DAG (the original project status graph
// from legacy-standalone-v6.html line 223). Personal-stream surfaces
// keep the same shape; rooms add 'requests' and skip 'workflow'-only
// modes via the BE defaults.
const DEFAULT_PANELS: PanelKind[] = [
  "tasks",
  "knowledge",
  "skills",
  "workflow",
];

interface Panel {
  id: string;
  kind: PanelKind;
  title: string;
  focus: boolean;
  wide?: boolean;
}

const SHELF_CHIPS: { kind: PanelKind; labelKey: string }[] = [
  { kind: "tasks", labelKey: "wb.chip.tasks" },
  { kind: "knowledge", labelKey: "wb.chip.knowledge" },
  { kind: "requests", labelKey: "wb.chip.requests" },
  { kind: "skills", labelKey: "wb.chip.skills" },
  { kind: "workflow", labelKey: "wb.chip.workflow" },
];

interface Props {
  onClose: () => void;
  // Active stream kind — drives which workbench layout to load. Default
  // 'personal' so the workbench has a sensible composition before a
  // stream is selected.
  streamKind?: VNextStreamKind;
  // Active project — drives the live data fetch for tasks / knowledge /
  // skills / requests panels. Without a project context the panels
  // render their empty-state "pick a project agent" copy.
  activeProjectId?: string | null;
}

function makePanel(
  kind: PanelKind,
  title: string,
  focus: boolean,
): Panel {
  return {
    id: `p-${kind}`,
    kind,
    title,
    focus,
    wide: kind === "workflow",
  };
}

export function Workbench({
  onClose,
  streamKind = "personal",
  activeProjectId = null,
}: Props) {
  const t = useTranslations("shellVNext");
  const [mode, setMode] = useState<PanelMode>("grid");
  const [panels, setPanels] = useState<Panel[]>(() =>
    DEFAULT_PANELS.map((kind, i) =>
      makePanel(kind, t(`wb.title.${kind}` as const), i === 0),
    ),
  );
  const [draggingId, setDraggingId] = useState<string | null>(null);
  // Skip the persistence write that immediately follows hydration —
  // otherwise we'd echo the server's own value back to it on every
  // mount.
  const skipPersistRef = useRef(true);

  // E-9 hydrate from /api/vnext/prefs. Falls back to DEFAULT_PANELS.
  useEffect(() => {
    let cancelled = false;
    skipPersistRef.current = true;
    fetchVNextPrefs()
      .then((p) => {
        if (cancelled) return;
        const stored = p.workbench_layout[streamKind];
        const kinds = stored && stored.length > 0 ? stored : DEFAULT_PANELS;
        setPanels(
          kinds.map((kind, i) =>
            makePanel(kind, t(`wb.title.${kind}` as const), i === 0),
          ),
        );
      })
      .catch(() => {
        // Silent — keep the default composition.
      });
    return () => {
      cancelled = true;
    };
  }, [streamKind, t]);

  // Persist on every panel mutation.
  useEffect(() => {
    if (skipPersistRef.current) {
      // First effect run after hydration is the echo — skip.
      skipPersistRef.current = false;
      return;
    }
    const kinds = panels.map((p) => p.kind);
    void updateVNextPrefs({
      workbench: { stream_kind: streamKind, panels: kinds },
    }).catch(() => {
      // Non-fatal.
    });
  }, [panels, streamKind]);

  function focusPanel(id: string) {
    setPanels((prev) => prev.map((p) => ({ ...p, focus: p.id === id })));
  }

  function closePanel(id: string) {
    setPanels((prev) => prev.filter((p) => p.id !== id));
  }

  function addPanel(kind: PanelKind) {
    setPanels((prev) => {
      const existing = prev.find((p) => p.kind === kind);
      if (existing) {
        // Focus existing rather than duplicate.
        return prev.map((p) => ({ ...p, focus: p.id === existing.id }));
      }
      const next: Panel = {
        id: `p-${kind}-${Date.now()}`,
        kind,
        title: t(`wb.title.${kind}` as const),
        focus: true,
        wide: kind === "workflow",
      };
      return [next, ...prev.map((p) => ({ ...p, focus: false }))];
    });
  }

  function movePanel(targetId: string) {
    if (!draggingId || draggingId === targetId) return;
    setPanels((prev) => {
      const arr = [...prev];
      const from = arr.findIndex((p) => p.id === draggingId);
      const to = arr.findIndex((p) => p.id === targetId);
      if (from < 0 || to < 0) return prev;
      const [item] = arr.splice(from, 1);
      arr.splice(to, 0, item);
      return arr;
    });
  }

  return (
    <aside className={styles.tools} data-testid="vnext-workbench">
      <div className={styles.toolsHead}>
        <strong>{t("wb.head.title")}</strong>
        <small>{t("wb.head.subtitle")}</small>
        <span className={styles.privatePill}>{t("wb.head.privatePill")}</span>
        <div className={styles.spacer} />
        <div className={styles.modeGroup}>
          {(["grid", "vertical", "focus"] as PanelMode[]).map((m) => (
            <button
              key={m}
              type="button"
              className={`${styles.mode} ${mode === m ? styles.modeActive : ""}`}
              onClick={() => setMode(m)}
              data-mode={m}
            >
              {t(`wb.mode.${m}`)}
            </button>
          ))}
        </div>
        <button
          type="button"
          className={styles.closeBtn}
          onClick={onClose}
          aria-label={t("wb.head.close")}
        >
          ×
        </button>
      </div>
      <div className={styles.toolsBody}>
        <div className={styles.toolShelf} data-testid="vnext-workbench-shelf">
          {SHELF_CHIPS.map((chip) => (
            <button
              key={chip.kind}
              type="button"
              className={styles.toolChip}
              onClick={() => addPanel(chip.kind)}
              data-chip-kind={chip.kind}
            >
              ＋ {t(chip.labelKey)}
            </button>
          ))}
        </div>
        <div
          className={`${styles.panelGrid} ${
            mode === "vertical" ? styles.gridVertical : ""
          } ${mode === "focus" ? styles.gridFocus : ""}`}
        >
          {panels.map((p) => (
            <PanelCard
              key={p.id}
              panel={p}
              modeFocus={mode === "focus"}
              activeProjectId={activeProjectId}
              onFocus={() => focusPanel(p.id)}
              onClose={() => closePanel(p.id)}
              onDragStart={() => setDraggingId(p.id)}
              onDragEnd={() => setDraggingId(null)}
              onDrop={() => movePanel(p.id)}
            />
          ))}
        </div>
      </div>
    </aside>
  );
}

function PanelCard({
  panel,
  modeFocus,
  activeProjectId,
  onFocus,
  onClose,
  onDragStart,
  onDragEnd,
  onDrop,
}: {
  panel: Panel;
  modeFocus: boolean;
  activeProjectId: string | null;
  onFocus: () => void;
  onClose: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDrop: () => void;
}) {
  if (modeFocus && !panel.focus) return null;
  return (
    <section
      className={`${styles.panel} ${panel.focus ? styles.panelFocus : ""} ${
        panel.wide ? styles.panelWide : ""
      }`}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      <div className={styles.panelHead}>
        <span className={styles.dragHandle} aria-hidden>
          ⋮⋮
        </span>
        <strong>{panel.title}</strong>
        <div className={styles.panelActions}>
          <button
            type="button"
            className={styles.panelBtn}
            onClick={onFocus}
            aria-label="focus"
          >
            ⌖
          </button>
          <button
            type="button"
            className={styles.panelBtn}
            onClick={onClose}
            aria-label="close"
          >
            ×
          </button>
        </div>
      </div>
      <div className={styles.panelBody}>
        <PanelBody kind={panel.kind} activeProjectId={activeProjectId} />
      </div>
    </section>
  );
}

// PanelBody — kind-specific renderers. Wave 4 swap: tasks / knowledge /
// skills / requests now fetch real data from the relevant BE endpoint
// when an active project context exists. Workflow stays as the static
// stage DAG per spec §12 DEVIATE (stages derived from graph in v2).
function PanelBody({
  kind,
  activeProjectId,
}: {
  kind: PanelKind;
  activeProjectId: string | null;
}) {
  const t = useTranslations("shellVNext");

  if (kind === "tasks") {
    return <TasksPanel activeProjectId={activeProjectId} />;
  }
  if (kind === "knowledge") {
    return <KnowledgePanel activeProjectId={activeProjectId} />;
  }
  if (kind === "skills") {
    return <SkillsPanel activeProjectId={activeProjectId} />;
  }
  if (kind === "requests") {
    return <RequestsPanel />;
  }
  if (kind === "workflow") {
    return (
      <>
        <div className={styles.workflow}>
          <div className={`${styles.wfNode} ${styles.wfDone}`}>
            需求收集
            <br />
            <span>已完成</span>
          </div>
          <span className={styles.wfArrow}>→</span>
          <div className={`${styles.wfNode} ${styles.wfActive}`}>
            方案设计
            <br />
            <span>进行中</span>
          </div>
          <span className={styles.wfArrow}>→</span>
          <div className={styles.wfNode}>
            评审确认
            <br />
            <span>等待中</span>
          </div>
          <span className={styles.wfArrow}>→</span>
          <div className={styles.wfNode}>
            开发实现
            <br />
            <span>未开始</span>
          </div>
        </div>
        <p className={styles.workflowHint}>{t("wb.workflow.hint")}</p>
      </>
    );
  }
  return <PanelItem title={t("wb.unknownKind")} meta="" />;
}

function PanelItem({
  title,
  meta,
  progress,
}: {
  title: string;
  meta: string;
  progress?: number;
}) {
  return (
    <div className={styles.panelItem}>
      <strong>{title}</strong>
      {meta && <small>{meta}</small>}
      {typeof progress === "number" && (
        <div className={styles.progress}>
          <i style={{ width: `${progress}%` }} />
        </div>
      )}
    </div>
  );
}

// ---- Live panels (Wave 4) ----------------------------------------
//
// Each panel below replaces its prototype mock data with a real fetch
// from the corresponding BE endpoint. When there's no active project
// context (general agent / DM / no stream) the panel renders an
// empty-state with a hint so users understand WHY it's empty.

function TasksPanel({ activeProjectId }: { activeProjectId: string | null }) {
  const t = useTranslations("shellVNext");
  const [tasks, setTasks] = useState<PersonalTask[] | null>(null);
  const [scope, setScope] = useState<"mine" | "team">("mine");
  // Inline "+ new task" affordance — matches legacy /projects/[id]/team
  // workbench panel that exposed createPersonalTask. Posts as a personal
  // (private) task; user can promote to plan from the task page.
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState("");

  const refresh = () => {
    if (!activeProjectId) {
      setTasks(null);
      return;
    }
    fetchPersonalTasks(activeProjectId)
      .then((res) => setTasks(res.tasks))
      .catch(() => setTasks([]));
  };
  useEffect(() => {
    refresh();
    // refresh fn captures activeProjectId via closure each render — OK.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProjectId]);

  async function submit() {
    const title = draft.trim();
    if (!title || !activeProjectId || creating) return;
    setCreating(true);
    try {
      await createPersonalTask(activeProjectId, { title });
      setDraft("");
      refresh();
    } catch {
      // surface failure inline; non-fatal
    } finally {
      setCreating(false);
    }
  }

  if (!activeProjectId) {
    return (
      <p className={styles.emptyHint}>{t("wb.tasks.noProject")}</p>
    );
  }

  const list = (tasks ?? []).filter((task) =>
    scope === "mine" ? task.scope === "personal" : task.scope === "plan",
  );

  return (
    <>
      <div className={styles.scopeRow}>
        <button
          type="button"
          className={`${styles.scopePill} ${
            scope === "mine" ? styles.scopePillActive : ""
          }`}
          onClick={() => setScope("mine")}
          data-testid="vnext-wb-tasks-mine"
        >
          {t("wb.tasks.mine")}
        </button>
        <button
          type="button"
          className={`${styles.scopePill} ${
            scope === "team" ? styles.scopePillActive : ""
          }`}
          onClick={() => setScope("team")}
          data-testid="vnext-wb-tasks-team"
        >
          {t("wb.tasks.team")}
        </button>
      </div>
      {scope === "mine" && (
        <div className={styles.taskComposer}>
          <input
            className={styles.panelInput}
            placeholder={t("wb.tasks.newPlaceholder")}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void submit();
              }
            }}
            disabled={creating}
            data-testid="vnext-wb-tasks-new-input"
          />
          <button
            type="button"
            className={styles.taskComposerBtn}
            onClick={() => void submit()}
            disabled={!draft.trim() || creating}
            data-testid="vnext-wb-tasks-new-submit"
          >
            ＋
          </button>
        </div>
      )}
      {tasks === null ? (
        <p className={styles.emptyHint}>{t("wb.loading")}</p>
      ) : list.length === 0 ? (
        <p className={styles.emptyHint}>
          {scope === "mine"
            ? t("wb.tasks.emptyMine")
            : t("wb.tasks.emptyTeam")}
        </p>
      ) : (
        list.map((task) => (
          <PanelItem
            key={task.id}
            title={task.title}
            meta={
              (task.assignee_role ? `${task.assignee_role} · ` : "") +
              task.status
            }
          />
        ))
      )}
    </>
  );
}

function KnowledgePanel({
  activeProjectId,
}: {
  activeProjectId: string | null;
}) {
  const t = useTranslations("shellVNext");
  const [items, setItems] = useState<KbNote[] | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!activeProjectId) {
      setItems(null);
      return;
    }
    listKbNotes(activeProjectId)
      .then((res) => setItems(res.items))
      .catch(() => setItems([]));
  }, [activeProjectId]);

  if (!activeProjectId) {
    return <p className={styles.emptyHint}>{t("wb.knowledge.noProject")}</p>;
  }

  const filtered = (items ?? []).filter((it) => {
    if (!query.trim()) return true;
    const q = query.toLowerCase();
    return (
      it.title.toLowerCase().includes(q) ||
      it.content_md.toLowerCase().includes(q)
    );
  });

  return (
    <>
      <input
        className={styles.panelInput}
        placeholder={t("wb.knowledge.searchPlaceholder")}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        data-testid="vnext-wb-knowledge-search"
      />
      {items === null ? (
        <p className={styles.emptyHint}>{t("wb.loading")}</p>
      ) : filtered.length === 0 ? (
        <p className={styles.emptyHint}>{t("wb.knowledge.empty")}</p>
      ) : (
        filtered
          .slice(0, 12)
          .map((it) => (
            <PanelItem
              key={it.id}
              title={it.title}
              meta={`${it.scope} · ${it.status}`}
            />
          ))
      )}
    </>
  );
}

function SkillsPanel({ activeProjectId }: { activeProjectId: string | null }) {
  const t = useTranslations("shellVNext");
  const [members, setMembers] = useState<ProjectMember[] | null>(null);

  useEffect(() => {
    if (!activeProjectId) {
      setMembers(null);
      return;
    }
    fetchProjectMembers(activeProjectId)
      .then((res) => setMembers(res))
      .catch(() => setMembers([]));
  }, [activeProjectId]);

  return (
    <>
      <div className={styles.graphBox} aria-hidden />
      {!activeProjectId ? (
        <p className={styles.emptyHint}>{t("wb.skills.noProject")}</p>
      ) : members === null ? (
        <p className={styles.emptyHint}>{t("wb.loading")}</p>
      ) : members.length === 0 ? (
        <p className={styles.emptyHint}>{t("wb.skills.empty")}</p>
      ) : (
        members.slice(0, 8).map((m) => (
          <PanelItem
            key={m.user_id}
            title={m.display_name ?? m.username ?? m.user_id.slice(0, 8)}
            meta={
              (m.skill_tags && m.skill_tags.length > 0
                ? m.skill_tags.join(", ")
                : m.role ?? "member")
            }
          />
        ))
      )}
    </>
  );
}

function RequestsPanel() {
  const t = useTranslations("shellVNext");
  const [signals, setSignals] = useState<RoutingSignal[] | null>(null);

  useEffect(() => {
    listRoutedInbox({ status: "pending", limit: 12 })
      .then((res) => setSignals(res.signals))
      .catch(() => setSignals([]));
  }, []);

  if (signals === null) {
    return <p className={styles.emptyHint}>{t("wb.loading")}</p>;
  }
  if (signals.length === 0) {
    return <p className={styles.emptyHint}>{t("wb.requests.empty")}</p>;
  }
  return (
    <>
      {signals.map((s) => {
        // Pick a one-line summary from the framing or the first option.
        const summary = s.framing.trim().split(/\n/)[0]?.slice(0, 80) ?? "";
        const created = s.created_at
          ? new Date(s.created_at).toLocaleString()
          : "";
        return (
          <PanelItem
            key={s.id}
            title={summary || t("wb.requests.untitled")}
            meta={`${s.status} · ${created}`}
          />
        );
      })}
    </>
  );
}
