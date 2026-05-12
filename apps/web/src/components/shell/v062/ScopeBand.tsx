"use client";

// ScopeBand — sticky band below the topbar. Shows the active project
// scope and lets the user switch.
//
// Per DESIGN_LOCK §"Scope doctrine": project focus is a *mode*, not a
// filter. When active it affects My AI retrieval, Tasks, Documents,
// Flow Center, routing suggestions, and memory candidate scope.
//
// **Always visible** when the user has ≥1 project. Hidden when zero
// projects (first-run user). Persistent band so the user is never
// confused about what scope they're acting in.
//
// API contract (Phase B):
//   GET  /api/scopes             → list of available scopes
//   GET  /api/user/active-scope  → current selection
//   POST /api/user/active-scope  → mutate

import { ChevronDown, Globe2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

export type Scope = {
  id: string;
  title: string;
  // For now scopes map 1:1 to projects. Future: department / enterprise
  // tiers (per north-star §"R.3 four scope tiers") layer on top.
};

export type ScopeMode = "current_focus" | "all_accessible" | "no_focus";

export function ScopeBand({
  scopes,
  activeScopeId,
  mode,
  onChange,
}: {
  scopes: Scope[];
  activeScopeId: string | null;
  mode: ScopeMode;
  onChange: (next: { scopeId: string | null; mode: ScopeMode }) => void;
}) {
  const t = useTranslations("shellV062.scopeBand");
  const [menuOpen, setMenuOpen] = useState(false);

  // No projects → hide band entirely. New users land in /my-ai with
  // a "create your first scope" prompt instead.
  if (scopes.length === 0) return null;

  const active =
    mode === "current_focus" && activeScopeId
      ? scopes.find((s) => s.id === activeScopeId)
      : null;

  const label =
    mode === "all_accessible"
      ? t("allAccessible")
      : mode === "no_focus"
        ? t("noFocus")
        : (active?.title ?? t("switch"));

  return (
    <div
      role="region"
      aria-label="Project scope"
      style={{
        height: 40,
        borderBottom: "1px solid var(--wg-line)",
        background: "var(--wg-surface-sunk)",
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "0 24px",
        fontSize: "var(--wg-fs-label)",
        fontFamily: "var(--wg-font-sans)",
        color: "var(--wg-ink-soft)",
        position: "relative",
      }}
    >
      <span
        style={{
          fontSize: "var(--wg-fs-caption)",
          fontFamily: "var(--wg-font-mono)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          color: "var(--wg-ink-soft)",
        }}
      >
        {t("label")}
      </span>

      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={menuOpen}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "4px 10px",
          background: "var(--wg-surface)",
          border: "1px solid var(--wg-line)",
          borderRadius: "var(--wg-radius-sm)",
          cursor: "pointer",
          color: "var(--wg-ink)",
          fontWeight: 500,
          fontSize: "var(--wg-fs-label)",
          fontFamily: "inherit",
        }}
      >
        {mode === "all_accessible" ? <Globe2 size={13} /> : null}
        <span>{label}</span>
        <ChevronDown size={13} />
      </button>

      {menuOpen ? (
        <div
          role="listbox"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 130,
            zIndex: 50,
            background: "var(--wg-surface)",
            border: "1px solid var(--wg-line)",
            borderRadius: "var(--wg-radius-md)",
            boxShadow: "var(--wg-shadow)",
            minWidth: 240,
            maxHeight: 360,
            overflowY: "auto",
            padding: 6,
          }}
        >
          <ScopeOption
            label={t("allAccessible")}
            icon={<Globe2 size={13} />}
            selected={mode === "all_accessible"}
            onClick={() => {
              onChange({ scopeId: null, mode: "all_accessible" });
              setMenuOpen(false);
            }}
          />
          <div
            style={{
              height: 1,
              background: "var(--wg-line)",
              margin: "4px 0",
            }}
          />
          {scopes.map((s) => (
            <ScopeOption
              key={s.id}
              label={s.title}
              selected={mode === "current_focus" && activeScopeId === s.id}
              onClick={() => {
                onChange({ scopeId: s.id, mode: "current_focus" });
                setMenuOpen(false);
              }}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ScopeOption({
  label,
  icon,
  selected,
  onClick,
}: {
  label: string;
  icon?: React.ReactNode;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={onClick}
      style={{
        width: "100%",
        textAlign: "left",
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 10px",
        background: selected ? "var(--wg-accent-soft)" : "transparent",
        color: selected ? "var(--wg-accent)" : "var(--wg-ink)",
        border: "none",
        borderRadius: "var(--wg-radius-sm)",
        cursor: "pointer",
        fontSize: "var(--wg-fs-label)",
        fontFamily: "var(--wg-font-sans)",
        fontWeight: selected ? 600 : 400,
      }}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}
