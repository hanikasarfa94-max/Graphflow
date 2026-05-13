"use client";

// FlowDrawer — body for `useDrawer().open({ type: 'flow_request', ... })`.
//
// Phase RW-3.5 safety polish (2026-05-13): the previous Phase C
// version rendered a full fabricated flow_request (Mei's launch-date
// framing, fake attachments, fake authority block, fake send button
// that opened a fake memory candidate). All of it was mock data with
// no backend behind it — opening this drawer from a real flow packet
// in /flow-center would have shown invented content as if it were
// the real request.
//
// Until a v0.6.2 GET /api/flow-requests/:id read + POST
// /api/flow-requests/:id/respond mutation pipeline lands (Phase RW-4
// or B.3 in the backend plan), this drawer renders an honest "not
// wired yet" empty state. The flow_id from the table row is
// surfaced so the user knows the click registered; everything else
// is deliberately blank.
//
// Doctrine reminder: the flow_request mutation pipeline must also
// preserve memory decoupling. Even when wired, /respond must return
// memory_candidate_prompt with actions [review, skip, later] and
// MUST NOT auto-accept memory.

import { Card, EmptyState, Tag, Text } from "@/components/ui";

export function FlowDrawer({ flow_id }: { flow_id: string }) {
  return (
    <div
      data-testid="flow-drawer-not-wired"
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
    >
      <header style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Tag tone="amber">not wired</Tag>
        <Text variant="caption" muted>
          flow_id: {flow_id}
        </Text>
      </header>

      <EmptyState>
        The flow-request detail surface isn’t wired to the backend
        yet. Opening it from the Flow Center table registers the
        click but won’t show real framing, attachments, authority,
        or response state until <code>GET /api/flow-requests/:id</code>
        and <code>POST /api/flow-requests/:id/respond</code> land.
      </EmptyState>

      <Card variant="sunk">
        <Text variant="caption" muted>
          To review the underlying memory candidate (if this packet
          carries one), open it from <code>/flow-center</code>’s
          memory column or via the memory review drawer once an
          accept link is published. Memory crystallization remains a
          separate decision.
        </Text>
      </Card>
    </div>
  );
}
