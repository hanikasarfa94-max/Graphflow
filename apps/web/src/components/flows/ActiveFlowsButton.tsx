"use client";

// ActiveFlowsButton — B.2 bridge.
//
// The legacy `/projects/[id]` and `/projects/[id]/team` surfaces don't
// mount the v-Next RoomWorkbench (per the 2026-05-03 v-Next rollback);
// the workbench-hosted Active Flows panel is therefore unreachable from
// the surfaces users actually dogfood. This component is the bridge:
// a small toolbar button that opens a popover containing the same
// `FlowsPanelBody` the workbench renders, no new BE work.
//
// Read-only and Open-only, matching Slice B's surface guarantees.
// Mutation buttons (accept / counter / dismiss) wait for Slice C.

import { useEffect, useRef, useState, type CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { FlowsPanelBody } from "@/components/rooms/FlowsPanelBody";

interface Props {
  projectId: string;
  currentUserId?: string;
}

export function ActiveFlowsButton({ projectId, currentUserId }: Props) {
  const t = useTranslations("flows");
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  // Close on outside click + Escape. Both effects only mount while
  // open so we don't waste listeners on the common case.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (!wrapRef.current) return;
      if (e.target instanceof Node && wrapRef.current.contains(e.target)) {
        return;
      }
      setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <button
        type="button"
        data-testid="active-flows-button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="dialog"
        style={buttonStyle(open)}
      >
        <span aria-hidden style={{ fontSize: 13 }}>
          ⇄
        </span>
        <span>{t("title")}</span>
      </button>
      {open ? (
        <div
          data-testid="active-flows-popover"
          role="dialog"
          aria-label={t("title")}
          style={popoverStyle}
        >
          <FlowsPanelBody projectId={projectId} viewerUserId={currentUserId} />
        </div>
      ) : null}
    </div>
  );
}

function buttonStyle(open: boolean): CSSProperties {
  return {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "4px 10px",
    fontSize: 12,
    fontFamily: "var(--wg-font-mono)",
    color: open ? "#fff" : "var(--wg-accent)",
    background: open ? "var(--wg-accent)" : "#fff",
    border: "1px solid var(--wg-accent-ring, var(--wg-accent))",
    borderRadius: 12,
    cursor: "pointer",
    whiteSpace: "nowrap",
  };
}

const popoverStyle: CSSProperties = {
  position: "absolute",
  top: "calc(100% + 8px)",
  right: 0,
  width: 380,
  maxHeight: 480,
  overflowY: "auto",
  padding: 14,
  background: "#fff",
  border: "1px solid var(--wg-line)",
  borderRadius: "var(--wg-radius)",
  boxShadow: "0 10px 28px rgba(0,0,0,0.10)",
  zIndex: 30,
};
