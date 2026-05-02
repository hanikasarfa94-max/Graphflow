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
  fetchVNextPrefs,
  updateVNextPrefs,
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

export function Workbench({ onClose, streamKind = "personal" }: Props) {
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
  onFocus,
  onClose,
  onDragStart,
  onDragEnd,
  onDrop,
}: {
  panel: Panel;
  modeFocus: boolean;
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
        <PanelBody kind={panel.kind} />
      </div>
    </section>
  );
}

// PanelBody — kind-specific renderers. Phase 2 ships static placeholder
// content matching the prototype's visual shape. Real data wiring per
// kind is a separate follow-up (each kind has its own BE dependency:
// tasks → personal-tasks API, knowledge → kb_search, skills →
// project-members + skill atlas, requests → routing inbox).
function PanelBody({ kind }: { kind: PanelKind }) {
  const t = useTranslations("shellVNext");

  if (kind === "tasks") {
    return (
      <>
        <div className={styles.scopeRow}>
          <span className={`${styles.scopePill} ${styles.scopePillActive}`}>
            {t("wb.tasks.mine")}
          </span>
          <span className={styles.scopePill}>{t("wb.tasks.team")}</span>
        </div>
        <PanelItem title="CRM 后端接口对接" meta="进行中" progress={70} />
        <PanelItem title="客户标签体系重构" meta="进行中 · 2 天后" />
        <PanelItem title="渠道满意分析设计" meta="进行中" />
      </>
    );
  }
  if (kind === "knowledge") {
    return (
      <>
        <input
          className={styles.panelInput}
          placeholder={t("wb.knowledge.searchPlaceholder")}
        />
        <PanelItem title="Boss-3 智能设计实践 v0.3" meta="可用字数：12.8 MB" />
        <PanelItem title="团队标准 · 合作规范 v2.1" meta="10 分钟前" />
      </>
    );
  }
  if (kind === "skills") {
    return (
      <>
        <div className={styles.graphBox} aria-hidden />
        <PanelItem title="Blake" meta="后端负责人 · 9.2" />
        <PanelItem title="Diana" meta="设计负责人 · 8.6" />
      </>
    );
  }
  if (kind === "requests") {
    return (
      <>
        <PanelItem title="请 Blake 判断" meta="后端接口可行性 · 等待中" />
        <PanelItem title="请 Diana 确认" meta="数据口径定义 · 已发送" />
        <PanelItem title="请 Sofia 补充" meta="用户反馈证据 · 待处理" />
      </>
    );
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
