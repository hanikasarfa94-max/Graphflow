"use client";

// v-next ProjectBar — global crumb + scope tier pills.
//
// Differs from apps/web/src/components/projects/ProjectBar.tsx in two
// ways per spec §5 + Q-B:
//   1. Mounts globally (not per-project layout). Reads active project
//      from ImNav selection / ProjectBar context, not from the URL.
//   2. Cell pill defaults OFF — user opts in to broaden context (§5).
//
// Wave 2: + ⋯ overflow menu listing the project sub-routes that don't
// rate a Rail glyph (settings, meetings, renders, composition,
// team-perf). Disabled when no active project. Click-outside dismiss.

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import styles from "./ProjectBarVNext.module.css";

interface Props {
  // Display name of the active project, or null when no project context
  // applies (e.g. the user is in 通用 Agent or a DM).
  projectTitle: string | null;
  // Surface label derived from active stream kind.
  surfaceLabel: string | null;
  // Cell pill toggle state. Default OFF per Q-B.
  cellPillOn: boolean;
  onToggleCellPill: () => void;
  // Active project id — drives the overflow menu links. null hides the
  // overflow button (we'd have nowhere to navigate).
  activeProjectId?: string | null;
}

interface OverflowItem {
  key: string;
  href: (id: string) => string;
  i18nKey: string;
}

const OVERFLOW_ITEMS: OverflowItem[] = [
  {
    key: "settings",
    href: (id) => `/projects/${id}/settings`,
    i18nKey: "projectBar.overflow.settings",
  },
  {
    key: "meetings",
    href: (id) => `/projects/${id}/meetings`,
    i18nKey: "projectBar.overflow.meetings",
  },
  {
    key: "renders",
    href: (id) => `/projects/${id}/renders`,
    i18nKey: "projectBar.overflow.renders",
  },
  {
    key: "composition",
    href: (id) => `/projects/${id}/composition`,
    i18nKey: "projectBar.overflow.composition",
  },
  {
    key: "teamperf",
    href: (id) => `/projects/${id}/team/perf`,
    i18nKey: "projectBar.overflow.teamPerf",
  },
];

export function ProjectBarVNext({
  projectTitle,
  surfaceLabel,
  cellPillOn,
  onToggleCellPill,
  activeProjectId,
}: Props) {
  const t = useTranslations("shellVNext");
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Click-outside dismiss.
  useEffect(() => {
    if (!menuOpen) return;
    function onDoc(e: MouseEvent) {
      if (!menuRef.current) return;
      if (!menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [menuOpen]);

  return (
    <div className={styles.bar} data-testid="vnext-project-bar">
      {projectTitle ? (
        <>
          <span className={styles.crumb}>
            <span className={styles.dot} aria-hidden />
            <span className={styles.crumbLabel}>{t("projectBar.project")}</span>
            <strong className={styles.crumbValue}>{projectTitle}</strong>
          </span>
          {surfaceLabel && (
            <>
              <span className={styles.sep} aria-hidden>
                ·
              </span>
              <span className={styles.crumb}>
                <span className={styles.crumbLabel}>{t("projectBar.surface")}</span>
                <span className={styles.crumbValue}>{surfaceLabel}</span>
              </span>
            </>
          )}
        </>
      ) : (
        <span className={styles.crumbMuted}>{t("projectBar.noProject")}</span>
      )}

      <div className={styles.spacer} />

      {/* Per Q-B: Personal is default-on (visual-only marker since
          there's nothing to toggle for "this is your private surface");
          Cell is opt-in (toggleable). Department + Enterprise are
          stub pills for v1 — they need backend tier-filter wiring
          before they can flip. */}
      <span className={`${styles.pill} ${styles.pillOn}`} aria-disabled="true">
        {t("projectBar.tier.personal")}
      </span>
      <button
        type="button"
        className={`${styles.pill} ${cellPillOn ? styles.pillOn : ""}`}
        onClick={onToggleCellPill}
        disabled={!projectTitle}
        aria-pressed={cellPillOn}
        title={t("projectBar.cellTip")}
        data-testid="vnext-project-bar-cell-pill"
      >
        {t("projectBar.tier.cell")}
      </button>
      <span className={styles.pillStub}>{t("projectBar.tier.department")}</span>
      <span className={styles.pillStub}>{t("projectBar.tier.enterprise")}</span>

      {/* Overflow — settings / meetings / renders / composition /
          team-perf. Hidden when there's no project to scope to. */}
      {activeProjectId && (
        <div className={styles.overflowWrap} ref={menuRef}>
          <button
            type="button"
            className={styles.overflowBtn}
            onClick={() => setMenuOpen((v) => !v)}
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            title={t("projectBar.overflow.title")}
            data-testid="vnext-project-bar-overflow"
          >
            ⋯
          </button>
          {menuOpen && (
            <div
              className={styles.overflowMenu}
              role="menu"
              data-testid="vnext-project-bar-overflow-menu"
            >
              {OVERFLOW_ITEMS.map((item) => (
                <Link
                  key={item.key}
                  href={item.href(activeProjectId)}
                  role="menuitem"
                  className={styles.overflowItem}
                  onClick={() => setMenuOpen(false)}
                  data-testid={`vnext-project-bar-overflow-${item.key}`}
                >
                  {t(item.i18nKey)}
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
