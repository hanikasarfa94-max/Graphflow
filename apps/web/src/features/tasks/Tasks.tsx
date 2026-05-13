"use client";

// Tasks — page body for the v0.6.2 global /tasks surface.
//
// Phase D scaffold (2026-05-13). Replaces the Phase A.1 placeholder
// stub at apps/web/src/app/tasks/page.tsx with a real PageHeader +
// view tabs (My Tasks / All) + scope selector context + TaskList.
//
// Doctrine — tasks are context-born. The Create Menu must NOT expose
// "New task" (FRONTEND_IMPLEMENTATION.md + API_CONTRACT.md §"Create
// Menu" excluded_direct_creations). The page header therefore has no
// "+ New" CTA — by design.
//
// API surface consumed (Phase D.2):
//   GET /api/tasks?scope_id=<id|undefined>&view=<my_tasks|all>
//   POST /api/tasks/candidates       (consumed by other surfaces)
//   POST /api/tasks/:id/promote      (consumed by TaskRightRail)

// TODO(i18n): externalize tab labels, subtitle, scope-strip copy.

import { useState } from "react";

import { Button, PageHeader, Text } from "@/components/ui";

import { TaskList } from "./TaskList";
import type { TaskView } from "./types";

const TABS: ReadonlyArray<{ id: TaskView; label: string }> = [
  { id: "my_tasks", label: "My Tasks" },
  { id: "all", label: "All" },
];

export function Tasks() {
  // View tab — defaults to My Tasks. Phase D.2 persists this in the
  // URL so deep-linking to /tasks?view=all is shareable.
  const [view, setView] = useState<TaskView>("my_tasks");

  // Scope context. The shell's ScopeBand owns the active scope in
  // v0.6.2; for the scaffold we leave scope_id undefined (cross-scope)
  // and let the user filter via the chips on TaskCards. D.2 wires
  // useActiveScope() from the shell context.
  // TODO(phase-d.2): const { activeScopeId } = useActiveScope();
  const activeScopeId: string | undefined = undefined;

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="Tasks"
        title="Tasks"
        subtitle="Work in flight. Tasks are context-born — they enter as candidates and ascend through recognition policy to canonical. The Create Menu doesn't include 'New task' by doctrine."
      />

      {/* View tabs. Two tabs only — anything richer (assignee, due,
          policy) is a filter inside the list, not a tab. */}
      <div
        role="tablist"
        aria-label="Task view"
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 20,
          borderBottom: "1px solid var(--wg-line)",
          paddingBottom: 0,
        }}
      >
        {TABS.map((tab) => {
          const active = tab.id === view;
          return (
            <Button
              key={tab.id}
              variant={active ? "primary" : "ghost"}
              size="sm"
              role="tab"
              aria-selected={active}
              onClick={() => setView(tab.id)}
              style={{
                // Override Button shape for tab-bar fit: square the
                // bottom corners so the underline reads as a tab strip.
                borderBottomLeftRadius: 0,
                borderBottomRightRadius: 0,
                marginBottom: -1,
              }}
            >
              {tab.label}
            </Button>
          );
        })}
        <div style={{ marginLeft: "auto", paddingBottom: 8 }}>
          <Text variant="caption" muted>
            {activeScopeId
              ? `Scope: ${activeScopeId}`
              : "Scope: all accessible"}
          </Text>
        </div>
      </div>

      <TaskList view={view} scopeId={activeScopeId} />

      <Text
        as="p"
        variant="caption"
        muted
        style={{ marginTop: 16, textAlign: "center" }}
      >
        Recognition policy is non-optional on promote.
      </Text>
    </main>
  );
}
