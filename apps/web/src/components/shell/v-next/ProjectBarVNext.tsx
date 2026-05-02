"use client";

// v-next ProjectBar — global crumb + scope tier pills.
//
// Differs from apps/web/src/components/projects/ProjectBar.tsx in two
// ways per spec §5 + Q-B:
//   1. Mounts globally (not per-project layout). Reads active project
//      from ImNav selection / ProjectBar context, not from the URL.
//   2. Cell pill defaults OFF — user opts in to broaden context (§5).
//
// Phase 2 scope: render a static crumb derived from the active stream.
// "Active project" detection lives in the parent (AppShellClient) and
// passes down. Real project switching wires through TopBar's 切换项目
// dropdown (already shipped).

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
}

export function ProjectBarVNext({
  projectTitle,
  surfaceLabel,
  cellPillOn,
  onToggleCellPill,
}: Props) {
  const t = useTranslations("shellVNext");

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
    </div>
  );
}
