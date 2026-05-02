"use client";

// v-next Rail — far-left icon strip per docs/shell-v-next.txt §4.
//
// Six items + tools toggle + help. Glyphs match prototype data.ts:3-10
// exactly. Selecting any item OTHER than ⌂ (agentView) sets moduleMode
// on the parent, which hides ImNav and routes Main to the corresponding
// /detail/* page. Phase 1 wires the visual + state; navigation (next
// router push for module views) lands in Phase 2 alongside ModuleView.

import type { ActiveView } from "./AppShellClient";

import styles from "./Rail.module.css";

interface RailItem {
  id: ActiveView;
  glyph: string;
  label: string;
}

const RAIL_ITEMS: RailItem[] = [
  { id: "agentView", glyph: "⌂", label: "个人 Agent" },
  // The graph IS the product (north-star §"graph is what the product
  // actually is"). One Rail click into the project knowledge graph.
  { id: "graphView", glyph: "⊛", label: "项目图谱" },
  { id: "projectView", glyph: "▣", label: "项目管理" },
  { id: "taskView", glyph: "✓", label: "任务视图" },
  { id: "knowledgeView", glyph: "◇", label: "知识库" },
  { id: "orgView", glyph: "◎", label: "组织管理" },
  { id: "auditView", glyph: "⌕", label: "审计视图" },
];

export function Rail({
  activeView,
  onChange,
  onToggleTools,
}: {
  activeView: ActiveView;
  onChange: (view: ActiveView) => void;
  onToggleTools: () => void;
}) {
  return (
    <nav
      className={styles.rail}
      aria-label="WorkGraph 主导航"
      data-testid="vnext-rail"
    >
      <div className={styles.logo} aria-hidden>
        W
      </div>
      {RAIL_ITEMS.map((item) => (
        <button
          key={item.id}
          type="button"
          className={`${styles.item} ${activeView === item.id ? styles.active : ""}`}
          onClick={() => onChange(item.id)}
          title={item.label}
          aria-label={item.label}
          aria-pressed={activeView === item.id}
          data-rail-item={item.id}
        >
          <span aria-hidden>{item.glyph}</span>
          <span className={styles.tip}>{item.label}</span>
        </button>
      ))}
      <div className={styles.sep} />
      <button
        type="button"
        className={styles.item}
        onClick={onToggleTools}
        title="工具栏"
        aria-label="切换工具栏"
        data-testid="vnext-rail-tools"
      >
        <span aria-hidden>▦</span>
        <span className={styles.tip}>工具栏</span>
      </button>
      <div className={styles.bottom}>
        <button
          type="button"
          className={styles.item}
          title="帮助"
          aria-label="帮助"
        >
          <span aria-hidden>?</span>
          <span className={styles.tip}>帮助</span>
        </button>
      </div>
    </nav>
  );
}
