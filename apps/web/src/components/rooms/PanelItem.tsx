"use client";

// PanelItem — the unit of projection in the room workbench.
//
// Per the projection model: an entity (im_suggestion, decision, task,
// kb_item) renders one way inline in the timeline (causal context)
// and another way as a queue item in the workbench (current work
// surface). This component is the queue rendering — title + meta +
// optional progress + optional click handler that scrolls the inline
// card into view via the shared `data-entity-id` anchor written by
// RoomStreamTimeline.
//
// Direct port of `workgraph-ts-prototype/src/App.tsx` PanelItem
// (lines 530-538). DOM class names mirror the prototype so styles
// can transplant cleanly.

import type { TimelineItem } from "@/lib/api";

export interface EntityRef {
  kind: TimelineItem["kind"];
  id: string;
}

interface Props {
  title: string;
  meta?: string;
  progress?: number;
  // When supplied, clicking the item scrolls the matching inline
  // `data-entity-kind={kind} data-entity-id={id}` element into view
  // and momentarily highlights it. The room view's RoomStreamTimeline
  // writes those attributes on every rendered card.
  entityRef?: EntityRef;
  // Optional inline action area (e.g. accept/dismiss buttons on a
  // pending suggestion's PanelItem).
  actions?: React.ReactNode;
}

export function scrollToEntity(ref: EntityRef): void {
  if (typeof document === "undefined") return;
  const sel = `[data-entity-kind="${ref.kind}"][data-entity-id="${ref.id}"]`;
  const el = document.querySelector<HTMLElement>(sel);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  // Brief highlight so the user can locate the card after the scroll.
  el.classList.add("entity-flash");
  window.setTimeout(() => el.classList.remove("entity-flash"), 1200);
}

export function PanelItem({ title, meta, progress, entityRef, actions }: Props) {
  const clickable = entityRef !== undefined;
  return (
    <div
      data-testid="workbench-panel-item"
      data-entity-kind={entityRef?.kind}
      data-entity-id={entityRef?.id}
      className={"panelItem" + (clickable ? " panelItem--clickable" : "")}
      onClick={
        clickable
          ? () => scrollToEntity(entityRef)
          : undefined
      }
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onKeyDown={
        clickable
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                scrollToEntity(entityRef);
              }
            }
          : undefined
      }
      style={{
        padding: "10px 12px",
        border: "1px solid var(--wg-line)",
        borderRadius: "var(--wg-radius)",
        marginBottom: 8,
        cursor: clickable ? "pointer" : "default",
        background: "#fff",
        display: "grid",
        gap: 4,
      }}
    >
      <strong style={{ fontSize: 13, color: "var(--wg-ink)" }}>
        {title}
      </strong>
      {meta && (
        <small style={{ color: "var(--wg-ink-soft)", fontSize: 12 }}>
          {meta}
        </small>
      )}
      {typeof progress === "number" && (
        <div
          className="progress"
          style={{
            height: 4,
            background: "var(--wg-line)",
            borderRadius: 2,
            overflow: "hidden",
          }}
        >
          <i
            style={{
              display: "block",
              height: "100%",
              width: `${Math.max(0, Math.min(100, progress))}%`,
              background: "var(--wg-accent)",
            }}
          />
        </div>
      )}
      {actions && (
        <div
          style={{ display: "flex", gap: 6, marginTop: 4 }}
          onClick={(e) => e.stopPropagation()}
        >
          {actions}
        </div>
      )}
    </div>
  );
}
