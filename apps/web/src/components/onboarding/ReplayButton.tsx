"use client";

// ReplayButton — Phase 1.B.
//
// Calls POST /api/projects/{id}/onboarding/replay so the overlay
// re-opens on the user's next visit to /projects/[id]. Rendered on
// /settings/profile per each project the user is a member of.

import { useState } from "react";

import { Button, Text } from "@/components/ui";
import { postOnboardingReplay } from "@/lib/api";

type Props = {
  projectId: string;
  projectTitle: string;
  label: string;
};

export function ReplayButton({ projectId, projectTitle, label }: Props) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">(
    "idle",
  );

  async function onClick() {
    setState("busy");
    try {
      await postOnboardingReplay(projectId);
      setState("done");
    } catch {
      setState("error");
    }
  }

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        padding: "6px 0",
        borderBottom: "1px solid var(--wg-line-soft)",
      }}
    >
      <Text variant="body">{projectTitle}</Text>
      <Button
        variant="ghost"
        size="sm"
        onClick={onClick}
        disabled={state === "busy" || state === "done"}
        data-testid={`replay-onboarding-${projectId}`}
      >
        {state === "done" ? "✓" : label}
      </Button>
    </div>
  );
}
