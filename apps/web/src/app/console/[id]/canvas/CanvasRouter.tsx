"use client";

import type { Delivery, ProjectState } from "@/lib/api";
import type { Stage } from "@/lib/stage";

import { ConflictCanvas } from "./ConflictCanvas";
import { DeliveryCanvas } from "./DeliveryCanvas";
import { MessagesCanvas } from "./MessagesCanvas";
import { PlanTablesCanvas } from "./PlanTablesCanvas";

export function CanvasRouter({
  projectId,
  stage,
  state,
  deliveryHistory,
  setState,
  setDeliveryHistory,
}: {
  projectId: string;
  stage: Stage;
  state: ProjectState;
  deliveryHistory: Delivery[];
  setState: React.Dispatch<React.SetStateAction<ProjectState>>;
  setDeliveryHistory: React.Dispatch<React.SetStateAction<Delivery[]>>;
}) {
  switch (stage) {
    case "intake":
    case "clarify":
      return <MessagesCanvas projectId={projectId} state={state} />;
    case "plan":
      return <PlanTablesCanvas projectId={projectId} state={state} />;
    case "conflict":
      return (
        <ConflictCanvas
          projectId={projectId}
          state={state}
          setState={setState}
        />
      );
    case "delivery":
    case "done":
      return (
        <DeliveryCanvas
          projectId={projectId}
          state={state}
          deliveryHistory={deliveryHistory}
          setState={setState}
          setDeliveryHistory={setDeliveryHistory}
        />
      );
  }
}
