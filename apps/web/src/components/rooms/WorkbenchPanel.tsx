"use client";

// WorkbenchPanel — chrome around one workbench projection panel.
//
// Per the prototype `ToolPanelCard` (App.tsx:436-474). Header carries
// the panel title + drag affordance + focus and close buttons; body
// renders the projection contents. Drag-rearrange via HTML5 DnD is
// in-memory only this slice (codex deferred persistence).
//
// The panel is the chrome; the contents are passed as children so the
// projection logic (e.g. RequestsPanelBody) can stay pure and
// derive-from-state without coupling to the workbench shell.

import type { CSSProperties } from "react";
import { useTranslations } from "next-intl";

export type PanelKind =
  | "requests"
  | "tasks"
  | "knowledge"
  | "skills"
  | "workflow";

export interface PanelDef {
  id: string;
  kind: PanelKind;
  title: string;
  // Whether this panel is currently focused (focus mode hides others).
  focus?: boolean;
}

interface Props {
  panel: PanelDef;
  hidden: boolean;
  onFocus: () => void;
  onClose: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDrop: () => void;
  children: React.ReactNode;
}

const headStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "8px 10px",
  borderBottom: "1px solid var(--wg-line)",
  background: "#fafafa",
  borderTopLeftRadius: "var(--wg-radius)",
  borderTopRightRadius: "var(--wg-radius)",
};

const dragHandleStyle: CSSProperties = {
  cursor: "grab",
  color: "var(--wg-ink-soft)",
  fontSize: 12,
  userSelect: "none",
};

const actionBtnStyle: CSSProperties = {
  background: "transparent",
  border: "none",
  cursor: "pointer",
  padding: "2px 6px",
  fontSize: 12,
  color: "var(--wg-ink-soft)",
  borderRadius: 3,
};

export function WorkbenchPanel({
  panel,
  hidden,
  onFocus,
  onClose,
  onDragStart,
  onDragEnd,
  onDrop,
  children,
}: Props) {
  const tAria = useTranslations("aria.workbenchPanel");
  if (hidden) return null;
  return (
    <section
      className={
        "panel" + (panel.focus ? " panel--focus" : "")
      }
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
      style={{
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        background: "#fff",
        boxShadow: panel.focus
          ? "0 4px 16px rgba(0,0,0,0.06)"
          : "0 1px 2px rgba(0,0,0,0.02)",
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <div className="panelHead" style={headStyle}>
        <span aria-hidden style={dragHandleStyle}>
          ⋮⋮
        </span>
        <strong style={{ fontSize: 13, color: "var(--wg-ink)" }}>
          {panel.title}
        </strong>
        <div style={{ marginLeft: "auto", display: "flex", gap: 2 }}>
          <button
            className="panelBtn"
            onClick={onFocus}
            aria-label={tAria("focus")}
            style={actionBtnStyle}
          >
            ⌖
          </button>
          <button
            className="panelBtn"
            onClick={onClose}
            aria-label={tAria("close")}
            style={actionBtnStyle}
          >
            ×
          </button>
        </div>
      </div>
      <div className="panelBody" style={{ padding: 10, overflow: "auto" }}>
        {children}
      </div>
    </section>
  );
}
