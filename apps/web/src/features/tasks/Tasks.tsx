"use client";

// Tasks — page body for the v0.6.2 global /tasks surface.
//
// Phase RW-7 (2026-05-13): live data via GET /api/tasks. The shell's
// server page fetches twice (once per view tab) so switching views
// is a client-side prop swap, not a refetch. Scope filtering uses
// the same wire endpoint with ?scope_id=…; today the BE returns the
// caller's personal drafts in either view, so the My Tasks / All
// split is structurally present but visually identical until the
// backend widens list_personal_for_owner to include plan-scope rows.
// That limitation is surfaced inline in the page footer.

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, PageHeader, Text } from "@/components/ui";

import { TaskList } from "./TaskList";
import type { TaskListResponse, TaskRow, TaskView } from "./types";

const TABS: ReadonlyArray<TaskView> = ["my_tasks", "all"];

export function Tasks({
  myTasks,
  allTasks,
  initialView = "my_tasks",
  scopeId,
}: {
  myTasks: TaskListResponse;
  allTasks: TaskListResponse;
  initialView?: TaskView;
  scopeId: string | null;
}) {
  const t = useTranslations("shellV062.tasks.page");
  const [view, setView] = useState<TaskView>(initialView);

  const rows: TaskRow[] =
    view === "my_tasks" ? myTasks.tasks : allTasks.tasks;

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker={t("kicker")}
        title={t("title")}
        subtitle={t("subtitle")}
      />

      <div
        role="tablist"
        aria-label={t("tabsAriaLabel")}
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 20,
          borderBottom: "1px solid var(--wg-line)",
        }}
      >
        {TABS.map((tab) => {
          const active = tab === view;
          return (
            <Button
              key={tab}
              variant={active ? "primary" : "ghost"}
              size="sm"
              role="tab"
              aria-selected={active}
              onClick={() => setView(tab)}
              style={{
                borderBottomLeftRadius: 0,
                borderBottomRightRadius: 0,
                marginBottom: -1,
              }}
            >
              {t(`tabs.${tab}` as const)}
            </Button>
          );
        })}
        <div style={{ marginLeft: "auto", paddingBottom: 8 }}>
          <Text variant="caption" muted>
            {scopeId
              ? t("scopeLabel", { scope: scopeId.slice(0, 8) })
              : t("scopeAll")}
          </Text>
        </div>
      </div>

      <TaskList tasks={rows} />

      <Text
        as="p"
        variant="caption"
        muted
        style={{ marginTop: 16, textAlign: "center" }}
      >
        {t("limitationNote")}
      </Text>
    </main>
  );
}
