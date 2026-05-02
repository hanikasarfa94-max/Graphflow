"use client";

// v-next Rail — far-left icon strip per docs/shell-v-next.txt §4.
//
// Items: agentView ⌂ | graphView ⊛ | projectView ▣ | taskView ✓ |
// knowledgeView ◇ | orgView ◎ | auditView ⌕ | tools ▦ (toggle).
// Bottom: language toggle, profile avatar, sign-out — Wave 1+2.5 ports
// from legacy AppSidebar footer (most visible features lost in the
// v-next migration). Help "?" sits below them.

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { LOCALE_COOKIE, type Locale } from "@/i18n/config";
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

  // Compact language toggle. Clicks flip between en ↔ zh — same cookie
  // + best-effort profile-write semantics as the legacy LanguageSwitcher,
  // just rendered as a single rail-sized button instead of an inline
  // <select> (a 50px column can't host the dropdown). Two locales is
  // the entire v1 set so a toggle is enough.
  const currentLocale = useLocale() as Locale;
  const tLang = useTranslations("language");
  const langRouter = useRouter();
  const [langPending, langStartTransition] = useTransition();
  const otherLocale: Locale = currentLocale === "en" ? "zh" : "en";
  function flipLocale() {
    document.cookie = `${LOCALE_COOKIE}=${otherLocale}; path=/; max-age=${
      60 * 60 * 24 * 365
    }; samesite=lax`;
    void fetch("/api/users/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ display_language: otherLocale }),
    }).catch(() => undefined);
    langStartTransition(() => langRouter.refresh());
  }
  const localeBadge = currentLocale === "en" ? "EN" : "中";
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
          className={styles.langBtn}
          onClick={flipLocale}
          disabled={langPending}
          title={tLang("switcher")}
          aria-label={tLang("switcher")}
          data-testid="vnext-rail-language"
        >
          <span aria-hidden>{localeBadge}</span>
          <span className={styles.tip}>{tLang("switcher")}</span>
        </button>
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
        {/* Help "?" used to live here without an onClick — removed for
            v1 since there's no help center to point at and a dead
            button reads worse than no button. Reintroduce alongside
            real docs. */}
      </div>
    </nav>
  );
}
