"use client";

// MemoryPromptDrawer — bridge between a flow response and the memory
// review surface.
//
// Phase RW-3.5 safety polish (2026-05-13): the Phase C version
// rendered a fabricated summary paragraph (about a launch-date
// change) and shipped no-op Skip / Later handlers. Both deceived the
// reviewer about state: there was no real candidate behind the
// summary, and clicking Skip / Later did nothing the server would
// recognize.
//
// Until the flow_response → memory_candidate bridge is wired
// (depends on POST /api/flow-requests/:id/respond returning a real
// memory_candidate_prompt + the skip-reversal endpoint
// POST /api/flow-responses/:id/generate-memory-candidate landing
// real-data), this drawer:
//
//   * surfaces the candidate_id passed in (so the user can see the
//     routing happened) and
//   * offers ONE live affordance — "Review" — which opens the
//     MemoryReviewDrawer, which IS wired end-to-end (RW-2.2 + RW-3).
//
// Skip + Later are intentionally absent. Wiring them without the
// backend bridge would silently no-op and the user would believe
// they had deferred something that never persisted. Better to make
// the user click Review (or close the drawer) than to fake a
// "deferred" action.

import { Button, Card, EmptyState, Tag, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";

export function MemoryPromptDrawer({
  candidate_id,
}: {
  candidate_id: string;
}) {
  const drawer = useDrawer();

  return (
    <div
      data-testid="memory-prompt-not-wired"
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
    >
      <header style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Tag tone="amber">prompt not wired</Tag>
        <Text variant="caption" muted>
          candidate_id: {candidate_id}
        </Text>
      </header>

      <EmptyState>
        The flow-response → memory-prompt bridge isn’t wired yet.
        Skip and Later aren’t available; clicking them would
        silently no-op against the server, which is the failure mode
        we’re explicitly avoiding.
      </EmptyState>

      <Card variant="sunk">
        <Text variant="caption" muted>
          The Memory Review drawer is live — opening it for this
          candidate_id will pull the real{" "}
          <code>GET /api/memory-candidates/:id</code> payload. Accept /
          Defer / Reject / Reopen are server-authoritative there.
        </Text>
      </Card>

      <footer
        style={{
          display: "flex",
          gap: 8,
          justifyContent: "flex-end",
          flexWrap: "wrap",
          paddingTop: 12,
          borderTop: "1px solid var(--wg-line)",
        }}
      >
        <Button variant="ghost" size="md" onClick={() => drawer.close()}>
          Close
        </Button>
        <Button
          data-testid="memory-prompt-review"
          variant="primary"
          size="md"
          onClick={() =>
            drawer.open({
              type: "memory_review",
              props: { candidate_id },
            })
          }
        >
          Review
        </Button>
      </footer>
    </div>
  );
}
