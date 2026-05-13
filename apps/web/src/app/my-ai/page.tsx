// /my-ai — primary landing for v0.6.2.
//
// Phase RW-1.1 wiring (2026-05-13): pulls real data from
// GET /api/my-ai/landing instead of rendering a placeholder card.
// The endpoint surfaces pending routed signals as grounded items
// (real objects the user can re-enter). ready_to_share is honestly
// empty until the source-of-truth surface lands; we do NOT render
// mock drafts.
//
// API surface:
//   GET  /api/my-ai/landing?scope_id=...   ← live
//   POST /api/my-ai/messages                ← Phase RW-3 (composer)

import Link from "next/link";

import { Card, EmptyState, Heading, PageHeader, Tag, Text } from "@/components/ui";
import { requireUser, serverFetch } from "@/lib/auth";

export const dynamic = "force-dynamic";

type GroundedItem = {
  id: string;
  kind: string;
  title: string;
  scope_id: string | null;
  object_url: string | null;
};

type ShareableDraft = {
  id: string;
  title: string;
  target_scope_id: string | null;
  target_user_id: string | null;
};

type MyAILandingResponse = {
  grounded_items: GroundedItem[];
  ready_to_share: ShareableDraft[];
  scope_id: string | null;
};

async function loadLanding(): Promise<MyAILandingResponse> {
  // Tolerant: a transient API failure on the landing should not
  // crash the surface — render the empty state instead. The error
  // is observable in server logs via serverFetch's ApiError throw,
  // which we catch and downgrade.
  try {
    return await serverFetch<MyAILandingResponse>("/api/my-ai/landing");
  } catch {
    return { grounded_items: [], ready_to_share: [], scope_id: null };
  }
}

export default async function MyAILandingPage() {
  const user = await requireUser("/my-ai");
  const data = await loadLanding();

  const hasGrounded = data.grounded_items.length > 0;
  const hasDrafts = data.ready_to_share.length > 0;

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        kicker="My AI"
        title={`Good to see you, ${user.display_name || user.username}.`}
        subtitle="Private reasoning first. Think with AI, then share what's ready."
      />

      <section
        aria-labelledby="grounded-heading"
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr)",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <Heading level={2} id="grounded-heading">
          Pick up where you left off
        </Heading>

        {hasGrounded ? (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 12,
            }}
          >
            {data.grounded_items.map((item) => (
              <GroundedCard key={item.id} item={item} />
            ))}
          </div>
        ) : (
          <EmptyState>
            Nothing waiting for you right now.
          </EmptyState>
        )}
      </section>

      <section aria-labelledby="ready-heading">
        <Heading level={2} id="ready-heading">
          Ready to share
        </Heading>
        {hasDrafts ? (
          // Reserved for the drafts surface when it lands. Today
          // /api/my-ai/landing always returns ready_to_share=[] —
          // see the backend comment in routers/my_ai.py.
          <div>{/* draft list placeholder for live data */}</div>
        ) : (
          <EmptyState>No drafts ready to send yet.</EmptyState>
        )}
      </section>
    </main>
  );
}

function GroundedCard({ item }: { item: GroundedItem }) {
  // object_url comes from the server; today every routed-signal
  // grounded item routes to /flow-center. As real routing detail
  // pages come online (Phase RW-2.x), the server will deep-link
  // through more specific URLs (e.g. /flow-center?signal_id=…).
  const href = item.object_url || "#";
  return (
    <Link
      href={href}
      style={{
        display: "block",
        textDecoration: "none",
        color: "inherit",
      }}
    >
      <Card>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 8,
          }}
        >
          <Tag tone="ai">{item.kind}</Tag>
          {item.scope_id ? (
            <Text variant="caption" muted>
              {item.scope_id.slice(0, 8)}
            </Text>
          ) : null}
        </div>
        <Text variant="body">{item.title}</Text>
      </Card>
    </Link>
  );
}
