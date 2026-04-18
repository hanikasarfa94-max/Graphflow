// Derive the current workflow stage from graph state, never from a
// denormalized field (per PLAN.md 1E). The graph IS the status.

import type { Delivery, ProjectState } from "./api";

export type Stage =
  | "intake"
  | "clarify"
  | "plan"
  | "conflict"
  | "delivery"
  | "done";

export interface StageSignal {
  stage: Stage;
  // Why this stage — single-sentence hint shown in the console header.
  hint: string;
}

export function deriveStage(
  state: ProjectState,
  latestDelivery: Delivery | null = state.delivery,
): StageSignal {
  const openConflicts = state.conflicts.filter(
    (c) => c.status === "open" || c.status === "stale",
  );
  const unanswered = state.clarifications.filter((c) => !c.answer);
  const hasPlan = state.plan.tasks.length > 0;
  const hasGraph = state.graph.deliverables.length > 0;

  // Live conflict demands attention — short-circuit everything else.
  if (openConflicts.length > 0) {
    return {
      stage: "conflict",
      hint: `${openConflicts.length} open conflict${
        openConflicts.length === 1 ? "" : "s"
      } — your call.`,
    };
  }

  if (unanswered.length > 0) {
    return {
      stage: "clarify",
      hint: `${unanswered.length} clarification${
        unanswered.length === 1 ? "" : "s"
      } waiting on you.`,
    };
  }

  if (!hasGraph) {
    return {
      stage: "intake",
      hint: "Describe what you want to ship in a single message.",
    };
  }

  if (!hasPlan) {
    return {
      stage: "plan",
      hint: "Graph parsed. Run the planner to generate tasks.",
    };
  }

  // Plan exists + no open conflicts + no unanswered clarifications.
  // If there's a delivery summary, we're done. Otherwise, ready to ship
  // the delivery summary.
  if (latestDelivery) {
    return {
      stage: "done",
      hint: "Delivery summary ready. Ship it.",
    };
  }

  return {
    stage: "delivery",
    hint: "Plan approved. Generate the delivery summary.",
  };
}
