"use client";

// MyAILandingClient — client-side owner of the /my-ai landing-vs-active
// state.
//
// Why this exists: app/my-ai/page.tsx is a server component and cannot
// hide its own landing sections after the user starts interacting with
// the composer. MyAIComposer owns its thread state locally, so the
// only place that can switch off the landing hints is here, between
// them.
//
// State model:
//   active=false  →  user hasn't focused or typed yet. Show grounded
//                    re-entry cards if any. Never render the empty
//                    "Ready to share" section (BE returns [] today).
//   active=true   →  hide landing sections by default. Offer a
//                    "Show re-entry items" toggle so the user can
//                    re-summon the grounded list without reloading
//                    the page.
//
// MyAIComposer fires onActivity on focus + first send. Once true, it
// stays true for the page lifetime — re-collapsing on every focus
// blur would make the surface feel anxious.
//
// Doctrine reminder: this wrapper does NOT change composer behavior.
// POST /api/my-ai/messages still happens inside MyAIComposer, with
// no auto-route to memory crystallization. The wrapper just owns
// visibility.

import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button, Card, EmptyState, Heading, PageHeader, Tag, Text } from "@/components/ui";

import { MyAIComposer } from "./MyAIComposer";

import type { GroundedItem, ShareableDraft } from "@/lib/api";

interface Props {
  displayName: string;
  scopeId: string | null;
  groundedItems: GroundedItem[];
  readyToShare: ShareableDraft[];
}

export function MyAILandingClient({
  displayName,
  scopeId,
  groundedItems,
  readyToShare,
}: Props) {
  const t = useTranslations("shellV062.myAi");
  // Active iff the user has focused or sent in the composer. Sticky —
  // once active, never reverts in the same mount.
  const [active, setActive] = useState(false);
  // Even after active, the user can re-open the grounded list.
  const [showReentry, setShowReentry] = useState(false);

  const hasGrounded = groundedItems.length > 0;
  const hasDrafts = readyToShare.length > 0;

  // Show grounded section when:
  //   - the user hasn't interacted yet (landing mode), OR
  //   - they've clicked "Show re-entry items" after going active.
  const showGroundedSection = hasGrounded && (!active || showReentry);

  return (
    <main
      style={{
        maxWidth: 1180,
        margin: "0 auto",
        padding: "32px 28px 80px",
      }}
    >
      <PageHeader
        titleVariant="display"
        title={t("greeting", { name: displayName })}
        subtitle={t("subtitle")}
      />

      <section
        aria-labelledby="composer-heading"
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr)",
          gap: 12,
          marginBottom: 28,
        }}
      >
        <Heading level={2} id="composer-heading">
          {t("thinkHeading")}
        </Heading>
        <MyAIComposer scopeId={scopeId} onActivity={() => setActive(true)} />
      </section>

      {/* "Show re-entry items" affordance — only shown post-activity,
          and only when there ARE grounded items to show, and only
          while they are currently hidden. */}
      {active && hasGrounded && !showReentry ? (
        <div
          style={{
            display: "flex",
            justifyContent: "flex-start",
            marginBottom: 16,
          }}
        >
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setShowReentry(true)}
            data-testid="my-ai-show-reentry"
          >
            {t("showReentry", { count: groundedItems.length })}
          </Button>
        </div>
      ) : null}

      {showGroundedSection ? (
        <section
          aria-labelledby="grounded-heading"
          data-testid="my-ai-grounded-section"
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1fr)",
            gap: 16,
            marginBottom: 24,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
            }}
          >
            <Heading level={2} id="grounded-heading">
              {t("groundedHeading")}
            </Heading>
            {active && showReentry ? (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowReentry(false)}
                data-testid="my-ai-hide-reentry"
              >
                {t("groundedHide")}
              </Button>
            ) : null}
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 12,
            }}
          >
            {groundedItems.map((item) => (
              <GroundedCard key={item.id} item={item} />
            ))}
          </div>
        </section>
      ) : null}

      {/* "Ready to share" — render only when there are real drafts.
          The endpoint returns [] today, so this whole section stays
          off until the drafts surface lands. No more empty-state
          noise. */}
      {hasDrafts ? (
        <section
          aria-labelledby="ready-heading"
          data-testid="my-ai-ready-section"
        >
          <Heading level={2} id="ready-heading">
            {t("readyHeading")}
          </Heading>
          {/* Draft renderer lands when /api/my-ai/landing actually
              populates ready_to_share. */}
        </section>
      ) : null}

      {/* Landing-only "nothing to pick up" empty state — shown when
          there are no grounded items AND the user hasn't started
          interacting. Once active, the empty state would be noise. */}
      {!hasGrounded && !active ? (
        <EmptyState data-testid="my-ai-landing-empty">
          {t("landingEmpty")}
        </EmptyState>
      ) : null}
    </main>
  );
}

function GroundedCard({ item }: { item: GroundedItem }) {
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
        </div>
        <Text variant="body">{item.title}</Text>
      </Card>
    </Link>
  );
}
