// /my-ai — primary landing for v0.6.2. The 5-surface IA's default route.
//
// Phase A.1 scaffold (2026-05-12) — this is the placeholder shell. The
// real grounded greeting + Ready to Share strip + composer + routing
// suggestion cards land in Phase B per BUILD-v062.md.
//
// Routes that will eventually live here:
//   GroundedGreeting       — server-rendered re-entry summary
//   ReadyToShareStrip      — max 3 visible drafts ready to share
//   MyAIComposer           — single composer (per FRONTEND_IMPLEMENTATION.md)
//   RoutingSuggestionCard  — AI-proposed routes (proposals only)
//   ShareableDraftItem     — items the user can send to a stream
//
// API surface (Phase B):
//   GET  /api/my-ai/landing?scope_id=...
//   POST /api/my-ai/messages

import { Card, Heading, PageHeader, Text } from "@/components/ui";
import { requireUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

export default async function MyAILandingPage() {
  const user = await requireUser("/my-ai");

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
        subtitle="Private reasoning first. Think with AI, then share what's ready. This is the landing surface for the v0.6.2 build."
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr)",
          gap: 16,
        }}
      >
        <Card title="Coming next">
          <Text variant="body" muted>
            The grounded greeting, Ready to Share strip, and routing suggestion
            cards arrive in Phase B of <code>BUILD-v062.md</code>. For now this
            is a placeholder so the new shell can be wired without breaking
            login.
          </Text>
        </Card>
      </div>
    </main>
  );
}
