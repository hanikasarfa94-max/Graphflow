"use client";

// v-next Rail — far-left icon strip per docs/shell-v-next.txt §4.
//
// Items: agentView ⌂ | graphView ⊛ | projectView ▣ | taskView ✓ |
// knowledgeView ◇ | orgView ◎ | auditView ⌕ | tools ▦ (toggle).
// Bottom: profile avatar + sign-out (Wave 1 port from legacy
// AppSidebar footer — these were the most visible features lost in
// the v-next migration). Help "?" sits below them.

import Link from "next/link";
import type { User } from "@/lib/api";

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
  user,
}: {
  activeView: ActiveView;
  onChange: (view: ActiveView) => void;
  onToggleTools: () => void;
  // Drives the avatar initial + tooltip. Optional — when missing the
  // profile/sign-out chunk is hidden (e.g. defensive against unauthed
  // edge cases, even though AppShellVNext bails out before this point).
  user?: User | null;
}) {
  const initial = ((user?.display_name || user?.username || "?")
    .trim()
    .charAt(0)
    .toUpperCase() || "?");
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
        {user && (
          <>
            <Link
              href="/settings/profile"
              className={styles.avatar}
              title={user.display_name || user.username}
              aria-label="Profile"
              data-testid="vnext-rail-profile"
            >
              <span aria-hidden>{initial}</span>
              <span className={styles.tip}>
                {user.display_name || user.username}
              </span>
            </Link>
            <form
              action="/api/auth/logout?redirect=/"
              method="POST"
              className={styles.signoutForm}
            >
              <button
                type="submit"
                className={styles.signoutBtn}
                title="Sign out"
                aria-label="Sign out"
                data-testid="vnext-rail-signout"
              >
                <span aria-hidden>⎋</span>
                <span className={styles.tip}>Sign out</span>
              </button>
            </form>
          </>
        )}
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
