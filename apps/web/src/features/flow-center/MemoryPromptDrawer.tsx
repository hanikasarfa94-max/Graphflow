"use client";

// MemoryPromptDrawer — post-flow-response prompt. Opens immediately
// after a flow_request is sent and the API returned a
// `memory_candidate_prompt` payload.
//
// DESIGN_LOCK.md invariant #6: "Flow acceptance does not auto-accept
// memory." This drawer is the visible expression of that doctrine —
// the user picks one of [Review / Skip / Later]. Nothing crystallizes
// without an explicit step into MemoryReviewDrawer.
//
// Skip is reversible per API_CONTRACT.md:
//   POST /api/flow-responses/:id/generate-memory-candidate
// regenerates the candidate even after skip. Reflected in the body
// copy so the user isn't afraid to click.
//
// Phase B.2 swap-in: replace useSkipMemoryCandidate /
// useDeferMemoryCandidate with the real POST mutators.

import { Button, Card, Text } from "@/components/ui";
import { useDrawer } from "@/components/shell/v062/DrawerHost";

// TODO(phase-b.2): replace with real summary read from
//   `GET /api/memory-candidates/:id`
// Phase C returns a stub paragraph keyed by id.
function useMemoryCandidateSummary(id: string): string {
  return `A new memory atom was proposed from this exchange (${id}). It claims a launch-date change that affects downstream marketing, scheduling, and compliance dependencies.`;
}

// TODO(phase-b.2): replace stubs below with real POST mutators.
function useSkipMemoryCandidate() {
  return async (_id: string) => {
    /* noop in Phase C */
  };
}
function useDeferMemoryCandidate() {
  return async (_id: string) => {
    /* noop in Phase C */
  };
}

export function MemoryPromptDrawer({ candidate_id }: { candidate_id: string }) {
  const drawer = useDrawer();
  const summary = useMemoryCandidateSummary(candidate_id);
  const skip = useSkipMemoryCandidate();
  const defer = useDeferMemoryCandidate();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <header>
        <Text variant="caption" muted>
          Memory candidate detected
        </Text>
      </header>

      <Text as="p" variant="body">
        {summary}
      </Text>

      <Card variant="sunk">
        <Text variant="caption" muted>
          Memory crystallization is a separate decision. Acceptance
          requires server-side authority; you can skip now and reopen
          this candidate later.
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
        <Button
          variant="ghost"
          size="md"
          onClick={async () => {
            await skip(candidate_id);
            drawer.close();
          }}
        >
          Skip
        </Button>
        <Button
          variant="ghost"
          size="md"
          onClick={async () => {
            await defer(candidate_id);
            drawer.close();
          }}
        >
          Later
        </Button>
        <Button
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
